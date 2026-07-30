"""
India Food Health Index - Streamlit app.

Single-file app deliberately: Streamlit Community Cloud runs on 0.078-2 cores and
690 MB-2.7 GB of RAM, so the design goal is to load one Parquet file once, cache
it, and do all scoring in pure Python on demand.

Run locally:
    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scoring.additives import register_summary  # noqa: E402
from scoring.categories import CATEGORIES, as_list  # noqa: E402
from scoring.index import LADDER, score_product  # noqa: E402
from scoring.ingredients import render_tree  # noqa: E402

DATA = ROOT / "data" / "products.parquet"
REPORT = ROOT / "data" / "validation_report.json"

st.set_page_config(page_title="India Food Health Index", page_icon="🍪",
                   layout="wide", initial_sidebar_state="expanded")

# Score colours: red through amber to green, colour-blind-safe enough to be
# paired with the number and the word, never used alone.
BAND_COLOUR = {
    10: "#1a7f37", 9: "#2da44e", 8: "#4ac26b", 7: "#7ac142", 6: "#bf8700",
    5: "#d4a72c", 4: "#e16f24", 3: "#d1242f", 2: "#a40e26", 1: "#6e0b1c",
}


@st.cache_data(show_spinner="Loading product data…")
def load_products() -> pd.DataFrame:
    if not DATA.exists():
        return pd.DataFrame()
    df = pd.read_parquet(DATA)
    df["search_blob"] = (
        df["product_name"].fillna("").str.lower() + " "
        + df["brands"].fillna("").str.lower() + " "
        + df["code"].fillna("")
    )
    # One display label per product, used by the type-ahead. Name, brand and
    # barcode all live in the label so typing any of the three filters on it.
    df["display_label"] = [
        f"{(name or 'Unnamed product').strip()}"
        + (f" — {brand.strip()}" if isinstance(brand, str) and brand.strip() else "")
        + f"  ·  {code}"
        for name, brand, code in zip(df["product_name"], df["brands"], df["code"])
    ]
    return df


@st.cache_data(show_spinner=False)
def search_index() -> list[tuple[str, str, str]]:
    """(label, lowercase blob, barcode), ordered so recognisable products lead.

    Products with a name and a brand come first: the India subset contains 47
    unnamed records, and burying them keeps the suggestion list useful.
    """
    df = load_products()
    if df.empty:
        return []
    ordered = df.assign(
        _rank=df["product_name"].notna().astype(int) + df["brands"].notna().astype(int)
    ).sort_values(["_rank", "product_name"], ascending=[False, True])
    return list(zip(ordered["display_label"], ordered["search_blob"],
                    ordered["code"]))


def find_matches(query: str, limit: int = 200) -> list[tuple[str, str, str]]:
    """Case-insensitive, word-order-independent matching.

    Every whitespace-separated token must appear somewhere in the product's name,
    brand or barcode. So "digestive britannia" finds "Britannia NutriChoice
    Digestive" even though the words are in the other order, and case never
    matters because both sides are lowercased.
    """
    tokens = [t for t in query.lower().split() if t]
    if not tokens:
        return []
    out = []
    for label, blob, code in search_index():
        if all(token in blob for token in tokens):
            out.append((label, blob, code))
            if len(out) >= limit:
                break
    return out


@st.cache_data(show_spinner=False)
def score_all(_version: int = 1) -> pd.DataFrame:
    """Score every product once, for the browse and compare views."""
    df = load_products()
    if df.empty:
        return df
    rows = []
    for record in df.to_dict("records"):
        result = score_product(record)
        rows.append({
            "code": record["code"],
            "product_name": record.get("product_name"),
            "brands": record.get("brands"),
            "category": result.category.key if result.category else None,
            "category_display": result.category.display if result.category else None,
            "score": result.score,
            "label": result.band.label if result.band else None,
            "nutriscore": result.nutri.grade if result.nutri else None,
            "nova": result.processing.nova_group if result.processing else None,
            "confidence": result.confidence,
            "scoreable": result.scoreable,
            "energy_kcal": record.get("energy_kcal"),
            "sugars": record.get("sugars"),
            "saturated_fat": record.get("saturated_fat"),
            "sodium": record.get("sodium"),
            "fiber": record.get("fiber"),
            "proteins": record.get("proteins"),
        })
    return pd.DataFrame(rows)


def score_chip(score: int, label: str, *, big: bool = False) -> str:
    size = "2.6rem" if big else "1.3rem"
    pad = "0.55rem 1.1rem" if big else "0.2rem 0.6rem"
    return (
        f"<span style='background:{BAND_COLOUR[score]};color:#fff;"
        f"border-radius:10px;padding:{pad};font-size:{size};font-weight:700;"
        f"display:inline-block;line-height:1.15;'>{score}/10</span>"
        f"<span style='margin-left:.6rem;font-size:{'1.15rem' if big else '.95rem'};"
        f"font-weight:600;'>{label}</span>"
    )


def render_product(record: dict) -> None:
    result = score_product(record)
    name = record.get("product_name") or record.get("code")
    brands = record.get("brands")

    st.markdown(f"### {name}")
    meta = " · ".join(filter(None, [
        brands,
        record.get("quantity"),
        f"barcode {record['code']}",
        result.category.display if result.category else None,
    ]))
    st.caption(meta)

    if not result.scoreable:
        st.warning(f"**Not scored.** {result.refusal_reason}")
        with st.expander("Why refusing is the right answer here"):
            st.markdown(
                "A health score implies the number means something. For "
                "supplements, spices, infant food and cooking ingredients it "
                "does not — either the product is engineered to hit nutrient "
                "targets, or it is eaten in gram quantities where a per-100 g "
                "figure misleads, or it is separately regulated. Showing a "
                "confident number here would be worse than showing none."
            )
        _render_panel(record)
        return

    left, right = st.columns([1, 1.35])

    with left:
        st.markdown(score_chip(result.score, result.band.label, big=True),
                    unsafe_allow_html=True)
        st.markdown(f"<p style='margin-top:.7rem;font-size:1.02rem;'>"
                    f"{result.band.meaning}</p>", unsafe_allow_html=True)

        conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}[result.confidence]
        st.markdown(f"{conf_icon} **Confidence: {result.confidence}** "
                    f"(data tier {result.tier}/3)")
        st.caption(result.confidence_note)

        if result.binding_cap:
            st.error(f"**Score capped at {result.binding_cap.ceiling}/10.** "
                     f"{result.binding_cap.reason}")
            if result.uncapped_score and result.uncapped_score > result.score:
                st.caption(
                    f"Without that cap the weighted pillars alone would have given "
                    f"{result.uncapped_score}/10. The cap exists so a product "
                    f"cannot offset a serious excess with protein or fibre."
                )

    with right:
        st.markdown("**How the score was built**")
        for pillar in result.pillars:
            if not pillar.assessed:
                st.markdown(
                    f"<div style='opacity:.55;margin-bottom:.45rem;'>"
                    f"<b>{pillar.name}</b> — not assessed<br>"
                    f"<span style='font-size:.85rem;'>{pillar.detail}</span></div>",
                    unsafe_allow_html=True)
                continue
            st.markdown(
                f"<div style='margin-bottom:.15rem;'><b>{pillar.name}</b> "
                f"<span style='float:right;'>{pillar.subscore_0_100:.0f}/100 "
                f"<span style='opacity:.6'>× {pillar.weight:.0%}</span></span></div>",
                unsafe_allow_html=True)
            st.progress(min(1.0, pillar.subscore_0_100 / 100))
            st.caption(pillar.detail)

        assessed = [p for p in result.pillars if p.assessed]
        if len(assessed) < len(result.pillars):
            st.caption(
                f"Weights renormalised over the {len(assessed)} pillar(s) that "
                f"could be assessed, so missing data neither helps nor hurts the "
                f"score — it only lowers the confidence."
            )

    st.divider()
    tabs = st.tabs(["Nutrition", "WHO SEARO screen", "Processing", "Additives",
                    "Ingredient parse"])

    with tabs[0]:
        _render_panel(record)
        if result.rda:
            st.markdown("**Share of the FSSAI daily reference value, per 100 g**")
            st.caption("Same reference values Indian labels use: 2000 kcal, 67 g "
                       "fat, 22 g saturated fat, 2 g trans fat, 50 g added sugar, "
                       "2000 mg sodium (FSS Labelling and Display Regulations 2020).")
            st.dataframe(
                pd.DataFrame([{"nutrient": k.replace("_", " "), "% of daily value": v}
                              for k, v in result.rda.items()]),
                hide_index=True, use_container_width=True)
        if result.nutri:
            st.markdown(f"**Nutri-Score {result.nutri.grade}** "
                        f"(numeric {result.nutri.score:+d}, "
                        f"{result.nutri.variant} algorithm)")
            bd = pd.DataFrame([{"component": k, "points": v}
                               for k, v in result.nutri.breakdown.items() if v])
            if not bd.empty:
                st.dataframe(bd, hide_index=True, use_container_width=True)
            st.caption("Positive numbers count against the product, negative "
                       "numbers in its favour. 2023 algorithm, Nutri-Score "
                       "Scientific Committee.")
            if result.nutri.protein_capped:
                st.info("This product's protein points were excluded. Under the "
                        "2023 rules, once a product accumulates enough penalty "
                        "points its protein content no longer offsets them — "
                        "which stops a salty, fatty product scoring well on "
                        "protein alone.")

    with tabs[1]:
        searo = result.searo
        if not searo.applicable:
            st.info(searo.note)
        elif searo.passes:
            st.success("Passes every WHO SEARO threshold for its category.")
        else:
            st.error(f"{searo.breach_count} problem(s) found.")
            for field_name, value, limit in searo.breaches:
                st.markdown(f"- **{field_name.replace('_', ' ')}**: "
                            f"{value:g} vs a ceiling of {limit:g} per 100 g")
            for exclusion in searo.exclusions:
                st.markdown(f"- {exclusion}")
        st.caption(
            "The WHO nutrient profile model for the South-East Asia Region, "
            "pilot-tested in India. It is pass/fail per nutrient: exceed any one "
            "threshold and WHO would not permit the product to be marketed to "
            "children. Unlike a star rating, a breach here cannot be offset."
        )

    with tabs[2]:
        proc = result.processing
        if not proc.confident:
            st.info(proc.reason)
        else:
            st.markdown(f"**NOVA group {proc.nova_group}** — {proc.reason}")
            if proc.markers:
                st.markdown(f"**{len(proc.markers)} ultra-processing marker(s):**")
                st.dataframe(pd.DataFrame([
                    {"type": m.kind.replace("_", " "), "group": m.group,
                     "found on label": m.matched} for m in proc.markers
                ]), hide_index=True, use_container_width=True)
            st.caption(
                "NOVA group 4 is defined by markers, not by nutrients: "
                "ingredients never found in a home kitchen, plus cosmetic "
                "additives. Note that preservatives, antioxidants and acidity "
                "regulators are NOT cosmetic additives under NOVA and do not by "
                "themselves make a food ultra-processed."
            )

    with tabs[3]:
        add = result.additives
        if add is None or (not add.known and not add.invalid_codes):
            st.info("No additives identified on this label.")
        else:
            if add.flagged:
                st.markdown("**Additives carrying a penalty**")
                for a in add.flagged:
                    st.markdown(f"- **{a.name}** (INS {a.ins}) — penalty "
                                f"{a.penalty}/10, evidence: *{a.evidence}*")
                    st.caption(a.note)
                    if a.sources:
                        st.caption("Sources: " + "; ".join(a.sources))
            if add.combinations:
                st.markdown("**Combination risks**")
                for rule in add.combinations:
                    st.warning(rule.note)
            if add.cleared:
                st.markdown("**Present, but deliberately not penalised**")
                st.caption("These are often described online as harmful. The "
                           "evidence does not support a penalty, and saying so is "
                           "part of the job.")
                for a in add.cleared:
                    with st.expander(f"{a.name} (INS {a.ins}) — no penalty"):
                        st.write(a.note)
                        if a.sources:
                            st.caption("Sources: " + "; ".join(a.sources))
            if add.uncatalogued_codes:
                st.caption("Valid additives with no risk entry in this register "
                           "(scored as zero, not guessed): "
                           + ", ".join(c.upper() for c in add.uncatalogued_codes))
            if add.invalid_codes:
                st.caption("⚠️ Codes on this label that are not valid INS numbers — "
                           "likely a label typo or an OCR error: "
                           + ", ".join(c.upper() for c in add.invalid_codes))

    with tabs[4]:
        if result.label and result.label.ingredients:
            st.code(result.label.text, language=None)
            st.markdown("**Parsed structure**")
            st.code(render_tree(result.label), language=None)
            if result.label.allergens:
                st.markdown("**Allergens declared:** "
                            + ", ".join(result.label.allergens))
            if result.label.ecodes:
                st.markdown("**Additive codes found:** "
                            + ", ".join(c.upper() for c in result.label.ecodes))
        else:
            st.info("No ingredient list available for this product.")


def _render_panel(record: dict) -> None:
    fields = [("Energy", "energy_kcal", "kcal"), ("Protein", "proteins", "g"),
              ("Carbohydrate", "carbohydrates", "g"), ("  of which sugars", "sugars", "g"),
              ("  added sugars", "added_sugars", "g"), ("Dietary fibre", "fiber", "g"),
              ("Total fat", "fat", "g"), ("  saturated fat", "saturated_fat", "g"),
              ("  trans fat", "trans_fat", "g"), ("Sodium", "sodium", "g"),
              ("Salt", "salt", "g")]
    rows = []
    for label, key, unit in fields:
        value = record.get(key)
        rows.append({"per 100 g": label,
                     "value": f"{value:g} {unit}" if pd.notna(value) and value is not None
                     else "not declared"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    repairs = as_list(record.get("repairs"))
    issues = as_list(record.get("issues"))
    if repairs:
        st.caption("⚙️ Automatic corrections applied to this record: "
                   + ", ".join(repairs))
    if issues:
        st.caption("⚠️ Data-quality flags: " + ", ".join(issues))


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #

df = load_products()

st.sidebar.title("🍪 India Food Health Index")
if df.empty:
    st.sidebar.error("No dataset found.")
else:
    st.sidebar.caption(f"{len(df):,} packaged products sold in India, from Open "
                       f"Food Facts (ODbL).")
view = st.sidebar.radio("View", ["Search a product", "Browse & compare",
                                 "Best & worst", "How scoring works",
                                 "Data quality"])
st.sidebar.divider()
st.sidebar.caption(
    "**Not medical advice.** This is a student research project that rescales "
    "published nutrient-profiling models. It does not diagnose, treat or make "
    "claims about any disease, and no single food is good or bad on its own — "
    "the evidence behind every model here is about overall diet."
)
st.sidebar.markdown(
    "Built by **[Sahil Yadav](https://github.com/SahilYadav-op)**  \n"
    "[GitHub](https://github.com/SahilYadav-op/india-food-health-index) · "
    "[LinkedIn](https://www.linkedin.com/in/sahilgod01/)"
)

if df.empty:
    st.title("No data yet")
    st.markdown(
        "Build the dataset first:\n\n"
        "```bash\npython pipeline/harvest_off.py --max-products 4000\n"
        "python pipeline/build_dataset.py\n```"
    )
    st.stop()

if view == "Search a product":
    st.title("Search a product")

    # A product link should be shareable: /?code=8901719134845 opens that product
    # directly. Barcodes are the one stable identifier here, so they make better
    # URLs than names.
    deep_link = st.query_params.get("code")
    if deep_link and (df.code == deep_link).any():
        render_product(df[df.code == deep_link].iloc[0].to_dict())
        st.divider()
        if st.button("← Search for something else"):
            st.query_params.clear()
            st.rerun()
        st.stop()
    if deep_link:
        st.warning(f"No product with barcode {deep_link} in this dataset.")

    st.caption("Start typing — suggestions appear as you go. Upper or lower case "
               "makes no difference, and word order does not matter, so "
               "\"digestive britannia\" finds the same product as \"britannia "
               "digestive\". You can also paste a barcode.")

    # A selectbox rather than a text box: Streamlit filters its options live on
    # every keystroke and case-insensitively, whereas a text input only reacts
    # when you press Enter. Every label carries the product name, the brand and
    # the barcode, so typing any of the three narrows the list.
    index = search_index()
    labels = [label for label, _, _ in index]
    label_to_code = {label: code for label, _, code in index}

    picked_label = st.selectbox(
        "Product, brand or barcode",
        labels,
        index=None,
        placeholder="Type to search 3,000+ products — e.g. parle, maggi, kurkure, amul…",
    )

    if picked_label:
        record = df[df.code == label_to_code[picked_label]].iloc[0].to_dict()
        st.divider()
        render_product(record)
        st.caption(f"Shareable link for this product: `?code={record['code']}`")
    else:
        with st.expander("Multi-word search (word order does not matter)"):
            query = st.text_input("Type words in any order, then press Enter", "",
                                  placeholder="digestive britannia")
            if query.strip():
                matches = find_matches(query)
                if not matches:
                    st.info(
                        "Nothing matched. The dataset covers products that Open "
                        "Food Facts contributors have added for India, so "
                        "coverage is patchy — a missing product is a gap in the "
                        "data, not a verdict on the product."
                    )
                else:
                    st.caption(f"{len(matches)} match(es)")
                    chosen = st.selectbox("Choose one",
                                          [label for label, _, _ in matches])
                    st.session_state["picked"] = label_to_code[chosen]

        st.markdown("#### Or start from an example")
        examples = ["8901719134845", "8901491100519", "8901063142022",
                    "8901262150064", "8906017290026"]
        available = [c for c in examples if (df.code == c).any()]
        if available:
            cols = st.columns(len(available))
            for col, code in zip(cols, available):
                row = df[df.code == code].iloc[0]
                if col.button(f"{(row.product_name or code)[:24]}", key=f"eg_{code}",
                              use_container_width=True):
                    st.session_state["picked"] = code

        if st.session_state.get("picked"):
            st.divider()
            render_product(
                df[df.code == st.session_state["picked"]].iloc[0].to_dict())

elif view == "Browse & compare":
    st.title("Browse & compare")
    scored = score_all()
    scoreable = scored[scored.scoreable]

    cats = ["all"] + sorted(scoreable.category_display.dropna().unique().tolist())
    chosen_cat = st.selectbox("Category", cats)
    subset = scoreable if chosen_cat == "all" else \
        scoreable[scoreable.category_display == chosen_cat]

    col1, col2 = st.columns(2)
    min_conf = col1.select_slider("Minimum confidence",
                                  ["low", "medium", "high"], value="low")
    order = {"low": 0, "medium": 1, "high": 2}
    subset = subset[subset.confidence.map(order) >= order[min_conf]]
    sort_by = col2.selectbox("Sort by", ["score (best first)",
                                         "score (worst first)", "product name"])
    if sort_by.startswith("score (best"):
        subset = subset.sort_values("score", ascending=False)
    elif sort_by.startswith("score (worst"):
        subset = subset.sort_values("score")
    else:
        subset = subset.sort_values("product_name")

    st.caption(f"{len(subset)} products. Comparing within a category is the "
               f"useful move — the least bad biscuit is a real decision, whereas "
               f"a biscuit against a bottle of water is not.")
    st.dataframe(
        subset[["score", "label", "product_name", "brands", "category_display",
                "nutriscore", "nova", "confidence", "energy_kcal", "sugars",
                "saturated_fat", "sodium"]].rename(columns={
                    "product_name": "product", "category_display": "category",
                    "nutriscore": "Nutri-Score", "nova": "NOVA",
                    "energy_kcal": "kcal/100g", "sugars": "sugar g",
                    "saturated_fat": "sat fat g", "sodium": "sodium g"}),
        hide_index=True, use_container_width=True, height=560,
        column_config={"score": st.column_config.NumberColumn(
            "Score", help="1-10, higher is better", format="%d ⭐")},
    )

elif view == "Best & worst":
    st.title("Best & worst in each category")
    scored = score_all()
    scoreable = scored[(scored.scoreable) & (scored.confidence != "low")]
    st.caption("Low-confidence products are excluded here — a ranking is exactly "
               "where a half-known score does the most damage.")
    for cat in sorted(scoreable.category_display.dropna().unique()):
        sub = scoreable[scoreable.category_display == cat]
        if len(sub) < 4:
            continue
        with st.expander(f"{cat} ({len(sub)} products)"):
            a, b = st.columns(2)
            a.markdown("**Best**")
            for r in sub.nlargest(5, "score").itertuples():
                a.markdown(score_chip(r.score, r.product_name or r.code),
                           unsafe_allow_html=True)
            b.markdown("**Worst**")
            for r in sub.nsmallest(5, "score").itertuples():
                b.markdown(score_chip(r.score, r.product_name or r.code),
                           unsafe_allow_html=True)

elif view == "How scoring works":
    st.title("How scoring works")
    st.markdown("""
