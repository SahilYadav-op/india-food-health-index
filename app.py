"""India Food Health Index: Streamlit app.

Run locally with `streamlit run app.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scoring.additives import register_summary  # noqa: E402
from scoring.categories import as_list  # noqa: E402
from scoring.index import LADDER, score_product  # noqa: E402
from scoring.ingredients import render_tree  # noqa: E402
from scoring.suggest import better_alternatives  # noqa: E402

DATA = ROOT / "data" / "products.parquet"
REPORT = ROOT / "data" / "validation_report.json"

VIEWS = ["Search", "Compare", "Browse", "Best and worst", "How it works",
         "Data quality"]

st.set_page_config(page_title="India Food Health Index", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
    .block-container {max-width: 1080px; padding-top: 2.2rem;}
    .dot {display: inline-block; width: .6rem; height: .6rem;
          border-radius: 50%; margin-right: .45rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

BAND_COLOUR = {
    10: "#1a7f37", 9: "#2da44e", 8: "#4ac26b", 7: "#7ac142", 6: "#bf8700",
    5: "#d4a72c", 4: "#e16f24", 3: "#d1242f", 2: "#a40e26", 1: "#6e0b1c",
}
CONFIDENCE_COLOUR = {"high": "#2da44e", "medium": "#d4a72c", "low": "#d1242f"}


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _fmt(value, unit: str = "") -> str:
    v = _num(value)
    if v is None:
        return "n/a"
    return f"{round(v, 1):g}{(' ' + unit) if unit else ''}"


@st.cache_data(show_spinner=False)
def load_products() -> pd.DataFrame:
    if not DATA.exists():
        return pd.DataFrame()
    df = pd.read_parquet(DATA)
    df["search_blob"] = (
        df["product_name"].fillna("").str.lower() + " "
        + df["brands"].fillna("").str.lower() + " "
        + df["code"].fillna("")
    )
    df["display_label"] = [
        (name or "Unnamed product").strip()
        + (f" · {brand.strip()}" if isinstance(brand, str) and brand.strip() else "")
        + f" · {code}"
        for name, brand, code in zip(df["product_name"], df["brands"], df["code"])
    ]
    return df


@st.cache_data(show_spinner=False)
def search_index() -> list[tuple[str, str, str]]:
    """(label, lowercase text, barcode). Named, branded products come first."""
    df = load_products()
    if df.empty:
        return []
    ordered = df.assign(
        _rank=df["product_name"].notna().astype(int) + df["brands"].notna().astype(int)
    ).sort_values(["_rank", "product_name"], ascending=[False, True])
    return list(zip(ordered["display_label"], ordered["search_blob"],
                    ordered["code"]))


def find_matches(query: str, limit: int = 200) -> list[tuple[str, str, str]]:
    """Every word has to appear in the name, brand or barcode, in any order."""
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
def score_all() -> pd.DataFrame:
    df = load_products()
    if df.empty:
        return df
    rows = []
    for record in df.to_dict("records"):
        result = score_product(record)
        sodium = _num(record.get("sodium"))
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
            "sodium_mg": sodium * 1000 if sodium is not None else None,
            "fiber": record.get("fiber"),
            "proteins": record.get("proteins"),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def score_chip(score: int, label: str | None = None, *, big: bool = False) -> str:
    size = "2.6rem" if big else "1.05rem"
    pad = "0.5rem 1.1rem" if big else "0.15rem 0.55rem"
    chip = (
        f"<span style='background:{BAND_COLOUR[score]};color:#fff;"
        f"border-radius:8px;padding:{pad};font-size:{size};font-weight:700;"
        f"display:inline-block;line-height:1.15;'>{score}/10</span>"
    )
    if label:
        chip += (f"<span style='margin-left:.6rem;font-size:"
                 f"{'1.15rem' if big else '.95rem'};font-weight:600;'>{label}</span>")
    return chip


def open_product(code: str) -> None:
    st.query_params["code"] = code


def close_product() -> None:
    st.query_params.clear()
    for key in ("search_pick", "multi_pick"):
        st.session_state.pop(key, None)


def start_compare(code: str) -> None:
    label = {c: lab for lab, _, c in search_index()}.get(code)
    st.session_state["compare_pick"] = [label] if label else []
    st.session_state["view"] = "Compare"
    st.query_params.clear()


def nutrition_panel(record: dict) -> None:
    sodium = _num(record.get("sodium"))
    rows = [
        ("Energy", _fmt(record.get("energy_kcal"), "kcal")),
        ("Protein", _fmt(record.get("proteins"), "g")),
        ("Carbohydrate", _fmt(record.get("carbohydrates"), "g")),
        ("   of which sugars", _fmt(record.get("sugars"), "g")),
        ("   added sugars", _fmt(record.get("added_sugars"), "g")),
        ("Dietary fibre", _fmt(record.get("fiber"), "g")),
        ("Total fat", _fmt(record.get("fat"), "g")),
        ("   saturated fat", _fmt(record.get("saturated_fat"), "g")),
        ("   trans fat", _fmt(record.get("trans_fat"), "g")),
        ("Sodium", _fmt(sodium * 1000, "mg") if sodium is not None else "n/a"),
        ("Salt", _fmt(record.get("salt"), "g")),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Per 100 g", "Amount"]),
                 hide_index=True, use_container_width=True)
    repairs = as_list(record.get("repairs"))
    issues = as_list(record.get("issues"))
    if repairs:
        st.caption("Corrections applied to this record: " + ", ".join(repairs))
    if issues:
        st.caption("Data quality flags: " + ", ".join(issues))


# --------------------------------------------------------------------------- #
# product page
# --------------------------------------------------------------------------- #


def render_alternatives(result, record: dict, scored: pd.DataFrame) -> None:
    st.subheader("Better options in this category")
    alts = better_alternatives(scored, record["code"])
    if alts.empty:
        if result.score >= 8:
            st.write("Nothing in the dataset scores clearly higher in this category.")
        else:
            st.write("No clearly better option with reliable data in this category.")
        return

    sodium = _num(record.get("sodium"))
    st.caption(
        "Same category, at least 2 points higher, no more sugar, saturated fat "
        "or sodium than this one, and enough data to trust the score. Numbers "
        "are per 100 g. Check the pack too, recipes change."
    )
    st.caption(
        f"This product: sugar {_fmt(record.get('sugars'), 'g')} · "
        f"saturated fat {_fmt(record.get('saturated_fat'), 'g')} · "
        f"sodium {_fmt(sodium * 1000, 'mg') if sodium is not None else 'n/a'}"
    )
    for alt in alts.itertuples():
        c1, c2, c3 = st.columns([1, 5, 1.3])
        c1.markdown(score_chip(int(alt.score)), unsafe_allow_html=True)
        name = alt.product_name
        if isinstance(alt.brands, str) and alt.brands.strip():
            name += f"  ({alt.brands.split(',')[0].strip()})"
        c2.markdown(f"**{name}**")
        c2.caption(
            f"sugar {_fmt(alt.sugars, 'g')} · saturated fat "
            f"{_fmt(alt.saturated_fat, 'g')} · sodium {_fmt(alt.sodium_mg, 'mg')}"
        )
        c3.button("View", key=f"alt_{alt.code}", on_click=open_product,
                  args=(alt.code,))


def render_product(record: dict, scored: pd.DataFrame) -> None:
    result = score_product(record)
    name = record.get("product_name") or record.get("code")

    st.header(name)
    st.caption(" · ".join(filter(None, [
        record.get("brands"),
        record.get("quantity"),
        f"barcode {record['code']}",
        result.category.display if result.category else None,
    ])))

    if not result.scoreable:
        st.warning(f"No score for this product. {result.refusal_reason}")
        nutrition_panel(record)
        return

    left, right = st.columns([1, 1.35])

    with left:
        st.markdown(score_chip(result.score, result.band.label, big=True),
                    unsafe_allow_html=True)
        st.markdown(f"<p style='margin-top:.7rem;'>{result.band.meaning}</p>",
                    unsafe_allow_html=True)
        st.markdown(
            f"<span class='dot' style='background:"
            f"{CONFIDENCE_COLOUR[result.confidence]}'></span>"
            f"Confidence: {result.confidence}",
            unsafe_allow_html=True)
        st.caption(result.confidence_note)

        if result.binding_cap:
            st.error(f"Capped at {result.binding_cap.ceiling}/10. "
                     f"{result.binding_cap.reason}.")
            if result.uncapped_score and result.uncapped_score > result.score:
                st.caption(f"Without the cap it would have scored "
                           f"{result.uncapped_score}/10.")

        st.button("Compare with other products", on_click=start_compare,
                  args=(record["code"],))

    with right:
        st.markdown("**How the score was built**")
        for pillar in result.pillars:
            if not pillar.assessed:
                st.markdown(
                    f"<div style='opacity:.55;margin-bottom:.5rem;'>"
                    f"{pillar.name}: not assessed<br>"
                    f"<span style='font-size:.85rem;'>{pillar.detail}</span></div>",
                    unsafe_allow_html=True)
                continue
            st.markdown(
                f"{pillar.name} "
                f"<span style='opacity:.55;font-size:.85rem;'>"
                f"(weight {pillar.weight:.0%})</span>"
                f"<span style='float:right;'>{pillar.subscore_0_100:.0f} / 100</span>",
                unsafe_allow_html=True)
            st.progress(min(1.0, pillar.subscore_0_100 / 100))
            st.caption(pillar.detail)

        if any(not p.assessed for p in result.pillars):
            st.caption("Parts with no data are left out and the rest are "
                       "reweighted. Missing data doesn't raise or lower the "
                       "score, it only lowers the confidence.")

    st.divider()
    render_alternatives(result, record, scored)
    st.divider()

    tabs = st.tabs(["Nutrition", "WHO screen", "Processing", "Additives",
                    "Ingredients"])

    with tabs[0]:
        nutrition_panel(record)
        if result.rda:
            st.markdown("**Share of the daily reference value, per 100 g**")
            st.caption("The same reference values printed on Indian labels: "
                       "2000 kcal, 67 g fat, 22 g saturated fat, 2 g trans fat, "
                       "50 g added sugar, 2000 mg sodium.")
            st.dataframe(
                pd.DataFrame([{"Nutrient": k.replace("_", " "), "% of daily value": v}
                              for k, v in result.rda.items()]),
                hide_index=True, use_container_width=True)
        if result.nutri:
            st.markdown(f"**Nutri-Score {result.nutri.grade}** "
                        f"(score {result.nutri.score:+d}, "
                        f"{result.nutri.variant} version)")
            bd = pd.DataFrame([{"Component": k, "Points": v}
                               for k, v in result.nutri.breakdown.items() if v])
            if not bd.empty:
                st.dataframe(bd, hide_index=True, use_container_width=True)
            st.caption("Positive points count against the product, negative "
                       "points count in its favour.")
            if result.nutri.protein_capped:
                st.info("Protein points were left out. Under the 2023 rules, "
                        "once a product has enough penalty points its protein "
                        "no longer offsets them.")

    with tabs[1]:
        searo = result.searo
        if not searo.applicable:
            st.info(searo.note)
        elif searo.passes:
            st.success("Within every WHO threshold for its category.")
        else:
            st.error(f"{searo.breach_count} problem(s) found")
            for field_name, value, limit in searo.breaches:
                st.markdown(f"- {field_name.replace('_', ' ')}: {value:g} against "
                            f"a limit of {limit:g} per 100 g")
            for exclusion in searo.exclusions:
                st.markdown(f"- {exclusion}")
        st.caption("WHO's nutrient profile model for South-East Asia. Each "
                   "nutrient is pass or fail for the product's category. Going "
                   "over any limit means WHO would not allow it to be marketed "
                   "to children.")

    with tabs[2]:
        proc = result.processing
        if not proc.confident:
            st.info(proc.reason)
        else:
            st.markdown(f"**NOVA group {proc.nova_group}**. {proc.reason}.")
            if proc.markers:
                st.markdown(f"{len(proc.markers)} ultra-processing marker(s) found:")
                st.dataframe(pd.DataFrame([
                    {"Type": m.kind.replace("_", " "), "Group": m.group,
                     "Found on label": m.matched} for m in proc.markers
                ]), hide_index=True, use_container_width=True)
            st.caption("Group 4 (ultra-processed) is decided by what is in the "
                       "ingredient list: things you wouldn't find in a home "
                       "kitchen, and additives that only change taste, colour or "
                       "texture. Preservatives, antioxidants and acidity "
                       "regulators don't count.")

    with tabs[3]:
        add = result.additives
        if add is None or (not add.known and not add.invalid_codes):
            st.info("No additives found on this label.")
        else:
            if add.flagged:
                st.markdown("**Counted against the product**")
                for a in add.flagged:
                    st.markdown(f"- {a.name} (INS {a.ins}), penalty {a.penalty}/10, "
                                f"evidence: {a.evidence}")
                    st.caption(a.note)
                    if a.sources:
                        st.caption("Sources: " + "; ".join(a.sources))
            if add.combinations:
                st.markdown("**Combinations**")
                for rule in add.combinations:
                    st.warning(rule.note)
            if add.cleared:
                st.markdown("**Present, but not penalised**")
                st.caption("These come up in online scare posts. The evidence "
                           "doesn't support a penalty.")
                for a in add.cleared:
                    with st.expander(f"{a.name} (INS {a.ins})"):
                        st.write(a.note)
                        if a.sources:
                            st.caption("Sources: " + "; ".join(a.sources))
            if add.uncatalogued_codes:
                st.caption("Valid additive codes not in the register, scored as "
                           "zero: " + ", ".join(c.upper() for c in add.uncatalogued_codes))
            if add.invalid_codes:
                st.caption("Codes on this label that aren't valid INS numbers, "
                           "probably a typo: "
                           + ", ".join(c.upper() for c in add.invalid_codes))

    with tabs[4]:
        if result.label and result.label.ingredients:
            st.code(result.label.text, language=None)
            st.markdown("**How the label was read**")
            st.code(render_tree(result.label), language=None)
            if result.label.allergens:
                st.markdown("Allergens declared: " + ", ".join(result.label.allergens))
            if result.label.ecodes:
                st.markdown("Additive codes found: "
                            + ", ".join(c.upper() for c in result.label.ecodes))
        else:
            st.info("No ingredient list for this product.")


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #


def view_search(df: pd.DataFrame, scored: pd.DataFrame) -> None:
    code = st.query_params.get("code")
    if code and (df.code == code).any():
        st.button("Back to search", on_click=close_product)
        render_product(df[df.code == code].iloc[0].to_dict(), scored)
        return
    if code:
        st.warning(f"No product with barcode {code} in this dataset.")

    st.title("Find a product")
    st.write("Type a product name, a brand or a barcode. Capital letters don't matter.")

    index = search_index()
    labels = [label for label, _, _ in index]
    label_to_code = {label: c for label, _, c in index}

    picked = st.selectbox("Product", labels, index=None, key="search_pick",
                          placeholder="For example: parle, maggi, kurkure",
                          label_visibility="collapsed")
    if picked:
        open_product(label_to_code[picked])
        st.rerun()

    with st.expander("Search with several words"):
        query = st.text_input("Words in any order", "", placeholder="digestive britannia")
        if query.strip():
            matches = find_matches(query)
            if not matches:
                st.info("Nothing matched. This dataset only has products that "
                        "Open Food Facts contributors added for India, so a "
                        "missing product says nothing about it.")
            else:
                st.caption(f"{len(matches)} match(es)")
                chosen = st.selectbox("Pick one", [m[0] for m in matches],
                                      index=None, key="multi_pick")
                if chosen:
                    open_product(label_to_code[chosen])
                    st.rerun()

    scoreable = scored[scored.scoreable]
    a, b, c = st.columns(3)
    a.metric("Products", f"{len(df):,}")
    b.metric("With a score", f"{len(scoreable):,}")
    c.metric("Average score", f"{scoreable.score.mean():.1f} / 10")

    st.markdown("#### Try one")
    examples = ["8901719134845", "8901491100519", "8901063142022",
                "8901262150064", "8906017290026"]
    available = [e for e in examples if (df.code == e).any()]
    if available:
        cols = st.columns(len(available))
        for col, ex in zip(cols, available):
            row = df[df.code == ex].iloc[0]
            col.button(str(row.product_name or ex)[:22], key=f"eg_{ex}",
                       use_container_width=True, on_click=open_product, args=(ex,))


def view_compare(df: pd.DataFrame) -> None:
    st.title("Compare products")
    st.write("Pick two or three products. All numbers are per 100 g.")

    index = search_index()
    labels = [label for label, _, _ in index]
    label_to_code = {label: c for label, _, c in index}

    picks = st.multiselect("Products", labels, key="compare_pick",
                           max_selections=3, placeholder="Search and add a product")
    if len(picks) < 2:
        st.info("Add at least two products.")
        return

    # (row label, column, better when higher?)
    metrics = [
        ("Score (out of 10)", "score", True),
        ("Energy (kcal)", "energy_kcal", False),
        ("Sugars (g)", "sugars", False),
        ("Saturated fat (g)", "saturated_fat", False),
        ("Sodium (mg)", "sodium_mg", False),
        ("Fibre (g)", "fiber", True),
        ("Protein (g)", "proteins", True),
    ]

    scored = score_all().set_index("code")
    columns: dict[str, dict[str, float | None]] = {}
    head = st.columns(len(picks))
    for slot, label in zip(head, picks):
        code = label_to_code[label]
        row = scored.loc[code]
        title = str(row.product_name or code)
        if title in columns:
            title = f"{title} ({code[-4:]})"
        columns[title] = {m[0]: _num(row[m[1]]) for m in metrics}
        with slot:
            st.markdown(f"**{title}**")
            if row.scoreable:
                st.markdown(score_chip(int(row.score), row.label), unsafe_allow_html=True)
            else:
                st.caption("Not scored")
            st.caption(str(row.category_display))

    table = pd.DataFrame(columns, index=[m[0] for m in metrics])
    higher = {m[0]: m[2] for m in metrics}

    def best_in_row(row: pd.Series) -> list[str]:
        vals = row.astype(float)
        if vals.notna().sum() < 2 or vals.nunique() < 2:
            return [""] * len(row)
        target = vals.max() if higher[row.name] else vals.min()
        return ["background-color:#dff0e3;font-weight:600" if v == target else ""
                for v in vals]

    try:
        styled = (table.style.apply(best_in_row, axis=1)
                  .format(lambda v: "n/a" if pd.isna(v) else f"{round(v, 1):g}"))
        st.dataframe(styled, use_container_width=True)
    except Exception:
        st.dataframe(table.round(1), use_container_width=True)
    st.caption("Green marks the better value in each row: higher for score, fibre "
               "and protein, lower for everything else.")


def view_browse(scored: pd.DataFrame) -> None:
    st.title("Browse")
    scoreable = scored[scored.scoreable]

    cats = ["All categories"] + sorted(scoreable.category_display.dropna().unique().tolist())
    c1, c2, c3 = st.columns([2, 2, 2])
    chosen = c1.selectbox("Category", cats)
    min_conf = c2.select_slider("Minimum confidence", ["low", "medium", "high"],
                                value="low")
    sort_by = c3.selectbox("Sort by", ["Best first", "Worst first", "Name"])

    subset = scoreable if chosen == "All categories" else \
        scoreable[scoreable.category_display == chosen]
    order = {"low": 0, "medium": 1, "high": 2}
    subset = subset[subset.confidence.map(order) >= order[min_conf]]
    if sort_by == "Best first":
        subset = subset.sort_values("score", ascending=False)
    elif sort_by == "Worst first":
        subset = subset.sort_values("score")
    else:
        subset = subset.sort_values("product_name")

    st.caption(f"{len(subset)} products. Compare within a category: the least bad "
               "biscuit is a real choice, a biscuit against water is not.")
    st.dataframe(
        subset[["score", "label", "product_name", "brands", "category_display",
                "nutriscore", "nova", "confidence", "energy_kcal", "sugars",
                "saturated_fat", "sodium_mg"]].rename(columns={
                    "score": "Score", "label": "Rating", "product_name": "Product",
                    "brands": "Brand", "category_display": "Category",
                    "nutriscore": "Nutri-Score", "nova": "NOVA",
                    "confidence": "Confidence", "energy_kcal": "kcal",
                    "sugars": "Sugar (g)", "saturated_fat": "Sat fat (g)",
                    "sodium_mg": "Sodium (mg)"}),
        hide_index=True, use_container_width=True, height=560)


def view_best_worst(scored: pd.DataFrame) -> None:
    st.title("Best and worst by category")
    st.caption("Products with low-confidence scores are left out of these lists.")
    pool = scored[(scored.scoreable) & (scored.confidence != "low")]
    for cat in sorted(pool.category_display.dropna().unique()):
        sub = pool[pool.category_display == cat]
        if len(sub) < 4:
            continue
        with st.expander(f"{cat} ({len(sub)} products)"):
            a, b = st.columns(2)
            a.markdown("**Best**")
            for r in sub.nlargest(5, "score").itertuples():
                a.markdown(score_chip(int(r.score), r.product_name or r.code),
                           unsafe_allow_html=True)
            b.markdown("**Worst**")
            for r in sub.nsmallest(5, "score").itertuples():
                b.markdown(score_chip(int(r.score), r.product_name or r.code),
                           unsafe_allow_html=True)


def view_how() -> None:
    st.title("How it works")
    st.write(
        "Each product gets a score from 1 to 10. It is built from four parts, "
        "each based on a published source, and then limited by caps that extra "
        "protein or fibre can't get around."
    )
    st.markdown(f"""
