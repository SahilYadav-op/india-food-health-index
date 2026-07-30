"""
Nutrient scoring: Nutri-Score 2023, the WHO SEARO screen, and FSSAI %RDA.

Three independent nutrient assessments, deliberately kept separate because they
answer different questions and because an examiner can check each one against its
own published source.

1. NUTRI-SCORE 2023 - the graded, validated core.
   The algorithm updated by the Nutri-Score Scientific Committee in 2022/2023.
   Chosen as the backbone because it is the only model in this family with
   published prospective validation against hard outcomes: EPIC (n=471,495) found
   HR 1.07 for total cancer comparing highest to lowest quintile of the
   FSAm-NPS dietary index, and EPIC mortality (n=501,594, 54,951 deaths) found
   all-cause HR 1.06. Three separate algorithms - general foods, beverages, and
   fats/oils/nuts/seeds - because one scale genuinely cannot span cooking oil and
   cola.

   Honest limitation to state in any write-up: a peer-reviewed critique argues
   Nutri-Score is "calibrated" rather than validated, and that a diet-level index
   validated against cohorts does not establish that a single product's grade
   predicts anything. This project uses it as the best-evidenced available
   ranking, not as a causal claim about any individual product.

2. WHO SEARO SCREEN - the non-compensatory, India-relevant check.
   The WHO nutrient profile model written for the South-East Asia Region and
   pilot-tested in India. Unlike a points model, it is pass/fail per nutrient
   against category-specific thresholds: exceed ANY one and the product may not
   be marketed to children. This is what stops a high-sodium product buying its
   way to a good grade with added protein and fibre, which is the single most
   cited criticism of star-rating systems - including of FSSAI's own INR.

3. FSSAI %RDA - the Indian regulatory reference.
   The reference values Indian labels themselves use, from the FSS (Labelling and
   Display) Regulations 2020: 2000 kcal, 67 g total fat, 22 g saturated fat, 2 g
   trans fat, 50 g added sugar, 2000 mg sodium. Used for consumer-facing
   "this pack is X% of your daily sodium" statements, not for the score.

WHY NOT FSSAI'S INDIAN NUTRITION RATING: INR would be the obvious India-native
choice, but as of early 2026 FSSAI has proposed to WITHDRAW the 2022 draft in an
affidavit to the Supreme Court, citing lack of stakeholder consensus. Its
thresholds were never derived from a health-outcomes study - the IIM-Ahmedabad
report it cites is a consumer-preference experiment comparing label formats, with
no nutrient thresholds in it - and its 21 g/100 g sugar reference is far more
permissive than the WHO free-sugars recommendation. Building this project's core
on a withdrawn, unvalidated draft would be indefensible. INR is implemented in
`compare.py` as a reference point, not as the backbone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Nutri-Score 2023 threshold arrays
# Source: Update of the Nutri-Score algorithm, Scientific Committee 2022,
#         pp. 129-134; beverages report Feb 2023, pp. 72-75.
# Semantics: award point i when value > T[i-1]. So points = number of thresholds
# strictly exceeded. Beverage energy and sugars are the exception - see below.
# --------------------------------------------------------------------------- #

A_ENERGY_KJ = [335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350]
A_SUGARS_G = [3.4, 6.8, 10, 14, 17, 20, 24, 27, 31, 34, 37, 41, 44, 48, 51]
A_SATFAT_G = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
A_SALT_G = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0,
            2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.4, 3.6, 3.8, 4.0]

C_PROTEIN_G = [2.4, 4.8, 7.2, 9.6, 12, 14, 17]
C_FIBRE_G = [3.0, 4.1, 5.2, 6.3, 7.4]
# Fruit/veg/legume points are non-contiguous: only 0, 1, 2 and 5 exist.
C_FVL_BANDS = [(80, 5), (60, 2), (40, 1)]

# Beverages. Energy and sugars use UPPER-BOUND semantics: point i if value <= UB[i].
BEV_ENERGY_KJ_UB = [30, 90, 150, 210, 240, 270, 300, 330, 360, 390]
BEV_SUGARS_G_UB = [0.5, 2, 3.5, 5, 6, 7, 8, 9, 10, 11]
BEV_PROTEIN_G = [1.2, 1.5, 1.8, 2.1, 2.4, 2.7, 3.0]
BEV_FVL_BANDS = [(80, 6), (60, 4), (40, 2)]
# The 2023 beverage algorithm adds a flat 4-point penalty for any non-nutritive
# sweetener - the mechanism that stops a diet drink outscoring water.
BEV_NNS_PENALTY = 4

# Fats, oils, nuts and seeds. Energy is replaced by energy FROM SATURATES, and
# absolute saturated fat by the saturates/total-lipids ratio.
KJ_PER_G_SATURATES = 37
FAT_EFS_KJ = [120, 240, 360, 480, 600, 720, 840, 960, 1080, 1200]
FAT_SAT_RATIO_PCT = [10, 16, 22, 28, 34, 40, 46, 52, 58, 64]

KCAL_TO_KJ = 4.184

# Non-nutritive sweetener codes, for the beverage penalty and the SEARO exclusion.
NNS_CODES = {
    "e950", "e951", "e952", "e954", "e955", "e957", "e959", "e960", "e961",
    "e962", "e969",
    # SEARO's definition explicitly includes caloric polyols.
    "e420", "e421", "e953", "e965", "e966", "e967", "e968",
}

GRADE_CUTS_GENERAL = [(0, "A"), (2, "B"), (10, "C"), (18, "D")]
GRADE_CUTS_FAT = [(-6, "A"), (2, "B"), (10, "C"), (18, "D")]
GRADE_CUTS_BEVERAGE = [(2, "B"), (6, "C"), (9, "D")]

# FSSAI %RDA denominators, FSS (Labelling and Display) Regulations 2020.
FSSAI_RDA = {
    "energy_kcal": 2000.0,
    "fat": 67.0,
    "saturated_fat": 22.0,
    "trans_fat": 2.0,
    "added_sugars": 50.0,
    "sodium_mg": 2000.0,
}


def num(value) -> float | None:
    """Coerce to a real float, mapping NaN and non-numerics to None.

    This is load-bearing, not defensive boilerplate. Parquet stores a missing
    float as NaN rather than None, and every comparison against NaN is False - so
    `nan > threshold` awards ZERO penalty points and `nan is None` is False, which
    means a product with no nutrition data at all silently scored as if it were
    perfectly clean AND did not register as incomplete. That combination graded
    empty records A. Coercing at the boundary is the fix.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN is the only value unequal to itself