The score combines four pillars, each computed against a published source, then
applies hard caps that positive nutrients cannot buy off.

| Pillar | Weight | Source |
|---|---|---|
| Nutrients | 50% | Nutri-Score 2023 algorithm (Nutri-Score Scientific Committee) |
| Processing | 25% | NOVA classification (Monteiro et al.) |
| Additives | 15% | Evidence-graded register built from EFSA, JECFA and IARC positions |
| WHO SEARO screen | 10% | WHO nutrient profile model for South-East Asia |

The nutrient pillar leads because it is the only component with prospective
validation against hard outcomes — EPIC, n=471,495, HR 1.07 for total cancer
across quintiles of the underlying index. The processing pillar is second because
the ultra-processed-food evidence base is large and consistent but observational:
its strongest single result is RR 1.12 per 10-point increase in dietary UPF share.
""")
    st.subheader("The caps matter more than the weights")
    st.markdown("""
Every star rating that has been criticised in India — including FSSAI's own
withdrawn Indian Nutrition Rating — shares one flaw: a product can offset a
serious excess with protein and fibre and still show a respectable score. Here a
WHO SEARO breach lowers the **ceiling** instead:

| Trigger | Ceiling |
|---|---|
| 1 SEARO threshold breached | 7 |
| 2 breached | 5 |
| 3 or more breached | 4 |
| SEARO blanket exclusion (trans fat above 1% of energy, or a non-sugar sweetener) | 3 |
| Ultra-processed (NOVA group 4) | 8 |
| Contains a colour the EU warning-labels for child behaviour | 6 |
| Nutri-Score E | 4 |
""")
    st.subheader("The 1-10 ladder")
    st.dataframe(pd.DataFrame([
        {"score": b.score, "label": b.label, "meaning": b.meaning,
         "what puts a product here": b.basis}
        for b in sorted(LADDER.values(), key=lambda x: -x.score)
    ]), hide_index=True, use_container_width=True, height=420)

    st.subheader("What this project refuses to do")
    st.markdown("""