| Part | Weight | What it uses |
|---|---|---|
| Nutrients | 50% | The Nutri-Score 2023 algorithm, applied to the nutrition panel |
| Processing | 25% | NOVA group, worked out from the ingredient list |
| Additives | 15% | A table of {register_summary()['total']} additives, graded by how strong the evidence is |
| WHO screen | 10% | WHO's nutrient profile model for South-East Asia, pass or fail per nutrient |
""")
    st.write(
        "Nutri-Score gets the most weight because it is the only one of the four "
        "that has been tested against long-term health outcomes in large studies. "
        "The processing evidence is large but observational, so it comes second."
    )

    st.subheader("Caps")
    st.write(
        "A known weakness of star ratings is that a product can make up for a lot "
        "of salt or sugar with some protein or fibre and still look fine. So going "
        "over WHO's limits lowers the highest score a product can get."
    )
    st.markdown("""
| Trigger | Highest possible score |
|---|---|
| Over 1 WHO limit | 7 |
| Over 2 WHO limits | 5 |
| Over 3 or more | 4 |
| Trans fat above 1% of energy, or any added non-sugar sweetener | 3 |
| Ultra-processed (NOVA group 4) | 8 |
| Contains a colour the EU puts a child-behaviour warning on | 6 |
| Nutri-Score E | 4 |
""")

    st.subheader("The scale")
    st.dataframe(pd.DataFrame([
        {"Score": b.score, "Rating": b.label, "Meaning": b.meaning}
        for b in sorted(LADDER.values(), key=lambda x: -x.score)
    ]), hide_index=True, use_container_width=True, height=420)

    st.subheader("Choices that might surprise you")
    st.markdown("""