def _points(value: float | None, thresholds: list[float]) -> int:
    """Number of thresholds strictly exceeded. None -> 0 points (best case).

    Treating a missing value as zero points is a deliberate, documented bias: it
    scores the product as if the nutrient were absent, which flatters it. The
    index compensates by carrying a data-completeness flag and refusing to
    publish a confident grade below tier 1.
    """
    if value is None:
        return 0
    return sum(1 for t in thresholds if value > t)


def _points_upper_bound(value: float | None, bounds: list[float]) -> int:
    """Beverage energy/sugars: the first band whose upper bound contains value."""
    if value is None:
        return 0
    for i, ub in enumerate(bounds):
        if value <= ub:
            return i
    return len(bounds)


def _band_points(value: float | None, bands: list[tuple[float, int]]) -> int:
    if value is None:
        return 0
    for threshold, pts in bands:
        if value > threshold:
            return pts
    return 0


def _grade(score: int, cuts: list[tuple[int, str]], last: str = "E") -> str:
    for limit, letter in cuts:
        if score <= limit:
            return letter
    return last


# --------------------------------------------------------------------------- #
# Nutri-Score
# --------------------------------------------------------------------------- #


@dataclass
class NutriScore:
    variant: str            # "general" | "beverage" | "fat" | "water"
    a_points: int
    c_points: int
    score: int
    grade: str
    breakdown: dict[str, int] = field(default_factory=dict)
    protein_capped: bool = False
    missing: list[str] = field(default_factory=list)

    @property
    def grade_index(self) -> int:
        """A=0 .. E=4, for sorting and colouring."""
        return "ABCDE".index(self.grade)


