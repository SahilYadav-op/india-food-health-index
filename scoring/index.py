"""
The 1-10 India Food Health Index.

Four pillars, each computed in its own module against its own published source,
then combined - with hard caps that no amount of added protein can buy off.

  nutrient   50%   Nutri-Score 2023, rescaled so each published grade band
                   occupies exactly one fifth of the 0-100 scale
  processing 25%   NOVA group plus ultra-processing marker count
  additive   15%   the evidence-graded additive register
  regulatory 10%   the WHO SEARO pass/fail screen

WHY WEIGHTED AT ALL, AND WHY THESE WEIGHTS. The nutrient pillar dominates because
it is the only component with prospective validation against hard outcomes. The
processing pillar is second because the UPF evidence base, while observational, is
enormous and consistent - but its one Moderate-GRADE cell is RR 1.12 per 10-point
increase in UPF share, an order of magnitude weaker than the nutrient evidence, so
it does not lead. Additives come third: real regulatory concern, mostly limited
evidence. The regulatory pillar carries the smallest weight because its job is not
to contribute points but to trigger the caps below.

THE CAPS ARE THE POINT. Every star-rating system that has been criticised in India
- FSSAI's own withdrawn Indian Nutrition Rating included - shares one flaw: a
product can offset a serious excess with positive components and still show a
respectable score. A packet of namkeen with 1.2 g sodium per 100 g should not reach
8/10 because it also contains protein and fibre. So a breach of a WHO SEARO
threshold does not merely subtract points, it lowers the CEILING:

  1 SEARO threshold breached          ceiling 7   "not for children" under WHO
  2 breached                          ceiling 5
  3 or more breached                  ceiling 4
  a SEARO blanket exclusion           ceiling 3   trans fat over 1% of energy,
                                                  or an added non-sugar sweetener
  NOVA group 4 (ultra-processed)      ceiling 8   cannot be "excellent"
  a Southampton warning-label colour  ceiling 6   RCT-grade child behaviour signal
  Nutri-Score E                       ceiling 4   worst published grade

Caps compose by taking the lowest. They can only lower a score, never raise it.

WHICH NUMBERS HERE ARE NOT SOURCED. Every threshold in this project traces to a
published document, but four numbers in THIS file do not, and pretending otherwise
would be the easiest thing for a reviewer to catch:

  * the pillar weights 0.50 / 0.25 / 0.15 / 0.10
  * the 25-points-per-breach conversion of the SEARO screen into a 0-100 subscore
  * the composite-to-1-10 band edges in SCORE_BANDS
  * the cap ceilings (7 / 5 / 4 / 3 / 8 / 6 / 4)

WHO SEARO is a binary pass/fail model and publishes no severity scale, so ANY
conversion of it into a graded subscore requires an unsourced choice. The weights
are ordered by evidence strength, which is defensible, but the specific values are
a judgement. These must be declared as such and tested: the evaluation plan
includes an ablation that reports how the score distribution moves at weights of
0.40/0.30/0.20/0.10 and 0.60/0.20/0.10/0.10, and at 15 / 25 / 35 points per
breach. A model whose conclusions survive that is honest; one that does not was
never measuring what it claimed.

ON THE LANGUAGE AT THE BOTTOM OF THE SCALE. A 1/10 label reads "harmful as a
regular part of your diet" rather than "toxic" or "will destroy your health". This
is deliberate and it is not timidity. No single packaged food sold legally in India
is toxic at normal intake - every additive in these products sits inside a JECFA or
FSSAI limit - and the entire evidence base here is about dietary PATTERNS, not
single items. Claiming toxicity would be scientifically indefensible, would fail
the first question any examiner asks, and in India would risk falling foul of ASCI
advertising rules and the FSSAI prohibition on disease claims. The honest strong
statement is about habitual consumption, and it is available at the bottom of the
ladder.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .additives import AdditiveAssessment, additive_risk
from .categories import CategoryResult, as_list, classify
from .ingredients import ParsedLabel, parse_ingredients
from .nutrients import (NutriScore, SearoResult, nutri_score, num,
                        rda_contribution, searo_screen)
from .processing import ProcessingAssessment, assess_processing

# --------------------------------------------------------------------------- #
# weights and caps
# --------------------------------------------------------------------------- #

WEIGHTS = {
    "nutrient": 0.50,
    "processing": 0.25,
    "additive": 0.15,
    "regulatory": 0.10,
}

# Nutri-Score numeric score -> 0-100, anchored on the PUBLISHED grade boundaries so
# each grade occupies one fifth of the scale. Read as (score, subscore) and
# interpolate linearly between anchors.
NUTRIENT_ANCHORS: dict[str, list[tuple[float, float]]] = {
    # General foods: A <=0, B 1-2, C 3-10, D 11-18, E >=19.
    "general": [(-15, 100), (0, 80), (2, 60), (10, 40), (18, 20), (40, 0)],
    "cheese": [(-15, 100), (0, 80), (2, 60), (10, 40), (18, 20), (40, 0)],
    # Fats/oils/nuts/seeds: A <=-6, B -5..2, C 3-10, D 11-18, E >=19.
    "fat": [(-20, 100), (-6, 80), (2, 60), (10, 40), (18, 20), (40, 0)],
    # Beverages: only water can be A, so the ladder starts at B = 80.
    "beverage": [(-6, 80), (2, 60), (6, 40), (9, 20), (25, 0)],
    "water": [(0, 100)],
}

# composite 0-100 -> 1-10. Lower bound of each band.
SCORE_BANDS = [(92, 10), (84, 9), (75, 8), (66, 7), (57, 6),
               (48, 5), (38, 4), (28, 3), (16, 2), (0, 1)]

SOUTHAMPTON = {"e102", "e104", "e110", "e122", "e124", "e129"}

CAP_SEARO_1 = 7
CAP_SEARO_2 = 5
CAP_SEARO_3 = 4
CAP_SEARO_EXCLUSION = 3
CAP_NOVA4 = 8
CAP_SOUTHAMPTON = 6
CAP_NUTRISCORE_E = 4


# --------------------------------------------------------------------------- #
# the label ladder
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Band:
    score: int
    label: str
    meaning: str
    basis: str


LADDER: dict[int, Band] = {b.score: b for b in [
    Band(10, "Excellent",
         "Fits into daily eating with no reservations.",
         "Nutri-Score A on the 2023 algorithm, minimally processed (NOVA 1-2), no "
         "penalised additives, and inside every WHO SEARO threshold for its category."),
    Band(9, "Very good",
         "A genuinely good everyday choice.",
         "Nutri-Score A or high B, little or no processing, and no WHO SEARO breach."),
    Band(8, "Good",
         "Sound for regular eating; nothing here needs limiting.",
         "Nutri-Score B, no threshold breaches. Capped here if ultra-processed, "
         "because NOVA group 4 alone rules out the top two bands."),
    Band(7, "Reasonable",
         "Fine as part of a varied diet. Worth reading the panel.",
         "Nutri-Score B or C with no more than one WHO SEARO threshold breached. "
         "One breach caps a product here."),
    Band(6, "Okay in moderation",
         "No reason to avoid it, but it should not be a staple.",
         "Nutri-Score C, or an otherwise better product carrying a colour that the "
         "EU requires a child-behaviour warning on."),
    Band(5, "Average",
         "Middling. Portion size is doing most of the work here.",
         "Nutri-Score C or D, or two WHO SEARO thresholds breached."),
    Band(4, "Below average",
         "Better as an occasional item than a habit.",
         "Nutri-Score D or E, or three or more WHO SEARO thresholds breached."),
    Band(3, "Poor",
         "A treat food. Frequent eating is the problem, not one packet.",
         "Nutri-Score D or E with heavy processing, or a WHO SEARO blanket "
         "exclusion such as trans fat above 1% of energy."),
    Band(2, "Very poor",
         "Keep this rare rather than regular.",
         "Nutri-Score E, ultra-processed, and multiple thresholds breached."),
    Band(1, "Harmful as a regular habit",
         "Not toxic in one packet, but genuinely harmful as a routine part of your "
         "diet.",
         "Worst on every pillar at once: Nutri-Score E, ultra-processed with many "
         "markers, penalised additives, and several WHO SEARO breaches. The claim "
         "is about habitual intake - the evidence base is dietary patterns, not "
         "single items."),
]}


# --------------------------------------------------------------------------- #
# result types
# --------------------------------------------------------------------------- #


@dataclass
class Pillar:
    key: str
    name: str
    subscore_0_100: float | None
    weight: float
    detail: str = ""
    confident: bool = True

    @property
    def assessed(self) -> bool:
        return self.confident and self.subscore_0_100 is not None


@dataclass
class Cap:
    ceiling: int
    reason: str


@dataclass
class IndexResult:
    scoreable: bool
    score: int | None
    band: Band | None
    composite_0_100: float | None
    pillars: list[Pillar] = field(default_factory=list)
    caps_applied: list[Cap] = field(default_factory=list)
    binding_cap: Cap | None = None
    category: CategoryResult | None = None
    nutri: NutriScore | None = None
    searo: SearoResult | None = None
    processing: ProcessingAssessment | None = None
    additives: AdditiveAssessment | None = None
    label: ParsedLabel | None = None
    tier: int = 0
    confidence: str = "low"
    confidence_note: str = ""
    refusal_reason: str = ""
    rda: dict[str, float] = field(default_factory=dict)

    @property
    def uncapped_score(self) -> int | None:
        if self.composite_0_100 is None:
            return None
        return _band_for(self.composite_0_100)


def _band_for(composite: float) -> int:
    for lower, score in SCORE_BANDS:
        if composite >= lower:
            return score
    return 1


def _interpolate(score: float, anchors: list[tuple[float, float]]) -> float:
    """Piecewise-linear map from a Nutri-Score value onto 0-100."""
    if len(anchors) == 1:
        return anchors[0][1]
    if score <= anchors[0][0]:
        return anchors[0][1]
    if score >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= score <= x1:
            if x1 == x0:
                return y1
            t = (score - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return anchors[-1][1]


# --------------------------------------------------------------------------- #
# the index
# --------------------------------------------------------------------------- #

CORE_NUTRIENTS = ("energy_kcal", "fat", "saturated_fat", "carbohydrates",
                  "sugars", "proteins", "sodium")


def data_tier(row: dict, label: ParsedLabel) -> int:
    """0 = cannot score, 1 = nutrients only, 2 = + ingredients, 3 = + fibre and more."""
    if any(num(row.get(k)) is None for k in CORE_NUTRIENTS):
        return 0
    if label.parse_failed or not label.ingredients:
        return 1
    if num(row.get("fiber")) is not None and (
        num(row.get("added_sugars")) is not None
        or num(row.get("fvl_estimate")) is not None
        or num(row.get("fvnl_estimate")) is not None
    ):
        return 3
    return 2


def score_product(row: dict) -> IndexResult:
    """Compute the full 1-10 index for one product row.

    `row` uses the column names produced by pipeline/build_dataset.py.
    """
    category = classify(row)
    label = parse_ingredients(row.get("ingredients_text"))
    tier = data_tier(row, label)

    # Refuse rather than mislead.
    if not category.scoreable:
        return IndexResult(
            scoreable=False, score=None, band=None, composite_0_100=None,
            category=category, label=label, tier=tier,
            refusal_reason=category.note or
            "This kind of product cannot be meaningfully scored on a per-100 g "
            "health scale.",
        )

    if tier == 0:
        missing = [k for k in CORE_NUTRIENTS if num(row.get(k)) is None]
        return IndexResult(
            scoreable=False, score=None, band=None, composite_0_100=None,
            category=category, label=label, tier=0,
            refusal_reason="The nutrition panel for this product is incomplete - "
                           f"missing {', '.join(missing)}. Scoring it would mean "
                           "guessing, and a guessed health score is worse than "
                           "none.",
        )

    ecodes = sorted(set(as_list(row.get("additives"))) | set(label.ecodes))

    # --- pillars ---------------------------------------------------------- #
    nutri = nutri_score(row, family=category.family, ecodes=ecodes,
                        is_cheese=(category.key == "cheese"))
    nutrient_sub = _interpolate(nutri.score,
                                NUTRIENT_ANCHORS.get(category.family,
                                                     NUTRIENT_ANCHORS["general"]))

    proc = assess_processing(label)
    add = additive_risk(ecodes)
    searo = searo_screen(row, category.key, ecodes)

    # A pillar that cannot be assessed gets subscore None, NOT a default value.
    # Awarding 100 for "no ingredient list" handed a free 40 points to every
    # product with missing data - the exact opposite of what incomplete data
    # should do. Instead the weights are renormalised over the pillars that were
    # actually assessed, so a gap neither helps nor hurts the score; it only
    # lowers the reported confidence.
    have_ingredients = bool(label.ingredients) and not label.parse_failed
    processing_sub = (100.0 - proc.processing_penalty_0_100) if proc.confident else None
    additive_sub = (100.0 - add.risk_0_100) if have_ingredients else None

    if not searo.applicable:
        regulatory_sub = None
    elif searo.exclusions:
        regulatory_sub = 0.0
    else:
        regulatory_sub = max(0.0, 100.0 - 25.0 * len(searo.breaches))

    pillars = [
        Pillar("nutrient", "Nutrients", round(nutrient_sub, 1), WEIGHTS["nutrient"],
               f"Nutri-Score {nutri.grade} (score {nutri.score:+d}) on the 2023 "
               f"{nutri.variant} algorithm"),
        Pillar("processing", "Processing",
               round(processing_sub, 1) if processing_sub is not None else None,
               WEIGHTS["processing"],
               (f"NOVA group {proc.nova_group}, {proc.upf_marker_count} "
                f"ultra-processing marker(s)") if proc.confident
               else "no usable ingredient list, so the degree of processing could "
                    "not be assessed",
               confident=proc.confident),
        Pillar("additive", "Additives",
               round(additive_sub, 1) if additive_sub is not None else None,
               WEIGHTS["additive"],
               (f"{len(add.flagged)} of {len(add.known)} identified additives carry "
                f"a penalty") if add.known
               else ("no additives identified" if have_ingredients
                     else "no usable ingredient list, so additives could not be "
                          "assessed"),
               confident=have_ingredients),
        Pillar("regulatory", "WHO SEARO screen",
               round(regulatory_sub, 1) if regulatory_sub is not None else None,
               WEIGHTS["regulatory"],
               "passes every threshold for its category" if searo.passes
               else (f"{searo.breach_count} threshold(s) or exclusion(s) breached"
                     if searo.applicable
                     else "WHO SEARO defines no thresholds for this category"),
               confident=searo.applicable),
    ]

    assessed = [p for p in pillars if p.assessed]
    weight_total = sum(p.weight for p in assessed)
    composite = (sum(p.subscore_0_100 * p.weight for p in assessed) / weight_total
                 if weight_total else nutrient_sub)
    raw_score = _band_for(composite)

    # --- caps -------------------------------------------------------------- #
    caps: list[Cap] = []
    n_breach = len(searo.breaches)
    if searo.exclusions:
        caps.append(Cap(CAP_SEARO_EXCLUSION,
                        "Breaches a WHO SEARO blanket exclusion: "
                        + "; ".join(searo.exclusions)))
    if n_breach >= 3:
        caps.append(Cap(CAP_SEARO_3,
                        f"{n_breach} WHO SEARO thresholds exceeded for its category"))
    elif n_breach == 2:
        caps.append(Cap(CAP_SEARO_2,
                        "Two WHO SEARO thresholds exceeded for its category"))
    elif n_breach == 1:
        field_name, value, limit = searo.breaches[0]
        pretty = field_name.replace("_", " ").replace(" g", "")
        caps.append(Cap(CAP_SEARO_1,
                        f"Exceeds the WHO SEARO {pretty} threshold for its category "
                        f"({value:g} vs {limit:g}), so WHO would not permit it to be "
                        f"marketed to children"))
    if proc.nova_group == 4:
        caps.append(Cap(CAP_NOVA4,
                        "Ultra-processed (NOVA group 4), which rules out the top "
                        "two bands whatever the nutrient profile"))
    southampton = sorted(set(ecodes) & SOUTHAMPTON)
    if southampton:
        caps.append(Cap(CAP_SOUTHAMPTON,
                        "Contains "
                        + ", ".join(c.upper() for c in southampton)
                        + " - a colour the EU requires a child-behaviour warning on"))
    if nutri.grade == "E":
        caps.append(Cap(CAP_NUTRISCORE_E, "Nutri-Score E, the worst published grade"))

    final = raw_score
    binding: Cap | None = None
    for cap in caps:
        if cap.ceiling < final:
            final = cap.ceiling
            binding = cap
    if binding is not None:
        # Report the single lowest cap as the binding one.
        binding = min((c for c in caps if c.ceiling == final), key=lambda c: c.ceiling)

    # --- confidence -------------------------------------------------------- #
    issues = as_list(row.get("issues"))
    if tier >= 3 and not issues:
        confidence, note = "high", "Complete panel and a parseable ingredient list."
    elif tier >= 2:
        confidence, note = "medium", (
            "Ingredient list available but the panel is missing "
            + (", ".join(nutri.missing) if nutri.missing else "some optional fields")
            + "."
        )
    else:
        confidence, note = "low", (
            "Scored from the nutrition panel alone - no usable ingredient list, so "
            "processing and additives could not be assessed."
        )
    if issues:
        note += f" Data-quality flags on this record: {', '.join(issues)}."

    serving = num(row.get("serving_quantity"))
    return IndexResult(
        scoreable=True, score=final, band=LADDER[final],
        composite_0_100=round(composite, 1), pillars=pillars,
        caps_applied=caps, binding_cap=binding, category=category, nutri=nutri,
        searo=searo, processing=proc, additives=add, label=label, tier=tier,
        confidence=confidence, confidence_note=note,
        rda=rda_contribution(row, serving),
    )
