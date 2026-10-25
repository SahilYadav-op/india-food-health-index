"""India Food Health Index: Streamlit app.

Run locally with `streamlit run app.py`.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scoring.additives import register_summary  # noqa: E402
from scoring.categories import CATEGORIES, as_list  # noqa: E402
from scoring.custom import (NUTRIENT_FIELDS, input_warnings, parse_number,  # noqa: E402
                            row_from_inputs)
from scoring.index import LADDER, score_product  # noqa: E402
from scoring.ingredients import render_tree  # noqa: E402
from scoring.limits import LIMITS, daily_shares, serving_grams  # noqa: E402
from scoring.suggest import better_alternatives  # noqa: E402

DATA = ROOT / "data" / "products.parquet"
REPORT = ROOT / "data" / "validation_report.json"

VIEWS = ["Search", "Compare", "Check a label", "Browse", "Highest and lowest",
         "How it works", "Data quality", "About"]

ISSUES_URL = "https://github.com/SahilYadav-op/india-food-health-index/issues"

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


def _is_named(name) -> bool:
    if not isinstance(name, str):
        return False
    name = name.strip()
    return bool(name) and not name.isdigit() and name.lower() not in {"none", "null", "n/a"}


def _last_edited(value) -> str | None:
    """'Mar 2024' from a Unix timestamp, or None."""
    v = _num(value)
    if v is None or v <= 0:
        return None
    return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%b %Y")


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
    """(label, lowercase text, barcode), in the order the dropdown shows them.

    Named, branded products come first. Supplements go to the very end: they have
    no score, and the default list is alphabetical, so "100% Whey" and similar
    names were turning up among the first things a visitor sees. They can still be
    found by typing.
    """
    df = load_products()
    if df.empty:
        return []
    scored = score_all()
    supplement_codes = set(scored.loc[scored.category == "supplement", "code"])
    ordered = df.assign(
        _supplement=df["code"].isin(supplement_codes).astype(int),
        _rank=df["product_name"].notna().astype(int) + df["brands"].notna().astype(int),
    ).sort_values(["_supplement", "_rank", "product_name"],
                  ascending=[True, False, True])
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


def scored_row(record: dict, result) -> dict:
    """One row of the table the list pages and the suggestions are built from."""
    sodium = _num(record.get("sodium"))
    return {
        "code": record["code"],
        "product_name": record.get("product_name"),
        "brands": record.get("brands"),
        # A record with no name, or only its barcode as a name, can't be shown
        # in a list of products without looking broken or naming nothing.
        "named": _is_named(record.get("product_name")),
        "category": result.category.key if result.category else None,
        "category_display": result.category.display if result.category else None,
        "score": result.score,
        "label": result.band.label if result.band else None,
        "nutriscore": result.nutri.grade if result.nutri else None,
        "nova": result.processing.nova_group if result.processing else None,
        "confidence": result.confidence,
        "scoreable": result.scoreable,
        "refusal_reason": result.refusal_reason,
        "energy_kcal": record.get("energy_kcal"),
        "sugars": record.get("sugars"),
        "saturated_fat": record.get("saturated_fat"),
        "sodium_mg": sodium * 1000 if sodium is not None else None,
        "fiber": record.get("fiber"),
        "proteins": record.get("proteins"),
    }


@st.cache_data(show_spinner=False)
def score_all() -> pd.DataFrame:
    df = load_products()
    if df.empty:
        return df
    return pd.DataFrame([scored_row(record, score_product(record))
                         for record in df.to_dict("records")])


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


def set_product(code: str) -> None:
    st.query_params["code"] = code


def open_product(code: str) -> None:
    """Button callback: show a product on the Search page, from any page.

    Only callbacks may change the sidebar's selected page. Changing it from the
    body of a run, after the sidebar has been drawn, raises an error.
    """
    set_product(code)
    st.session_state["view"] = "Search"


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
    st.subheader("Higher-scoring products in this category")
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


def render_daily_limits(record: dict, key: str) -> None:
    """How much of each daily limit a portion uses up. Arithmetic, not a health claim."""
    default = serving_grams(record.get("serving_size"))
    portion = st.number_input(
        "Portion size (g or ml)", min_value=1.0, max_value=2000.0,
        value=float(default) if default else 100.0, step=5.0,
        key=f"portion_{key}_{default or 'x'}",
        help="Starts at the serving size on the label when there is one, "
             "otherwise 100 g.")
    if not default:
        st.caption("No serving size on this record, so it starts at 100 g.")

    shares = daily_shares(record, portion)
    if not shares:
        st.info("There aren't enough numbers on this record to work this out.")
        return

    st.dataframe(pd.DataFrame([{
        "Nutrient": s.label,
        f"In {portion:g} g": f"{round(s.in_portion, 1):g} {s.unit}",
        "% of daily limit": round(s.percent),
        "Portions to reach the limit": (f"{s.portions_to_limit:.1f}"
                                        if s.portions_to_limit else "n/a"),
    } for s in shares]), hide_index=True, use_container_width=True)

    for s in shares:
        if s.note:
            st.caption(f"{s.label}: {s.note}")
    st.caption(
        "Limits for an adult on a 2000 kcal diet, from WHO guidance and the "
        "reference values FSSAI prints on Indian labels:"
    )
    for limit in LIMITS:
        st.caption(f"{limit.label}, {limit.amount:g} {limit.unit} a day. {limit.source}")
    st.caption(
        "This compares the numbers with published limits. It doesn't say what "
        "the product does to anyone. Your own needs may differ, so ask a doctor "
        "or dietitian."
    )


def render_product(record: dict, scored: pd.DataFrame) -> None:
    render_result(record, score_product(record), scored, custom=False)


def render_result(record: dict, result, scored: pd.DataFrame, *, custom: bool) -> None:
    name = record.get("product_name") or ("Your product" if custom else record.get("code"))

    st.header(name)
    if custom:
        st.caption(f"{result.category.display} · based on the numbers you entered. "
                   "Nothing is saved. The score is an automated calculation, not a "
                   "safety rating or medical advice.")
    else:
        st.caption(" · ".join(filter(None, [
            record.get("brands"),
            record.get("quantity"),
            f"barcode {record['code']}",
            result.category.display if result.category else None,
        ])))
        edited = _last_edited(record.get("last_modified_t"))
        st.caption(
            "Label data from Open Food Facts"
            + (f", record last edited {edited}" if edited else "")
            + f". [See or correct the source record]"
            f"(https://world.openfoodfacts.org/product/{record['code']}). "
            "It can be wrong or out of date, so check the pack. The score is an "
            "automated calculation, not a safety rating or medical advice."
        )

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

        if not custom:
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
    # A typed-in label isn't in the table, so add it for the suggestions lookup.
    typed = {k: v for k, v in scored_row(record, result).items() if v is not None}
    pool = (pd.concat([scored, pd.DataFrame([typed])], ignore_index=True)
            if custom else scored)
    render_alternatives(result, record, pool)
    st.divider()

    tabs = st.tabs(["Nutrition", "Daily limits", "WHO screen", "Processing",
                    "Additives", "Ingredients"])
    t_nutrition, t_daily, t_who, t_proc, t_add, t_ingr = tabs

    with t_daily:
        render_daily_limits(record, str(record["code"]))

    with t_nutrition:
        nutrition_panel(record)
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

    with t_who:
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
                   "nutrient has a limit for the product's category. WHO designed "
                   "the limits to decide which foods shouldn't be marketed to "
                   "children. Here they are only a yardstick, not a ruling on "
                   "any product.")

    with t_proc:
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

    with t_add:
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

    with t_ingr:
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
        set_product(label_to_code[picked])
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
                    set_product(label_to_code[chosen])
                    st.rerun()

    scoreable = scored[scored.scoreable]
    a, b, c = st.columns(3)
    a.metric("Products in this dataset", f"{len(df):,}")
    b.metric("With a score", f"{len(scoreable):,}")
    c.metric("Average score", f"{scoreable.score.mean():.1f} / 10")
    st.caption("Only products that people have added to Open Food Facts, so this "
               "isn't a picture of the whole market.")

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


def clear_check() -> None:
    st.session_state.pop("custom_record", None)


def view_check(scored: pd.DataFrame) -> None:
    st.title("Check a label")
    st.write(
        "Type in the numbers from the back of a pack to get a score, and to see "
        "how much of the daily limits a portion uses up. Nothing you type is saved."
    )

    categories = {c.display: c.key for c in CATEGORIES.values()
                  if c.scoreable and c.key != "general"}
    options = dict(sorted(categories.items())) | {
        CATEGORIES["general"].display: "general"}

    with st.form("check_label"):
        name = st.text_input("Product name (optional)")
        category = st.selectbox(
            "What kind of product is it?", list(options), index=None,
            placeholder="Choose the closest match",
            help="The WHO limits depend on the kind of product. 'Other packaged "
                 "food' has no WHO limits, so that part is left out.")
        basis = st.radio("The numbers on the pack are",
                         ["Per 100 g (or 100 ml)", "Per serving"], horizontal=True)
        serving = st.text_input(
            "Serving size in g or ml",
            help="Needed if the numbers are per serving. Also used for the daily "
                 "limits.")

        st.markdown("**Nutrition numbers.** Leave a box empty if the pack doesn't "
                    "show it. An empty box means unknown, not zero.")
        c1, c2, c3 = st.columns(3)
        energy = c1.text_input("Energy (kcal)")
        protein = c2.text_input("Protein (g)")
        carbs = c3.text_input("Carbohydrate (g)")
        sugars = c1.text_input("of which sugars (g)")
        added = c2.text_input("added sugars (g)")
        fibre = c3.text_input("Dietary fibre (g)")
        fat = c1.text_input("Total fat (g)")
        sat = c2.text_input("Saturated fat (g)")
        trans = c3.text_input("Trans fat (g)")
        sodium = c1.text_input("Sodium (mg)")
        salt = c2.text_input("or Salt (g)",
                             help="If you give both, sodium is used.")
        ingredients = st.text_area(
            "Ingredient list (optional)",
            placeholder="Copy the ingredient list as printed, including INS numbers",
            help="Without it the score uses the nutrition numbers only, and "
                 "processing and additives aren't assessed.")
        submitted = st.form_submit_button("Score it")

    if submitted:
        raw = {"energy_kcal": energy, "proteins": protein, "carbohydrates": carbs,
               "sugars": sugars, "added_sugars": added, "fat": fat,
               "saturated_fat": sat, "trans_fat": trans, "fiber": fibre}
        try:
            values = {k: parse_number(v) for k, v in raw.items()}
            sodium_mg, salt_g, serving_g = (parse_number(sodium), parse_number(salt),
                                            parse_number(serving))
        except ValueError as exc:
            st.error(f"{exc}. Use plain numbers, like 12 or 12.5.")
            return
        if not category:
            st.error("Choose what kind of product it is.")
            return
        try:
            row = row_from_inputs(
                name=name, category_key=options[category],
                per_serving=basis == "Per serving", serving_g=serving_g,
                values=values, sodium_mg=sodium_mg, salt_g=salt_g,
                ingredients=ingredients)
        except ValueError as exc:
            st.error(str(exc))
            return
        if serving_g:
            row["serving_size"] = f"{serving_g:g} g"
        st.session_state["custom_record"] = row

    row = st.session_state.get("custom_record")
    if not row:
        return

    st.divider()
    for warning in input_warnings(row):
        st.warning(warning)
    st.button("Clear and start again", on_click=clear_check)
    render_result(row, score_product(row), scored, custom=True)


def view_browse(scored: pd.DataFrame) -> None:
    st.title("Browse")
    scoreable = scored[scored.scoreable & scored.named]

    cats = ["All categories"] + sorted(scoreable.category_display.dropna().unique().tolist())
    c1, c2, c3 = st.columns([2, 2, 2])
    chosen = c1.selectbox("Category", cats)
    min_conf = c2.select_slider("Minimum confidence", ["low", "medium", "high"],
                                value="low")
    sort_by = c3.selectbox("Sort by", ["Highest first", "Lowest first", "Name"])

    subset = scoreable if chosen == "All categories" else \
        scoreable[scoreable.category_display == chosen]
    order = {"low": 0, "medium": 1, "high": 2}
    subset = subset[subset.confidence.map(order) >= order[min_conf]]
    if sort_by == "Highest first":
        subset = subset.sort_values("score", ascending=False)
    elif sort_by == "Lowest first":
        subset = subset.sort_values("score")
    else:
        subset = subset.sort_values("product_name")

    st.caption(f"{len(subset)} products. Compare within a category: two biscuits "
               "can be compared, a biscuit and a bottle of water can't.")
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


def view_highest_lowest(scored: pd.DataFrame) -> None:
    st.title("Highest and lowest scores by category")
    st.caption("Scores come from label data on Open Food Facts, which can be wrong "
               "or out of date. Products with low-confidence scores are left out.")
    pool = scored[scored.scoreable & scored.named & (scored.confidence != "low")]
    for cat in sorted(pool.category_display.dropna().unique()):
        sub = pool[pool.category_display == cat]
        if len(sub) < 4:
            continue
        with st.expander(f"{cat} ({len(sub)} products)"):
            a, b = st.columns(2)
            a.markdown("**Highest scores**")
            for r in sub.nlargest(5, "score").itertuples():
                a.markdown(score_chip(int(r.score), r.product_name or r.code),
                           unsafe_allow_html=True)
            b.markdown("**Lowest scores**")
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

    st.subheader("Daily limits")
    st.write(
        "Each product page also has a Daily limits tab. It shows how much of the "
        "daily limits for sodium, added sugar, saturated fat, trans fat and total "
        "fat a portion uses up, and how many portions it would take to reach each "
        "one. The limits are for an adult on a 2000 kcal diet. They come from WHO "
        "guidance and match the reference values FSSAI prints on Indian labels."
    )
    st.write(
        "This is not part of the 1 to 10 score. Daily limits only make sense for "
        "a portion, and only about half of the products have a serving size on "
        "record. The score already uses WHO's limits per 100 g for the product's "
        "category, and adding the daily limits as well would count the same "
        "sodium and sugar twice. It is also only arithmetic against published "
        "numbers. It doesn't say what a product does to anyone."
    )

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
- **No score if the nutrition panel is incomplete or doesn't add up.** That includes a biscuit or a sauce listed with 0 sodium, which is almost always a blank field. A guessed score is worse than none.
- **The scale describes the score, not the product.** Nothing is called harmful, unhealthy or toxic. The score comes from label data and published methods, and says nothing about whether a product is safe.
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
        "Product data is from Open Food Facts, an open database that anyone can "
        "edit. Some entries are wrong or incomplete, so the data is checked and "
        "repaired where possible. See the Data quality page, and the About page "
        "for what the score does and doesn't mean."
    )


def _refusal_group(reason: str) -> str:
    if "incomplete" in reason:
        return "A core number is missing from the nutrition panel"
    if "doesn't look right" in reason:
        return "The panel doesn't add up (for example 0 sodium in a biscuit)"
    return "A kind of product that isn't scored (supplement, spice, infant food...)"


def view_data_quality(scored: pd.DataFrame) -> None:
    st.title("Data quality")
    st.write(
        "This page is about the data itself: the product records pulled from "
        "Open Food Facts through its public API, what was wrong with them, and "
        "what was done about it. It isn't about the app's code. Crowd-sourced "
        "label data has mistakes, and a score built on a bad nutrition panel is "
        "worse than no score."
    )

    refused = scored[~scored.scoreable]
    st.subheader("Products with no score, and why")
    st.write(f"{len(refused):,} of {len(scored):,} products get no score. This is "
             "decided when a product is scored, so it is separate from the "
             "records dropped when the data was pulled.")
    groups = refused.refusal_reason.fillna("").map(_refusal_group).value_counts()
    st.dataframe(pd.DataFrame({"Reason": groups.index, "Products": groups.values}),
                 hide_index=True, use_container_width=True)

    st.subheader("When the data was pulled")
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
- **Sodium entered in milligrams where grams were expected.** Indian labels print sodium in mg and contributors copy the number. Table salt is 39 g of sodium per 100 g, so any value above 40 has to be mg. Dropping these records would have removed a lot of well-known Indian products.
- **Kilojoules entered as kilocalories.** Spotted when the stated energy is about 4.2 times what the fat, carbohydrate and protein add up to.
- **One impossible value**, like saturated fat above total fat. That one field is blanked and the product keeps its other numbers.
- **Fibre is left out of the "adds up to 100 g" check.** Labels disagree on whether carbohydrate already includes fibre, so counting it wrongly failed high-fibre products like atta and oats.

Some values can't be fixed, only refused. If a product that always contains salt (a biscuit, a sauce, noodles) lists sodium as 0, or lists no saturated fat despite over 10 g of total fat, or every value is 0, it gets no score. A blank entered as zero would otherwise count as the best possible result.
""")

    st.subheader("Known limits")
    st.markdown("""
- Open Food Facts isn't ground truth. One India record called "Organic Goat Feed" has an Indian biscuit's ingredient list.
- "Listed for India" isn't the same as "sold in India". Some records are labels from other countries that carry an India tag.
- The same product can be listed under different barcodes (around 250 repeated names in this data).
- Some products are filed in the wrong category because their source tags are wrong, for example a biscuit tagged as a fermented milk product.
- Only about a fifth of Open Food Facts' India products have both a full nutrition panel and a full ingredient list.
- Everything is per 100 g. A small packet and a large one score the same.
""")