- **MSG isn't penalised.** The scare started with a 1968 letter and blinded trials haven't reproduced the symptoms. It also has about a third of the sodium of table salt by weight, and any sodium is already counted from the nutrition panel. Saccharin and food-grade carrageenan get no penalty for similar reasons.
- **Palm oil has no penalty of its own.** Its effect on cholesterol comes from its saturated fat, which is already counted.
- **Some products get no score:** supplements, spices, infant food, cooking ingredients and alcohol. A protein powder looks perfect on every nutrient model, and spices are eaten by the gram.
- **No score if the nutrition panel is incomplete.** A guessed score is worse than none.
- **Nothing is called toxic.** The lowest rating says "harmful as a regular habit", because the evidence is about long-term eating patterns, not one packet.
""")

    st.subheader("What is a judgement call")
    st.write(
        "Four things are not from any published source: the weights of the four "
        "parts, the 25 points taken off per WHO limit exceeded, the cut-offs "
        "between the 1 to 10 ratings, and the cap values. WHO's model is pass or "
        "fail and doesn't say how bad a breach is, so turning it into a number "
        "needed a choice. The Nutri-Score tables, the WHO limits and the additive "
        "grades all come from the published documents."
    )

    st.subheader("Where the data comes from")
    st.write(
        "Product data is from Open Food Facts, an open, crowd-sourced database "
        "(ODbL licence). Some entries are wrong or incomplete, so the data is "
        "checked and repaired where possible. See the Data quality page."
    )


def view_data_quality() -> None:
    st.title("Data quality")
    st.write(
        "Crowd-sourced label data has mistakes, and a score built on a bad "
        "nutrition panel is worse than no score. Here is what was checked."
    )
    if REPORT.exists():
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        a, b, c, d = st.columns(4)
        a.metric("Records pulled", f"{report.get('raw_records', 0):,}")
        b.metric("Kept", f"{report.get('passed', 0):,}")
        c.metric("Dropped", f"{report.get('quarantined', 0):,}")
        d.metric("Duplicate barcodes", f"{report.get('duplicate_barcodes', 0):,}")

        st.subheader("How much of each record is filled in")
        cov = report.get("nutrient_coverage", {})
        st.dataframe(pd.DataFrame([
            {"Field": k.replace("_", " "), "Share of products": f"{v:.0%}"}
            for k, v in sorted(cov.items(), key=lambda kv: -kv[1])
        ]), hide_index=True, use_container_width=True, height=400)
        st.caption(f"Ingredient lists: {report.get('ingredient_coverage', 0):.0%} of "
                   "products. Fibre and added sugar are the gaps that matter most.")

        st.subheader("Problems found")
        st.dataframe(pd.DataFrame([{"Problem": k.replace("_", " "), "Products": v}
                                   for k, v in report.get("issue_counts", {}).items()]),
                     hide_index=True, use_container_width=True)

    st.subheader("Fixed instead of thrown away")
    st.markdown("""