- **It will not call food toxic.** No packaged food sold legally in India is toxic
  at normal intake, and the evidence behind every model used here is about dietary
  patterns, not single items. The bottom of the scale says "harmful as a regular
  habit", which is what the evidence supports.
- **It will not penalise MSG.** The "Chinese restaurant syndrome" story began with
  a 1968 letter later reported to be a prank, and double-blind trials have not
  reproduced it. MSG is 12.3% sodium against table salt's 39.3%, so replacing salt
  with it lowers sodium. Its penalty here is zero, on purpose.
- **It will not charge palm oil twice.** Palm oil's effect on LDL cholesterol is
  fully explained by its saturated fat, which the nutrition panel already
  penalises. A separate palm-oil penalty would be double-counting.
- **It will not score supplements, spices, infant food or cooking ingredients.**
  A whey protein isolate scores near-perfect on every nutrient model ever
  published, which tells you nothing useful.
- **It will not guess.** A product missing core nutrition data gets no score.
""")
    st.subheader("Which numbers here are not sourced")
    st.markdown("""
The pillar weights, the 25-points-per-breach SEARO conversion, the 1-10 band
edges, and the cap ceilings are **judgement calls, not published values**. WHO
SEARO is a pass/fail model and publishes no severity scale, so any conversion of
it into a graded subscore requires an unsourced choice. The weights are ordered by
evidence strength, which is defensible; the exact values are not. They belong in an
ablation study, not in a claim of objectivity.
""")
    st.caption(f"Additive register: {register_summary()}")

elif view == "Data quality":
    st.title("Data quality")
    st.markdown("""
