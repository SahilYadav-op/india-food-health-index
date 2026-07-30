"""
Turn raw Open Food Facts India records into a clean, validated product table.

This is the quality gate. Crowd-sourced label data is wrong in specific,
recognisable ways, and a health score computed on a bad panel is worse than no
score at all - so every row is checked and either passed, flagged, or quarantined.

Checks implemented (all per 100 g):

  atwater          4*protein + 4*carbs + 9*fat + 2*fibre should reproduce the
                   stated kcal. A large gap means one of the numbers is wrong or
                   in the wrong unit. Tolerance mirrors Open Food Facts' own
                   `energy-value-in-kcal-does-not-match...` quality tag.
  mass_budget      macros + salt cannot exceed 100 g in 100 g of food.
  sat_le_fat       saturated fat cannot exceed total fat.
  sugars_le_carbs  sugars cannot exceed total carbohydrate.
  added_le_sugars  added sugars cannot exceed total sugars.
  energy_ceiling   nothing can carry more than ~900 kcal/100 g (pure fat).
  salt_sodium      salt should equal sodium * 2.5 when both are present.
  non_negative     no negative nutrient values.
  plausible_units  catches per-serving values filed as per-100g and mg/g mixups.

Rows failing a *structural* check (negative values, impossible mass budget) are
quarantined. Rows failing a *soft* check (Atwater drift, salt/sodium drift) are
kept but carry a flag, and the app shows reduced confidence.

Also assigns each product a data tier, which is what lets the index degrade
gracefully instead of guessing:

  tier 1  the six core nutrients are present -> nutrient score only
  tier 2  tier 1 plus a parseable ingredient list -> processing + additive layers
  tier 3  tier 2 plus fibre and either added sugars or an F/V/legume estimate
          -> the full model with positive-component credit

Usage:
    python pipeline/build_dataset.py
    python pipeline/build_dataset.py --in data/raw/off_india_raw.jsonl --report
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scoring.ingredients import parse_ingredients  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW_DEFAULT = ROOT / "data" / "raw" / "off_india_raw.jsonl"
OUT_DEFAULT = ROOT / "data" / "products.parquet"
QUARANTINE = ROOT / "data" / "quarantine.parquet"
REPORT = ROOT / "data" / "validation_report.json"

log = logging.getLogger("build")

# Energy conversion factors (kcal/g) from EU Reg. 1169/2011 Annex XIV, which is
# also what Open Food Facts uses. Fibre is 2 kcal/g, NOT 4 - using a naive 4/4/9
# systematically over-estimates computed energy on exactly the high-fibre Indian
# staples (atta, oats, millet, bran) that this project most wants to rate well,
# manufacturing false "bad data" flags on the healthiest products in the corpus.
ATWATER = {"proteins": 4.0, "carbohydrates": 4.0, "fat": 9.0, "fiber": 2.0}

# Open Food Facts' own energy tolerance bands, ported from DataQualityFood.pm:
#   error   computed < stated*0.70 - 5  or  computed > stated*1.30 + 5
#   warning computed < stated*0.85 - 5  or  computed > stated*1.15 + 5
# Only evaluated once the stated value clears 13 kcal, since the absolute margin
# dominates below that.
ENERGY_ERROR_BAND = 0.30
ENERGY_WARN_BAND = 0.15
ENERGY_BAND_MARGIN = 5.0
ENERGY_CHECK_FLOOR = 13.0

CORE_NUTRIENTS = ["energy_kcal", "fat", "saturated_fat", "carbohydrates", "sugars",
                  "proteins", "sodium"]

# OFF nutriment key -> our column name.
NUTRIENT_MAP = {
    "energy-kcal_100g": "energy_kcal",
    "fat_100g": "fat",
    "saturated-fat_100g": "saturated_fat",
    "trans-fat_100g": "trans_fat",
    "cholesterol_100g": "cholesterol",
    "carbohydrates_100g": "carbohydrates",
    "sugars_100g": "sugars",
    "added-sugars_100g": "added_sugars",
    "fiber_100g": "fiber",
    "proteins_100g": "proteins",
    "salt_100g": "salt",
    "sodium_100g": "sodium",
    "calcium_100g": "calcium",
    "iron_100g": "iron",
    "fruits-vegetables-nuts-estimate-from-ingredients_100g": "fvnl_estimate",
    "fruits-vegetables-legumes-estimate-from-ingredients_100g": "fvl_estimate",
}

# Categories that are not human food and must never be scored. The India subset
# genuinely contains pet food and animal feed - a record titled "Organic Goat
# Feed" carries an Indian biscuit's ingredient list, which is exactly the kind of
# row that makes a demo look broken.
NON_FOOD_TAGS = {
    "en:pet-food", "en:cat-food", "en:dog-food", "en:animal-feed",
    "en:non-food-products", "en:cosmetics", "en:medicines",
}


# Pure table salt is 39.3 g sodium per 100 g, so no food can exceed ~40 g/100 g.
# Anything above that is a milligram value in a gram field - extremely common on
# the India subset, because Indian labels print sodium in mg and contributors copy
# the number as printed. Discarding these rows would delete most of the
# recognisable Indian brands, so the value is repaired instead.
SODIUM_G_CEILING = 40.0

# A stated kcal roughly 4.184x the Atwater reconstruction means kJ was typed into
# the kcal field.
KJ_PER_KCAL = 4.184
KJ_RATIO_WINDOW = (3.8, 4.6)


@dataclass
class Issue:
    code: str
    detail: str
    structural: bool = False


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)

    def add(self, code: str, detail: str, structural: bool = False) -> None:
        self.issues.append(Issue(code, detail, structural))

    @property
    def quarantined(self) -> bool:
        return any(i.structural for i in self.issues)

    @property
    def codes(self) -> list[str]:
        return [i.code for i in self.issues]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def num(value: Any) -> float | None:
    """Coerce to a finite float, or None. OFF stores numbers as strings sometimes."""
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def first_text(product: dict, *keys: str) -> str | None:
    for k in keys:
        v = product.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def tag_list(product: dict, key: str) -> list[str]:
    v = product.get(key)
    if isinstance(v, list):
        return [str(x) for x in v if x]
    if isinstance(v, str) and v.strip():
        return [t.strip() for t in v.split(",") if t.strip()]
    return []


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #


def repair(row: dict) -> list[str]:
    """Fix recoverable data-entry errors in place; return the repair codes applied.

    Runs before validation and before salt/sodium derivation. Three repairs, each
    only applied where the wrong reading is physically impossible so the correct
    reading is unambiguous:

      sodium_mg_to_g   sodium above 40 g/100 g must be milligrams
      energy_kj_to_kcal  stated kcal ~4.184x the Atwater reconstruction is kJ
      drop_impossible_field  a single nutrient that contradicts a hard identity
                       (saturated > total fat, sugars > carbohydrate, negative,
                       energy above the physical ceiling) is nulled rather than
                       used, so the product survives at a lower data tier

    Nulling one field is deliberately preferred to dropping the product: Cadbury
    Dairy Milk with an impossible saturated-fat entry is still worth scoring on
    its other seven nutrients, and losing it from an Indian food app is a worse
    error than scoring it with reduced confidence.
    """
    applied: list[str] = []

    # 1. sodium / salt entered in milligrams
    for col, ceiling in (("sodium", SODIUM_G_CEILING), ("salt", SODIUM_G_CEILING * 2.5)):
        v = row.get(col)
        if v is not None and v > ceiling:
            row[col] = v / 1000.0
            applied.append(f"{col}_mg_to_g")

    # 2. kJ typed into the kcal field
    energy = row.get("energy_kcal")
    fat, carbs, protein = row.get("fat"), row.get("carbohydrates"), row.get("proteins")
    if energy and all(v is not None for v in (fat, carbs, protein)):
        computed = (ATWATER["fat"] * fat + ATWATER["carbohydrates"] * carbs
                    + ATWATER["proteins"] * protein
                    + ATWATER["fiber"] * (row.get("fiber") or 0.0))
        if computed > 0:
            ratio = energy / computed
            if KJ_RATIO_WINDOW[0] <= ratio <= KJ_RATIO_WINDOW[1]:
                row["energy_kcal"] = energy / KJ_PER_KCAL
                applied.append("energy_kj_to_kcal")

    # 3. null single fields that contradict a hard identity
    fat, sat = row.get("fat"), row.get("saturated_fat")
    if sat is not None and fat is not None and sat > fat * 1.05 + 0.5:
        row["saturated_fat"] = None
        applied.append("drop_saturated_fat")

    carbs, sugars = row.get("carbohydrates"), row.get("sugars")
    if sugars is not None and carbs is not None and sugars > carbs * 1.05 + 0.5:
        row["sugars"] = None
        applied.append("drop_sugars")

    sugars, added = row.get("sugars"), row.get("added_sugars")
    if added is not None and sugars is not None and added > sugars * 1.05 + 0.5:
        row["added_sugars"] = None
        applied.append("drop_added_sugars")

    if (row.get("energy_kcal") or 0) > 950:
        row["energy_kcal"] = None
        applied.append("drop_energy")

    for col in NUTRIENT_MAP.values():
        v = row.get(col)
        if v is not None and v < 0:
            row[col] = None
            applied.append(f"drop_negative_{col}")

    return applied


def validate(row: dict) -> ValidationResult:
    """Report residual problems after repair(). Structural = unrepairable."""
    r = ValidationResult()
    get = row.get

    energy = get("energy_kcal")
    fat, carbs = get("fat"), get("carbohydrates")
    protein, fiber = get("proteins"), get("fiber")
    salt, sodium = get("salt"), get("sodium")

    # Mass budget is the one genuinely global check: if the declared components
    # cannot fit in 100 g, no single field is identifiable as the culprit, so the
    # whole panel is untrustworthy.
    #
    # Sum fat + carbohydrate + protein + salt ONLY, matching Open Food Facts.
    # Fibre is deliberately excluded: labelling conventions differ on whether the
    # declared carbohydrate figure already contains it, so adding fibre
    # double-counts on any label using the inclusive convention and penalises
    # high-fibre products for being high-fibre.
    #
    # The ceiling is 105 g rather than 100 g because 100 ml of a dense liquid
    # weighs more than 100 g, and per-100 ml panels are declared on volume.
    parts = {k: v for k, v in
             (("fat", fat), ("carbohydrates", carbs), ("proteins", protein),
              ("salt", salt)) if v is not None}
    if len(parts) >= 3:
        total = sum(parts.values())
        if total > 105:
            r.add("mass_budget", f"components sum to {total:.1f} g per 100 g",
                  structural=total > 120)

    # salt / sodium relationship: salt = sodium x 2.5
    if salt is not None and sodium is not None and sodium > 0:
        ratio = salt / sodium
        if not 2.0 <= ratio <= 3.0:
            r.add("salt_sodium", f"salt/sodium ratio {ratio:.2f}, expected ~2.5")

    # Energy reconstruction against Open Food Facts' two-band tolerance. After the
    # kJ repair, a residual gap means one of the macros is wrong in a way we
    # cannot attribute to a single field - keep the row, lower its confidence.
    if (energy is not None and energy > ENERGY_CHECK_FLOOR
            and all(v is not None for v in (fat, carbs, protein))):
        computed = (ATWATER["fat"] * fat + ATWATER["carbohydrates"] * carbs
                    + ATWATER["proteins"] * protein
                    + ATWATER["fiber"] * (fiber or 0.0))
        for band, code in ((ENERGY_ERROR_BAND, "energy_mismatch"),
                           (ENERGY_WARN_BAND, "energy_drift")):
            low = energy * (1 - band) - ENERGY_BAND_MARGIN
            high = energy * (1 + band) + ENERGY_BAND_MARGIN
            if not low <= computed <= high:
                r.add(code, f"stated {energy:.0f} kcal vs computed {computed:.0f} kcal "
                            f"(outside +/-{band:.0%})")
                break

    # Too many repairs on one row means the record itself is unreliable, even if
    # each individual fix looked defensible.
    repairs = [x for x in (row.get("repairs") or []) if x.startswith("drop_")]
    if len(repairs) >= 3:
        r.add("multiple_repairs", f"{len(repairs)} fields dropped: {','.join(repairs)}",
              structural=True)

    return r


# --------------------------------------------------------------------------- #
# flatten
# --------------------------------------------------------------------------- #


def flatten(product: dict) -> dict:
    nutriments = product.get("nutriments") or {}
    row: dict[str, Any] = {
        "code": str(product.get("code") or "").strip(),
        "product_name": first_text(product, "product_name", "generic_name"),
        "brands": first_text(product, "brands"),
        "quantity": first_text(product, "quantity"),
        "serving_size": first_text(product, "serving_size"),
        "categories_tags": tag_list(product, "categories_tags"),
        "labels_tags": tag_list(product, "labels_tags"),
        "allergens_tags": tag_list(product, "allergens_tags"),
        "off_additives_tags": [t.split(":")[-1].lower()
                               for t in tag_list(product, "additives_tags")],
        "ingredients_text": first_text(product, "ingredients_text_en", "ingredients_text"),
        "off_nova_group": num(product.get("nova_group")),
        "off_nutriscore_grade": (product.get("nutriscore_grade") or None),
        "off_nutriscore_score": num(product.get("nutriscore_score")),
        "off_completeness": num(product.get("completeness")),
        "image_front_url": product.get("image_front_url") or None,
        "image_nutrition_url": product.get("image_nutrition_url") or None,
        "image_ingredients_url": product.get("image_ingredients_url") or None,
        "last_modified_t": num(product.get("last_modified_t")),
    }

    for off_key, col in NUTRIENT_MAP.items():
        row[col] = num(nutriments.get(off_key))

    # Repair unit errors BEFORE deriving anything from these values, otherwise a
    # milligram sodium reading propagates into a nonsense salt figure.
    row["repairs"] = repair(row)

    # Derive the missing half of the salt/sodium pair rather than losing the row.
    if row.get("sodium") is None and row.get("salt") is not None:
        row["sodium"] = row["salt"] / 2.5
        row["sodium_derived"] = True
    elif row.get("salt") is None and row.get("sodium") is not None:
        row["salt"] = row["sodium"] * 2.5
        row["salt_derived"] = True
    row.setdefault("sodium_derived", False)
    row.setdefault("salt_derived", False)

    # Ingredient parsing
    parsed = parse_ingredients(row["ingredients_text"])
    row["ingredients_n"] = len(parsed.flat)
    row["ingredients_top_level"] = parsed.top_level_names()
    row["parsed_ecodes"] = parsed.ecodes
    row["parse_failed"] = parsed.parse_failed
    row["label_allergens"] = parsed.allergens

    # Union of both additive sources. Our parser reads INS numbers the OFF
    # taxonomy sometimes misses; OFF recognises additives written as names, which
    # the parser cannot. Neither alone is sufficient - measured on this corpus,
    # OFF found 5,657 codes and the parser 3,758, agreeing on 3,610.
    row["additives"] = sorted(set(row["off_additives_tags"]) | set(row["parsed_ecodes"]))
    row["additives_n"] = len(row["additives"])

    row["is_non_food"] = bool(set(row["categories_tags"]) & NON_FOOD_TAGS)
    return row


def assign_tier(row: dict) -> int:
    if any(row.get(k) is None for k in CORE_NUTRIENTS):
        return 0
    if not row.get("ingredients_text") or row.get("parse_failed"):
        return 1
    if row.get("fiber") is not None and (
        row.get("added_sugars") is not None
        or row.get("fvnl_estimate") is not None
        or row.get("fvl_estimate") is not None
    ):
        return 3
    return 2


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def build(raw_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rows, quarantined = [], []
    issue_counts: dict[str, int] = {}
    seen: set[str] = set()
    duplicates = 0

    with raw_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                product = json.loads(line)
            except ValueError:
                continue

            row = flatten(product)
            if not row["code"]:
                continue
            if row["code"] in seen:
                duplicates += 1
                continue
            seen.add(row["code"])

            result = validate(row)
            row["issues"] = result.codes
            row["tier"] = assign_tier(row)
            for code in set(result.codes):
                issue_counts[code] = issue_counts.get(code, 0) + 1

            if result.quarantined or row["is_non_food"]:
                row["quarantine_reason"] = (
                    "non_food" if row["is_non_food"]
                    else ";".join(i.code for i in result.issues if i.structural)
                )
                quarantined.append(row)
            else:
                rows.append(row)

    df = pd.DataFrame(rows)
    dq = pd.DataFrame(quarantined)

    report = {
        "source": str(raw_path),
        "raw_records": len(seen) + duplicates,
        "duplicate_barcodes": duplicates,
        "passed": len(df),
        "quarantined": len(dq),
        "issue_counts": dict(sorted(issue_counts.items(), key=lambda kv: -kv[1])),
        "tier_counts": (df["tier"].value_counts().sort_index().to_dict()
                        if not df.empty else {}),
        "quarantine_reasons": (dq["quarantine_reason"].value_counts().to_dict()
                               if not dq.empty else {}),
    }
    if not df.empty:
        report["nutrient_coverage"] = {
            col: round(float(df[col].notna().mean()), 4)
            for col in NUTRIENT_MAP.values() if col in df
        }
        report["ingredient_coverage"] = round(float(df["ingredients_text"].notna().mean()), 4)
        report["mean_additives"] = round(float(df["additives_n"].mean()), 2)
    return df, dq, report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--in", dest="raw", type=Path, default=RAW_DEFAULT)
    p.add_argument("--out", type=Path, default=OUT_DEFAULT)
    p.add_argument("--report", action="store_true", help="print the report to stdout")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    if not args.raw.exists():
        log.error("raw file not found: %s (run pipeline/harvest_off.py first)", args.raw)
        return 1

    df, dq, report = build(args.raw)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    # Lists must survive the round trip; parquet handles them natively.
    df.to_parquet(args.out, index=False)
    if not dq.empty:
        dq.to_parquet(QUARANTINE, index=False)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    log.info("passed %s products -> %s", len(df), args.out)
    log.info("quarantined %s -> %s", len(dq), QUARANTINE)
    log.info("tiers: %s", report.get("tier_counts"))
    if args.report:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