- **Sodium entered in milligrams where grams were expected.** Indian labels print sodium in mg and contributors copy the number. Table salt is 39 g of sodium per 100 g, so any value above 40 has to be mg. Dropping these records would have removed Britannia Marie Gold, Good Day, Kissan Ketchup and Top Ramen.
- **Kilojoules entered as kilocalories.** Spotted when the stated energy is about 4.2 times what the fat, carbohydrate and protein add up to.
- **One impossible value**, like saturated fat above total fat. That one field is blanked and the product keeps its other numbers.
- **Fibre is left out of the "adds up to 100 g" check.** Labels disagree on whether carbohydrate already includes fibre, so counting it wrongly failed high-fibre products like atta and oats.
""")

    st.subheader("Known limits")
    st.markdown("""
- Open Food Facts isn't ground truth. One India record called "Organic Goat Feed" has an Indian biscuit's ingredient list.
- The same product can be listed under different barcodes (around 250 repeated names in this data).
- Only about a fifth of Open Food Facts' India products have both a full nutrition panel and a full ingredient list.
- Everything is per 100 g. A small packet and a large one score the same.
""")


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #

df = load_products()

st.sidebar.title("India Food Health Index")
if df.empty:
    st.sidebar.error("No dataset found.")
else:
    st.sidebar.caption(f"{len(df):,} packaged products sold in India, from Open "
                       "Food Facts.")
view = st.sidebar.radio("Pages", VIEWS, key="view", label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.caption(
    "Not medical advice. A student project that applies published "
    "nutrient-profiling models. It makes no health claims about any single food."
)
st.sidebar.markdown(
    "Built by **[Sahil Yadav](https://github.com/SahilYadav-op)**  \n"
    "[GitHub](https://github.com/SahilYadav-op/india-food-health-index) · "
    "[LinkedIn](https://www.linkedin.com/in/sahilgod01/)"
)

if df.empty:
    st.title("No data yet")
    st.code("python pipeline/harvest_off.py --max-products 4000\n"
            "python pipeline/build_dataset.py", language="bash")
    st.stop()

with st.spinner("Scoring products (first visit only)"):
    scored = score_all()

if view == "Search":
    view_search(df, scored)
elif view == "Compare":
    view_compare(df)
elif view == "Browse":
    view_browse(scored)
elif view == "Best and worst":
    view_best_worst(scored)
elif view == "How it works":
    view_how()
else:
    view_data_quality()