Crowd-sourced label data is wrong in specific, recognisable ways. This page exists
because a health score computed on a bad panel is worse than no score at all.
""")
    if REPORT.exists():
        import json
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        a, b, c, d = st.columns(4)
        a.metric("Raw records", f"{report.get('raw_records', 0):,}")
        b.metric("Passed validation", f"{report.get('passed', 0):,}")
        c.metric("Quarantined", f"{report.get('quarantined', 0):,}")
        d.metric("Duplicate barcodes", f"{report.get('duplicate_barcodes', 0):,}")

        st.subheader("Scoreability tiers")
        st.caption("Tier 0 cannot be scored at all. Tier 1 is nutrients only. "
                   "Tier 2 adds a parseable ingredient list. Tier 3 adds fibre "
                   "and either added sugars or a fruit/vegetable estimate.")
        tiers = report.get("tier_counts", {})
        st.dataframe(pd.DataFrame([{"tier": k, "products": v}
                                   for k, v in sorted(tiers.items())]),
                     hide_index=True, use_container_width=True)

        st.subheader("Field coverage")
        cov = report.get("nutrient_coverage", {})
        st.dataframe(pd.DataFrame([
            {"field": k, "coverage": f"{v:.1%}"} for k, v in
            sorted(cov.items(), key=lambda kv: -kv[1])
        ]), hide_index=True, use_container_width=True, height=400)

        st.subheader("Issues found")
        st.dataframe(pd.DataFrame([{"issue": k, "products": v} for k, v in
                                   report.get("issue_counts", {}).items()]),
                     hide_index=True, use_container_width=True)

    st.subheader("Repairs, not deletions")
    st.markdown("""
