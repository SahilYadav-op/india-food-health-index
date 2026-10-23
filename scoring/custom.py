"""Turn numbers typed in from a pack into a row the scoring code can use."""

from __future__ import annotations

import re

NUTRIENT_FIELDS = ("energy_kcal", "proteins", "carbohydrates", "sugars",
                   "added_sugars", "fat", "saturated_fat", "trans_fat", "fiber")


def parse_number(text) -> float | None:
    """A number from a text box. Blank means "not known", and stays None.

    Blank must not turn into 0: a zero scores as the best possible result, and
    that is the mistake the scoring code already refuses to make with bad records.
    Raises ValueError for anything that isn't a plain non-negative number.
    """
    if text is None:
        return None
    s = str(text).strip().replace(",", ".").lstrip("<~")
    if not s:
        return None
    if not re.fullmatch(r"\d+(?:\.\d+)?", s):
        raise ValueError(f"'{text}' isn't a number")
    return float(s)


def row_from_inputs(*, name: str | None, category_key: str, per_serving: bool,
                    serving_g: float | None, values: dict,
                    sodium_mg: float | None, salt_g: float | None,
                    ingredients: str | None) -> dict:
    """Build a per-100 g row from what was typed.

    If the numbers are per serving they are scaled up to 100 g using the serving
    size. Sodium can be given as sodium in mg or as salt in g (salt is 2.5 times
    sodium); if both are given, sodium wins.
    """
    if per_serving and not serving_g:
        raise ValueError("Enter the serving size to convert per-serving numbers.")
    scale = 100.0 / serving_g if per_serving else 1.0

    row: dict = {
        "code": "custom",
        "product_name": (name or "").strip() or None,
        "brands": None,
        "categories_tags": [],
        "category_override": category_key,
        "ingredients_text": (ingredients or "").strip() or None,
        "additives": [],
        "issues": [],
        "repairs": [],
    }
    for field in NUTRIENT_FIELDS:
        v = values.get(field)
        row[field] = None if v is None else v * scale

    if sodium_mg is not None:
        sodium_g = sodium_mg * scale / 1000.0
        salt = sodium_g * 2.5
    elif salt_g is not None:
        salt = salt_g * scale
        sodium_g = salt / 2.5
    else:
        sodium_g = salt = None
    row["sodium"], row["salt"] = sodium_g, salt
    return row


def input_warnings(row: dict) -> list[str]:
    """Plain-English warnings about numbers that don't add up."""
    out: list[str] = []
    g = row.get
    fat, sat = g("fat"), g("saturated_fat")
    carbs, sugars, added = g("carbohydrates"), g("sugars"), g("added_sugars")
    protein, fibre, energy = g("proteins"), g("fiber"), g("energy_kcal")

    if fat is not None and sat is not None and sat > fat + 0.5:
        out.append("Saturated fat is higher than total fat. Check the two numbers.")
    if carbs is not None and sugars is not None and sugars > carbs + 0.5:
        out.append("Sugars are higher than total carbohydrate. Check the two numbers.")
    if sugars is not None and added is not None and added > sugars + 0.5:
        out.append("Added sugar is higher than total sugars. Check the two numbers.")

    parts = [v for v in (fat, carbs, protein) if v is not None]
    salt = g("salt")
    if len(parts) == 3 and sum(parts) + (salt or 0) > 105:
        out.append("Fat, carbohydrate, protein and salt add up to more than 100 g "
                   "in 100 g. Check the numbers and whether they are per 100 g or "
                   "per serving.")

    if energy is not None and len(parts) == 3:
        computed = 9 * fat + 4 * carbs + 4 * protein + 2 * (fibre or 0)
        if computed > 0 and 3.8 <= energy / computed <= 4.6:
            out.append("The energy looks like kilojoules. This needs kilocalories (kcal).")
        elif energy > 13 and abs(computed - energy) > 0.3 * max(energy, computed) + 5:
            out.append("The energy doesn't match the fat, carbohydrate and protein. "
                       "Check the units.")
    return out
