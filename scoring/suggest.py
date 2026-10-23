"""Suggest better-scoring products from the same category."""

from __future__ import annotations

import pandas as pd

from .categories import SALT_ALWAYS_PRESENT

CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}

# "general" is the catch-all bucket for products that matched no real category,
# so two products in it have nothing in common and shouldn't be offered as swaps.
NO_PEER_GROUP = {"general"}

# A suggestion shouldn't be worse than the original on the numbers people look at
# first. Without this, a biscuit with 29 g of sugar can be "better" than one with
# 13 g because it has less saturated fat, which is true but looks like a bug.
HEADLINE_NUTRIENTS = ("sugars", "saturated_fat", "sodium_mg")
TOLERANCE = 1.10

# In those categories a sodium value of 0 is a blank field, and such records look
# great on paper, so they are never suggested. (Scoring refuses them too.)


def better_alternatives(scored: pd.DataFrame, code: str, n: int = 5,
                        min_gain: int = 2) -> pd.DataFrame:
    """Products in the same category that score at least `min_gain` points higher
    and are no worse on sugar, saturated fat or sodium (within 10%).

    `scored` is the one-row-per-product table the app builds with score_product.
    Low-confidence scores are never suggested, unnamed records are skipped, and
    the same product listed under several barcodes only appears once.
    """
    empty = scored.iloc[0:0]
    match = scored[scored["code"] == code]
    if match.empty:
        return empty

    me = match.iloc[0]
    if not me["scoreable"] or pd.isna(me["score"]) or me["category"] in NO_PEER_GROUP:
        return empty

    pool = scored[
        (scored["category"] == me["category"])
        & scored["scoreable"]
        & (scored["code"] != code)
        & scored["product_name"].notna()
    ]
    # A record whose "name" is just its barcode can't be recommended to anyone.
    if "named" in pool.columns:
        pool = pool[pool["named"].astype(bool)]
    pool = pool[pool["score"] >= me["score"] + min_gain]
    pool = pool[pool["confidence"].map(CONFIDENCE_RANK).fillna(0) >= 1]

    for col in HEADLINE_NUTRIENTS:
        if col in scored.columns and pd.notna(me[col]):
            pool = pool[pool[col].notna() & (pool[col] <= me[col] * TOLERANCE)]
    if me["category"] in SALT_ALWAYS_PRESENT and "sodium_mg" in pool.columns:
        pool = pool[pool["sodium_mg"] > 0]
    if pool.empty:
        return empty

    pool = pool.assign(
        _conf=pool["confidence"].map(CONFIDENCE_RANK),
        _key=(pool["product_name"].astype(str).str.lower().str.strip()
              + "|" + pool["brands"].fillna("").astype(str).str.lower().str.strip()),
    )
    pool = pool.sort_values(["score", "_conf", "product_name"],
                            ascending=[False, False, True])
    pool = pool.drop_duplicates("_key")

    # Contributors often copy one panel onto several variants of a product. Those
    # rows say the same thing, so keep the first.
    panel = [c for c in ("brands", "score", *HEADLINE_NUTRIENTS) if c in pool.columns]
    pool = pool.drop_duplicates(panel)
    return pool.head(n).drop(columns=["_conf", "_key"])