def nutri_score(row: dict, *, family: str, ecodes: list[str] | None = None,
                is_cheese: bool = False, is_red_meat: bool = False) -> NutriScore:
    """Compute the 2023 Nutri-Score for one product.

    `family` comes from `categories.CategorySpec.family`: "water", "beverage",
    "fat", "cheese", or "general".
    """
    ecodes = [c.lower() for c in (ecodes or [])]
    energy_kcal = num(row.get("energy_kcal"))
    energy_kj = energy_kcal * KCAL_TO_KJ if energy_kcal is not None else None
    sugars = num(row.get("sugars"))
    satfat = num(row.get("saturated_fat"))
    fat = num(row.get("fat"))
    salt = num(row.get("salt"))
    protein = num(row.get("proteins"))
    fibre = num(row.get("fiber"))
    fvl = num(row.get("fvl_estimate"))
    if fvl is None:
        fvl = num(row.get("fvnl_estimate"))

    missing = [k for k, v in (("energy", energy_kcal), ("sugars", sugars),
                              ("saturated fat", satfat), ("salt", salt),
                              ("protein", protein), ("fibre", fibre))
               if v is None]

    if family == "water":
        return NutriScore("water", 0, 0, 0, "A", {}, False, missing)

    if family == "beverage":
        p_energy = _points_upper_bound(energy_kj, BEV_ENERGY_KJ_UB)
        p_sugars = _points_upper_bound(sugars, BEV_SUGARS_G_UB)
        p_sat = _points(satfat, A_SATFAT_G)
        p_salt = _points(salt, A_SALT_G)
        p_nns = BEV_NNS_PENALTY if any(c in NNS_CODES for c in ecodes) else 0
        a = p_energy + p_sugars + p_sat + p_salt + p_nns

        p_protein = _points(protein, BEV_PROTEIN_G)
        p_fibre = _points(fibre, C_FIBRE_G)
        p_fvl = _band_points(fvl, BEV_FVL_BANDS)
        c = p_protein + p_fibre + p_fvl

        score = a - c  # beverages have no protein cap
        return NutriScore(
            "beverage", a, c, score, _grade(score, GRADE_CUTS_BEVERAGE),
            {"energy": p_energy, "sugars": p_sugars, "saturated fat": p_sat,
             "salt": p_salt, "sweeteners": p_nns, "protein": -p_protein,
             "fibre": -p_fibre, "fruit/veg/legumes": -p_fvl},
            False, missing,
        )

    if family == "fat":
        efs_kj = satfat * KJ_PER_G_SATURATES if satfat is not None else None
        ratio = (satfat / fat * 100) if (satfat is not None and fat) else None
        p_energy = _points(efs_kj, FAT_EFS_KJ)
        p_sat = _points(ratio, FAT_SAT_RATIO_PCT)
        p_sugars = _points(sugars, A_SUGARS_G)
        p_salt = _points(salt, A_SALT_G)
        a = p_energy + p_sugars + p_sat + p_salt

        p_protein = _points(protein, C_PROTEIN_G)
        p_fibre = _points(fibre, C_FIBRE_G)
        p_fvl = _band_points(fvl, C_FVL_BANDS)

        # Protein-cap trigger for this category is A >= 7, not 11.
        capped = a >= 7
        c = (p_fibre + p_fvl) if capped else (p_protein + p_fibre + p_fvl)
        score = a - c
        return NutriScore(
            "fat", a, c, score, _grade(score, GRADE_CUTS_FAT),
            {"energy from saturates": p_energy, "sugars": p_sugars,
             "saturates/fat ratio": p_sat, "salt": p_salt,
             "protein": 0 if capped else -p_protein,
             "fibre": -p_fibre, "fruit/veg/legumes": -p_fvl},
            capped, missing,
        )

    # General foods, including cheese and red meat.
    p_energy = _points(energy_kj, A_ENERGY_KJ)
    p_sugars = _points(sugars, A_SUGARS_G)
    p_sat = _points(satfat, A_SATFAT_G)
    p_salt = _points(salt, A_SALT_G)
    a = p_energy + p_sugars + p_sat + p_salt

    p_protein = _points(protein, C_PROTEIN_G)
    if is_red_meat:
        p_protein = min(p_protein, 2)
    p_fibre = _points(fibre, C_FIBRE_G)
    p_fvl = _band_points(fvl, C_FVL_BANDS)

    # The 2023 update removed the old "A>=11 unless fruit/veg = 5 points"
    # exemption. Only the cheese exemption survives.
    capped = a >= 11 and not is_cheese
    c = (p_fibre + p_fvl) if capped else (p_protein + p_fibre + p_fvl)
    score = a - c

    return NutriScore(
        "general", a, c, score, _grade(score, GRADE_CUTS_GENERAL),
        {"energy": p_energy, "sugars": p_sugars, "saturated fat": p_sat,
         "salt": p_salt, "protein": 0 if capped else -p_protein,
         "fibre": -p_fibre, "fruit/veg/legumes": -p_fvl},
        capped, missing,
    )


