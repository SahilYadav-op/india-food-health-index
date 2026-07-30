"""
Degree-of-processing assessment: NOVA group plus an ultra-processing marker count.

NOVA (Monteiro et al.) sorts food into four groups. Group 4, ultra-processed, is
defined by the PRESENCE OF MARKERS rather than by a nutrient profile, which is
what makes it computable from an ingredient list:

  Group 1  unprocessed or minimally processed - the edible parts of plants and
           animals, plus water. Drying, grinding, pasteurising, freezing and
           non-alcoholic fermentation are all permitted. No added culinary
           ingredients, no additives.
  Group 2  processed culinary ingredients - oils, salt, sugar, vinegar, starches,
           honey, syrups, butter. Things used to cook with, not eaten alone.
  Group 3  processed foods - Group 1 plus salt, sugar or oil, by baking, boiling,
           canning, bottling or fermenting. Cheese, breads, canned vegetables,
           salted nuts, fruit in syrup.
  Group 4  ultra-processed - industrial formulations where Group 1 foods are
           absent or a minor part, identified by two marker sets.

MARKER SET A - substances of no or rare culinary use. Things you would never find
in a home kitchen: high-fructose corn syrup, invert sugar, maltodextrin, dextrose,
fruit juice concentrate, hydrogenated and interesterified oils, modified starches,
protein isolates, hydrolysed proteins, mechanically separated meat.

MARKER SET B - cosmetic additives. Additives whose purpose is to make an
industrial formulation palatable or attractive: colours, flavours, flavour
enhancers, non-sugar sweeteners, emulsifiers, emulsifying salts, thickeners,
and anti-foaming, bulking, carbonating, foaming, gelling and glazing agents.

THE ASYMMETRY THAT MOST IMPLEMENTATIONS GET WRONG: preservatives, antioxidants
and acidity regulators are NOT cosmetic additives under NOVA and do not by
themselves make a food ultra-processed. Sodium benzoate in a pickle does not move
it to Group 4; a colour or an emulsifier does. Treating every additive as a
Group 4 trigger inflates the ultra-processed share and is a misreading of the
classification.

How hard the penalty should be: the BMJ 2024 umbrella review pooled 9.9 million
participants across 45 analyses, and only 4 reached "convincing" credibility with
GRADE certainty Low or Very Low for almost all of them. The one Moderate-certainty
cell is type 2 diabetes at RR 1.12 per 10-percentage-point increase in UPF share.
The dose-response estimates are far smaller than the high-versus-low headlines
(all-cause mortality 1.02 per increment against 1.21 high-vs-low), so this module
calibrates to the dose-response column. Causal support rests largely on Hall 2019,
a 20-person 14-day crossover trial. That is enough to justify a real penalty as a
dietary-pattern signal; it is not enough to claim an ingredient causes disease.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .additives import lookup
from .ingredients import ParsedLabel

# --------------------------------------------------------------------------- #
# marker set A - substances of no or rare culinary use
# --------------------------------------------------------------------------- #

# Matched on word boundaries against normalised ingredient names. Grouped so the
# app can explain WHICH kind of marker it found.
MARKER_SET_A: dict[str, tuple[str, ...]] = {
    "industrial sugar": (
        "high fructose corn syrup", "hfcs", "corn syrup", "glucose syrup",
        "liquid glucose", "invert sugar", "invert syrup", "glucose solids",
        "dextrose", "fructose", "maltodextrin", "malt extract",
        "fruit juice concentrate", "apple juice concentrate",
        "grape juice concentrate", "golden syrup", "treacle", "molasses",
        "caramel syrup", "date syrup", "maltose", "lactose",
    ),
    "modified fat": (
        "partially hydrogenated vegetable oil", "partially hydrogenated",
        "hydrogenated vegetable oil", "hydrogenated vegetable fat",
        "hydrogenated fat", "vanaspati", "bakery shortening", "bakery fat",
        "interesterified vegetable fat", "interesterified fat", "palm stearin",
        "cocoa butter substitute", "cocoa butter equivalent",
        "milk fat substitute", "vegetable fat", "edible vegetable fat",
    ),
    "modified starch": (
        "modified starch", "modified corn starch", "modified maize starch",
        "modified tapioca starch", "pregelatinised starch", "dextrin",
        "resistant starch", "acetylated starch",
    ),
    "protein isolate": (
        "soya protein isolate", "soy protein isolate", "soy protein concentrate",
        "whey protein isolate", "whey protein concentrate", "milk protein isolate",
        "casein", "caseinate", "sodium caseinate", "calcium caseinate",
        "wheat gluten", "vital gluten", "gluten", "pea protein isolate",
    ),
    "hydrolysed protein": (
        "hydrolysed vegetable protein", "hydrolyzed vegetable protein",
        "hydrolysed soy protein", "hydrolysed protein", "yeast extract",
        "soy protein hydrolysate", "textured vegetable protein",
    ),
    "mechanically separated meat": (
        "mechanically separated meat", "mechanically deboned meat",
        "meat slurry",
    ),
}

# --------------------------------------------------------------------------- #
# marker set B - cosmetic additive classes
# --------------------------------------------------------------------------- #

# NOVA cosmetic-additive functional classes. Deliberately EXCLUDES preservative,
# antioxidant and acidity regulator.
COSMETIC_CLASSES = {
    "colour", "flavour", "flavour enhancer", "sweetener", "emulsifier",
    "emulsifying salt", "thickener", "antifoaming agent", "bulking agent",
    "carbonating agent", "foaming agent", "gelling agent", "glazing agent",
    "modified starch", "humectant", "salt substitute",
}

# Ingredient-name signals for cosmetic additives declared by class name only,
# e.g. "added flavours (nature identical flavouring substances)" carries no INS
# number but is unambiguously a NOVA marker.
COSMETIC_NAME_SIGNALS = (
    "artificial flavour", "artificial flavor", "nature identical flavour",
    "nature identical flavor", "natural and artificial flavour",
    "flavouring substance", "flavoring substance", "added flavour",
    "added flavor", "artificial colour", "artificial color",
    "synthetic food colour", "permitted colour", "permitted food colour",
    "flavour enhancer", "flavor enhancer", "artificial sweetener",
)

# Group 2 culinary ingredients. Their presence moves a Group 1 food to Group 3,
# but never to Group 4.
GROUP2_INGREDIENTS = (
    "sugar", "jaggery", "gur", "honey", "salt", "iodised salt", "sea salt",
    "rock salt", "vinegar", "butter", "ghee", "cream", "vegetable oil",
    "sunflower oil", "mustard oil", "groundnut oil", "coconut oil", "olive oil",
    "sesame oil", "rice bran oil", "palm oil", "soyabean oil", "corn starch",
    "starch",
)


def _compile(words: tuple[str, ...]) -> list[tuple[re.Pattern, str]]:
    """Word-boundary patterns that tolerate a plural.

    Labels write "Added Flavours" and "Permitted Colours" far more often than the
    singular, and a strict trailing boundary silently missed every one of them.
    """
    return [(re.compile(rf"(?<![a-z]){re.escape(w)}(?:s|es)?(?![a-z])"), w)
            for w in words]


_A_PATTERNS = {k: _compile(v) for k, v in MARKER_SET_A.items()}
_COSMETIC_NAME_PATTERNS = _compile(COSMETIC_NAME_SIGNALS)
_GROUP2_PATTERNS = _compile(GROUP2_INGREDIENTS)


@dataclass
class Marker:
    kind: str      # "rare_culinary" | "cosmetic_additive"
    group: str     # marker sub-type, e.g. "industrial sugar"
    matched: str   # what was found on the label


@dataclass
class ProcessingAssessment:
    nova_group: int | None
    markers: list[Marker] = field(default_factory=list)
    upf_marker_count: int = 0
    processing_penalty_0_100: float = 0.0
    confident: bool = True
    reason: str = ""

    @property
    def rare_culinary(self) -> list[Marker]:
        return [m for m in self.markers if m.kind == "rare_culinary"]

    @property
    def cosmetic(self) -> list[Marker]:
        return [m for m in self.markers if m.kind == "cosmetic_additive"]

    @property
    def is_ultra_processed(self) -> bool:
        return self.nova_group == 4


def find_markers(label: ParsedLabel) -> list[Marker]:
    """Locate NOVA group-4 markers in a parsed ingredient list."""
    markers: list[Marker] = []
    seen: set[tuple[str, str]] = set()

    names = [n.name for n in label.flat if n.name]
    haystack = " | ".join(names)

    # Marker set A - by ingredient name.
    for group, patterns in _A_PATTERNS.items():
        for pattern, word in patterns:
            if pattern.search(haystack) and (group, word) not in seen:
                seen.add((group, word))
                markers.append(Marker("rare_culinary", group, word))

    # Marker set B - cosmetic additives, resolved through the additive register so
    # the NOVA asymmetry is respected: a preservative or antioxidant does not count.
    for node in label.flat:
        if not node.ecode:
            continue
        additive = lookup(node.ecode)
        if additive is None:
            continue
        if additive.nova_cosmetic and (additive.ecode, "") not in seen:
            seen.add((additive.ecode, ""))
            markers.append(Marker("cosmetic_additive", additive.functional_class,
                                  f"{additive.name} (INS {additive.ins})"))

    # Marker set B - cosmetic additives declared only as a class name.
    for pattern, word in _COSMETIC_NAME_PATTERNS:
        if pattern.search(haystack) and ("name", word) not in seen:
            seen.add(("name", word))
            markers.append(Marker("cosmetic_additive", "declared by class", word))

    # A function-class wrapper node is itself a marker when it wraps no resolvable
    # code, e.g. "Colours (permitted natural colours)".
    for node in label.flat:
        fn = (node.function or "").strip()
        if fn in COSMETIC_CLASSES and not node.ecode and ("fn", fn) not in seen:
            seen.add(("fn", fn))
            markers.append(Marker("cosmetic_additive", fn, f"{fn} (unspecified)"))

    return markers


def classify_nova(label: ParsedLabel, markers: list[Marker]) -> tuple[int | None, str]:
    """Assign a NOVA group from the ingredient list.

    Returns (group, reason). Group is None when the ingredient list is absent -
    guessing a NOVA group from a nutrient panel alone is not defensible, and
    saying so is better than inventing one.
    """
    if label.parse_failed or not label.ingredients:
        return None, "no usable ingredient list"

    if markers:
        kinds = {m.kind for m in markers}
        if "cosmetic_additive" in kinds and "rare_culinary" in kinds:
            why = "contains both cosmetic additives and substances of no culinary use"
        elif "cosmetic_additive" in kinds:
            why = "contains cosmetic additives (colour, flavour, sweetener, emulsifier or similar)"
        else:
            why = "contains substances of no or rare culinary use"
        return 4, why

    names = [n.name for n in label.flat if n.name]
    haystack = " | ".join(names)
    has_group2 = any(p.search(haystack) for p, _ in _GROUP2_PATTERNS)

    # A single-ingredient product with no additives is Group 1 unless that single
    # ingredient is itself a culinary ingredient, in which case it is Group 2.
    if len(label.ingredients) == 1:
        return (2, "a single processed culinary ingredient") if has_group2 else \
               (1, "a single unprocessed or minimally processed ingredient")

    if has_group2:
        return 3, "a processed food: whole foods plus salt, sugar or fat, no ultra-processing markers"
    return 1, "minimally processed ingredients only, with no additives"


def assess_processing(label: ParsedLabel) -> ProcessingAssessment:
    """Full processing assessment for one product."""
    if label.parse_failed or not label.ingredients:
        return ProcessingAssessment(
            nova_group=None, markers=[], upf_marker_count=0,
            processing_penalty_0_100=0.0, confident=False,
            reason="No ingredient list available, so the degree of processing "
                   "cannot be assessed. This does not mean the product is "
                   "unprocessed.",
        )

    markers = find_markers(label)
    group, reason = classify_nova(label, markers)
    count = len(markers)

    # Penalty curve. Group 4 membership carries a floor, because the epidemiology
    # is about UPF exposure rather than marker count; additional markers then add
    # progressively less. Calibrated so a typical Indian biscuit (2-4 markers)
    # lands mid-range and a heavily formulated drink saturates.
    if group == 4:
        penalty = 45.0 + 55.0 * (1.0 - 0.72 ** (count - 1)) if count else 45.0
    elif group == 3:
        penalty = 15.0
    elif group == 2:
        penalty = 8.0
    elif group == 1:
        penalty = 0.0
    else:
        penalty = 0.0

    return ProcessingAssessment(
        nova_group=group,
        markers=markers,
        upf_marker_count=count,
        processing_penalty_0_100=round(min(100.0, penalty), 1),
        confident=True,
        reason=reason,
    )