Three data errors are common enough on the India subset to be worth repairing
rather than discarding, because discarding them deletes exactly the brands people
search for:

- **Sodium in milligrams filed as grams.** Indian labels print sodium in mg and
  contributors copy the number as printed. Pure table salt is 39.3 g sodium per
  100 g, so anything above 40 is unambiguously mg. Left unrepaired, this deleted
  Britannia Marie Gold, Good Day, Kissan Ketchup and Top Ramen from the dataset.
- **Kilojoules typed into the kcal field.** Detected when the stated energy is
  about 4.184× the value reconstructed from the macronutrients.
- **A single impossible nutrient** — saturated fat above total fat, sugars above
  carbohydrate — is nulled rather than used, so the product survives at a lower
  data tier instead of vanishing.

One deliberate choice worth flagging: the mass-budget check sums fat,
carbohydrate, protein and salt only, **excluding fibre**. Labelling conventions
differ on whether declared carbohydrate already includes fibre, so counting it
double-penalises high-fibre products. Including fibre raised false failures from
27 to 148 — concentrated on atta, oats and millet products, which is to say on
the healthiest items in the corpus.
""")
    st.subheader("Known limits of this dataset")
    st.markdown("""
- Open Food Facts is crowd-sourced and **not ground truth**. One India record
  titled "Organic Goat Feed" carries an Indian biscuit's ingredient list.
- Roughly 250 product names appear more than once across 694 rows
  (`peanut butter` ×16, `sprite` ×8) — barcode-level deduplication does not
  resolve the same product listed under different barcodes.
- Only about a fifth of the OFF India subset has both complete nutrition and
  complete ingredients, so coverage is the binding constraint on this project,
  not the scoring model.
- Data is ODbL-licensed. Any redistribution of this dataset or a derived database
  must credit Open Food Facts and remain under ODbL.
""")