def view_about() -> None:
    st.title("About and disclaimer")
    st.write(
        "This is a student project by Sahil Yadav. It takes the nutrition panel "
        "and ingredient list that people have entered on Open Food Facts for a "
        "product, and runs published nutrient-profiling methods on them. The "
        "score is the result of that calculation."
    )

    st.subheader("What a score is, and isn't")
    st.write(
        "A score is an automated calculation from label data. It is not medical "
        "or dietary advice, and it is not a safety, quality or hygiene rating. "
        "It does not say that any product is healthy, unhealthy, safe or unsafe, "
        "and it does not describe what a product does to any person. A low score "
        "only means the label data gives a low result under these methods. For "
        "advice about your own diet, ask a doctor or a registered dietitian."
    )

    st.subheader("The data can be wrong")
    st.write(
        "All product data comes from Open Food Facts, which anyone can edit. An "
        "entry can contain typing mistakes, be out of date, or describe an older "
        "version of the pack, and recipes change. Some entries are labels from "
        "other countries that carry an India tag. Each product page links to its "
        "source record and shows when it was last edited. Please check the pack "
        "in your hand before relying on any number here."
    )

    st.subheader("The method is a set of choices")
    st.write(
        "The score depends on choices made by the author: the weights, the caps "
        "and the edges between the 1 to 10 ratings, all listed on the How it "
        "works page. Other reasonable methods would give different numbers. The "
        "ratings are the author's analysis, produced by that published method, "
        "and are not statements of fact about any company or product."
    )

    st.subheader("Brands and trademarks")
    st.write(
        "Product and brand names appear only to identify the products being "
        "scored. They belong to their owners. This project is not affiliated "
        "with, endorsed by or sponsored by any brand, or by Open Food Facts, "
        "FSSAI, WHO or any other organisation mentioned. No logos or product "
        "images are used."
    )

    st.subheader("Corrections and removal")
    st.markdown(
        "If you own a brand, or you can see a mistake, please "
        f"[open an issue]({ISSUES_URL}) with the barcode and what is wrong. "
        "Wrong source data is best corrected on Open Food Facts itself, and it "
        "is picked up here when the dataset is rebuilt. If a record is wrong, or "
        "you would like a product taken out of this app, say so in the issue and "
        "it will be looked at."
    )

    st.subheader("No warranty")
    st.write(
        "This app is provided as it is, without any warranty. To the extent the "
        "law allows, the author is not responsible for decisions made using it."
    )

    st.subheader("Data licence")
    st.markdown(
        "Contains information from Open Food Facts, which is made available "
        "under the [Open Database License](https://opendatacommons.org/licenses/odbl/1-0/). "
        "The individual contents are under the "
        "[Database Contents License](https://opendatacommons.org/licenses/dbcl/1-0/). "
        "The cleaned dataset in this project's repository is a derivative of that "
        "data and is shared under the same licence."
    )

    st.subheader("Who made this")
    st.markdown(
        "Sahil Yadav · [GitHub](https://github.com/SahilYadav-op) · "
        "[LinkedIn](https://www.linkedin.com/in/sahilgod01/)"
    )


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #

df = load_products()

st.sidebar.title("India Food Health Index")
if df.empty:
    st.sidebar.error("No dataset found.")
else:
    st.sidebar.caption(f"{len(df):,} packaged products listed for India on Open "
                       "Food Facts.")
view = st.sidebar.radio("Pages", VIEWS, key="view", label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.caption(
    "Not medical advice. Scores are an automated calculation from label data "
    "that can be wrong, not a safety rating. See About."
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
elif view == "Check a label":
    view_check(scored)
elif view == "Browse":
    view_browse(scored)
elif view == "Highest and lowest":
    view_highest_lowest(scored)
elif view == "How it works":
    view_how()
elif view == "Data quality":
    view_data_quality(scored)
else:
    view_about()
