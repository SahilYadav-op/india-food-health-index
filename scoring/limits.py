"""Daily limits from WHO guidance and the reference values FSSAI prints on labels.

This is arithmetic, not a health claim. It answers "how much of the daily limit
does this portion use up?", using numbers anyone can look up. It does not say
what a product does to a person.

The limits are for an adult on a 2000 kcal diet, which is also the reference diet
on Indian labels. FSSAI's label reference values (Food Safety and Standards
Labelling and Display Regulations 2020) are 2000 kcal, 67 g fat, 22 g saturated
fat, 2 g trans fat, 50 g added sugar and 2000 mg sodium. They line up with WHO's
guidance, which is written as shares of energy: fat under 30%, saturated fat
under 10%, trans fat under 1% and free sugars under 10%, plus under 2 g of sodium
a day.
"""

from __future__ import annotations

from dataclasses import dataclass

DAILY_ENERGY_KCAL = 2000


@dataclass(frozen=True)
class DailyLimit:
    key: str
    label: str
    amount: float
    unit: str
    source: str


LIMITS = (
    DailyLimit("sodium_mg", "Sodium", 2000, "mg",
               "WHO: under 2 g of sodium (5 g of salt) a day. FSSAI uses 2000 mg on labels."),
    DailyLimit("added_sugars", "Added sugar", 50, "g",
               "WHO: free sugars under 10% of energy, which is 50 g on 2000 kcal "
               "(WHO suggests under 5%, 25 g, for extra benefit). FSSAI uses 50 g."),
    DailyLimit("saturated_fat", "Saturated fat", 22, "g",
               "WHO: under 10% of energy, 22 g on 2000 kcal. FSSAI uses 22 g."),
    DailyLimit("trans_fat", "Trans fat", 2, "g",
               "WHO: under 1% of energy, about 2 g on 2000 kcal. FSSAI uses 2 g."),
    DailyLimit("fat", "Total fat", 67, "g",
               "WHO: under 30% of energy, about 67 g on 2000 kcal. FSSAI uses 67 g."),
)


@dataclass
class Share:
    label: str
    in_portion: float
    unit: str
    percent: float
    portions_to_limit: float | None
    limit: float
    source: str
    note: str = ""


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _amount(row: dict, key: str) -> tuple[float | None, str, str]:
    """Per-100 g amount for a limit, plus the label and a note if it's a stand-in."""
    if key == "sodium_mg":
        sodium = _num(row.get("sodium"))
        return (sodium * 1000 if sodium is not None else None), "Sodium", ""
    if key == "added_sugars":
        added = _num(row.get("added_sugars"))
        if added is not None:
            return added, "Added sugar", ""
        total = _num(row.get("sugars"))
        if total is not None:
            return total, "Total sugars", (
                "Added sugar isn't declared, so this uses total sugars. That also "
                "counts sugar that is naturally in milk or fruit, so it can "
                "overstate the added sugar."
            )
        return None, "Added sugar", ""
    label = next(limit.label for limit in LIMITS if limit.key == key)
    return _num(row.get(key)), label, ""


def daily_shares(row: dict, portion_g: float) -> list[Share]:
    """How much of each daily limit `portion_g` of the product uses up.

    `row` holds per-100 g values, using the column names from the dataset.
    Nutrients with no value are left out rather than counted as zero.
    """
    if portion_g is None or portion_g <= 0:
        return []
    shares: list[Share] = []
    for limit in LIMITS:
        per_100, label, note = _amount(row, limit.key)
        if per_100 is None:
            continue
        amount = per_100 * portion_g / 100.0
        shares.append(Share(
            label=label,
            in_portion=amount,
            unit=limit.unit,
            percent=amount / limit.amount * 100.0,
            portions_to_limit=(limit.amount / amount) if amount > 0 else None,
            limit=limit.amount,
            source=limit.source,
            note=note,
        ))
    return shares


def serving_grams(text) -> float | None:
    """Grams (or ml) from a serving-size string such as '45g', '30 g' or
    '1 biscuit (10g)'. Returns None if there isn't a clear number."""
    import re

    if not isinstance(text, str):
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:g|gm|gms|gram|grams|ml)\b", text, re.IGNORECASE)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value if 0 < value <= 2000 else None