# --------------------------------------------------------------------------- #
# WHO SEARO screen
# Source: WHO Nutrient Profile Model for the South-East Asia Region.
# Thresholds per 100 g. `None` means the model sets no threshold for that
# nutrient in that category. Exceeding ANY threshold means the product may not be
# marketed to children.
# --------------------------------------------------------------------------- #


@dataclass
class SearoThresholds:
    total_fat: float | None = None
    saturated_fat: float | None = None
    total_sugars: float | None = None
    added_sugars: float | None = None
    sodium_g: float | None = None
    energy_kcal: float | None = None
    always_permitted: bool = False
    note: str = ""


# Keyed by this project's own category keys. Where SEARO has no matching row the
# category maps to None and the screen is skipped rather than guessed.
#
# One transcription caveat, recorded honestly: the source row for "fine bakery
# wares" carries an ambiguous extra figure, so this table uses the same total-fat
# threshold as ordinary bakery wares (8.0 g) plus the 230 kcal energy cap that row
# does specify. If exact fidelity to that single row matters for a published
# result, re-read the WHO PDF before quoting it.
SEARO: dict[str, SearoThresholds | None] = {
    "confectionery": SearoThresholds(total_fat=8.0, total_sugars=6.0,
                                     energy_kcal=230),
    "biscuits": SearoThresholds(total_fat=8.0, total_sugars=6.0, sodium_g=0.25,
                                energy_kcal=230,
                                note="fine bakery wares"),
    "bread_bakery": SearoThresholds(total_fat=8.0, total_sugars=6.0,
                                    sodium_g=0.25,
                                    note="bread and ordinary bakery wares"),
    "breakfast_cereal": SearoThresholds(total_fat=12.0, total_sugars=9.0,
                                        sodium_g=0.35),
    "staples": SearoThresholds(total_fat=12.0, total_sugars=9.0, sodium_g=0.35),
    "salty_snacks": SearoThresholds(total_fat=8.0, added_sugars=0.0,
                                    sodium_g=0.25, energy_kcal=230),
    "nuts_seeds": SearoThresholds(added_sugars=0.0, sodium_g=0.05,
                                  note="processed nuts"),
    "juice": SearoThresholds(total_sugars=6.0, added_sugars=0.0),
    "dairy_drink": SearoThresholds(total_fat=7.0, added_sugars=0.0),
    "beverage_sweetened": SearoThresholds(total_sugars=2.0, sodium_g=0.30),
    "beverage_unsweetened": SearoThresholds(total_sugars=2.0),
    "desserts_frozen": SearoThresholds(total_fat=8.0, total_sugars=12.0,
                                       sodium_g=0.10),
    "dairy_dessert": SearoThresholds(total_fat=7.0, total_sugars=6.0,
                                     sodium_g=0.10, energy_kcal=230),
    "dairy_fermented": SearoThresholds(total_fat=7.0, total_sugars=6.0,
                                       sodium_g=0.10, energy_kcal=230),
    "cheese": SearoThresholds(total_fat=20.0, added_sugars=0.0, sodium_g=0.60),
    "ready_meal": SearoThresholds(total_fat=8.0, saturated_fat=3.5,
                                  total_sugars=9.0, sodium_g=0.35),
    "fats_oils": SearoThresholds(saturated_fat=35.0, sodium_g=0.10),
    "noodles_pasta": SearoThresholds(total_fat=3.0, sodium_g=0.25),
    "meat_fish_eggs": SearoThresholds(total_fat=8.0, sodium_g=0.40,
                                      note="processed meat/fish"),
    "fruit_veg": SearoThresholds(added_sugars=0.0, sodium_g=0.40,
                                 note="processed fruits and vegetables"),
    "condiments": SearoThresholds(total_fat=12.0, total_sugars=10.0,
                                  sodium_g=0.30),
    "spreads": SearoThresholds(total_fat=12.0, total_sugars=10.0, sodium_g=0.30),
    "milk": None,
    "water": SearoThresholds(always_permitted=True),
    "general": None,
}

# SEARO's blanket exclusions (section 2.3). A product breaching any of these may
# not be marketed to children regardless of its nutrient thresholds.
SEARO_TRANS_FAT_ENERGY_PCT = 1.0   # >1% of total energy as industrial TFA
SEARO_TRANS_FAT_G_PER_SERVE = 0.5


@dataclass
class SearoResult:
    applicable: bool
    breaches: list[tuple[str, float, float]] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def passes(self) -> bool:
        return self.applicable and not self.breaches and not self.exclusions

    @property
    def breach_count(self) -> int:
        return len(self.breaches) + len(self.exclusions)


def searo_screen(row: dict, category_key: str,
                 ecodes: list[str] | None = None) -> SearoResult:
    """Apply the WHO SEARO pass/fail screen.

    Returns which specific thresholds are breached, so the app can say
    "too much sodium for this kind of food" rather than just showing a number.
    """
    thresholds = SEARO.get(category_key)
    if thresholds is None:
        return SearoResult(applicable=False,
                           note="WHO SEARO defines no thresholds for this "
                                "category, so this screen is not applied.")
    if thresholds.always_permitted:
        return SearoResult(applicable=True, note="Always permitted under WHO SEARO.")

    breaches: list[tuple[str, float, float]] = []
    for field_name, label in (("total_fat", "fat"),
                              ("saturated_fat", "saturated_fat"),
                              ("total_sugars", "sugars"),
                              ("added_sugars", "added_sugars"),
                              ("sodium_g", "sodium"),
                              ("energy_kcal", "energy_kcal")):
        limit = getattr(thresholds, field_name)
        value = num(row.get(label))
        if limit is not None and value is not None and value > limit:
            breaches.append((field_name, value, limit))

    exclusions: list[str] = []
    codes = {c.lower() for c in (ecodes or [])}
    if codes & NNS_CODES:
        exclusions.append(
            "Contains a non-sugar sweetener. WHO SEARO excludes any product with "
            "an added non-sugar sweetener from marketing to children, including "
            "sugar alcohols."
        )

    trans = num(row.get("trans_fat"))
    energy = num(row.get("energy_kcal"))
    if trans is not None and energy:
        trans_energy_pct = (trans * 9 / energy) * 100
        if trans_energy_pct > SEARO_TRANS_FAT_ENERGY_PCT:
            exclusions.append(
                f"Trans fat supplies {trans_energy_pct:.1f}% of this product's "
                f"energy, above the 1% ceiling."
            )

    return SearoResult(applicable=True, breaches=breaches, exclusions=exclusions,
                       note=thresholds.note)


# --------------------------------------------------------------------------- #
# FSSAI %RDA
# --------------------------------------------------------------------------- #


def rda_contribution(row: dict, serving_g: float | None = None) -> dict[str, float]:
    """Percentage of the FSSAI daily reference value, per 100 g or per serving.

    These are the same denominators printed on Indian labels, so a user can check
    the number against the pack.
    """
    basis = serving_g if serving_g and serving_g > 0 else 100.0
    scale = basis / 100.0
    out: dict[str, float] = {}

    for col, key in (("energy_kcal", "energy_kcal"), ("fat", "fat"),
                     ("saturated_fat", "saturated_fat"),
                     ("trans_fat", "trans_fat"),
                     ("added_sugars", "added_sugars")):
        value = num(row.get(col))
        if value is not None:
            out[col] = round(value * scale / FSSAI_RDA[key] * 100, 1)

    sodium = num(row.get("sodium"))
    if sodium is not None:
        out["sodium"] = round(sodium * 1000 * scale
                              / FSSAI_RDA["sodium_mg"] * 100, 1)
    return out
