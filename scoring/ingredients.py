"""
Parse an Indian back-of-pack ingredient declaration into structured data.

Indian labels are their own dialect. A real Parle-style declaration looks like:

    Refined Wheat Flour (Maida) (63%), Sugar, Edible Vegetable Oil (Palm),
    Invert Syrup, Leavening Agents (INS 503(ii), INS 500(ii)), Salt,
    Emulsifiers (INS 322, INS 471), Dough Conditioner (INS 223).
    CONTAINS ADDED FLAVOURS (NATURAL AND NATURE IDENTICAL FLAVOURING SUBSTANCES).
    ALLERGEN INFORMATION: CONTAINS WHEAT AND MILK.

Three things make this hard:

1. Parentheses are overloaded. `(Maida)` is a gloss, `(63%)` is a quantity,
   `(Palm)` is a specification, `(INS 503(ii), INS 500(ii))` is a list of
   additives - and `(ii)` inside it is part of the additive code, not a nested
   ingredient. Naive paren-splitting mangles every INS number with a sub-part.

2. India uses INS numbers where the EU uses E numbers. INS 322 and E322 are the
   same substance (lecithin). Open Food Facts tags additives as `en:e322`, so we
   normalise everything to the E-number form to join against it.

3. Function words ("Emulsifiers", "Raising Agents", "Anticaking Agent") wrap the
   real ingredients. They are worth keeping as the parent's role rather than
   treating them as ingredients in their own right.

The parser is deliberately conservative: when it cannot confidently interpret a
token it keeps the raw text and flags it, rather than guessing. Downstream
scoring treats unparsed tokens as unknown, never as safe.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# lexicon
# --------------------------------------------------------------------------- #

# Words that introduce a class of additives rather than naming an ingredient.
FUNCTION_CLASSES = {
    "acidity regulator", "acidity regulators", "acid", "acids",
    "anticaking agent", "anticaking agents", "anti-caking agent", "anti caking agent",
    "antioxidant", "antioxidants",
    "bulking agent", "bulking agents",
    "colour", "colours", "color", "colors", "colouring", "coloring",
    "dough conditioner", "dough conditioners",
    "emulsifier", "emulsifiers",
    "emulsifying salt", "emulsifying salts",
    "firming agent", "firming agents",
    "flavour", "flavours", "flavor", "flavors",
    "flavour enhancer", "flavour enhancers", "flavor enhancer", "flavor enhancers",
    "flour treatment agent", "flour treatment agents",
    "gelling agent", "gelling agents",
    "glazing agent", "glazing agents",
    "humectant", "humectants",
    "improver", "improvers",
    "leavening agent", "leavening agents",
    "preservative", "preservatives",
    "raising agent", "raising agents",
    "sequestrant", "sequestrants",
    "stabiliser", "stabilisers", "stabilizer", "stabilizers",
    "sweetener", "sweeteners", "artificial sweetener", "artificial sweeteners",
    "thickener", "thickeners", "thickening agent", "thickening agents",
}

# Boilerplate sentences that are not part of the ingredient list. Removed before
# parsing so they do not become phantom ingredients. Any INS code inside them is
# harvested first - "Contains Permitted Natural Colour (INS 160c)" is boilerplate
# wording around a genuine additive declaration.
BOILERPLATE_PATTERNS = [
    r"contains\s+permitted\s+(?:natural|synthetic|class\s+[ivx]+)?\s*"
    r"(?:food\s+)?(?:colou?rs?|flavou?rs?|preservatives?)[^;]*",
    r"contains?\s+(?:added\s+)?(?:natural\s+(?:and\s+)?)?(?:nature[\s-]identical\s+)?"
    r"flavou?r(?:s|ing)?\b[^;]*",
    r"contains?\s+class\s+[ivx]+\s+preservatives?[^;]*",
    r"contains?\s+added\s+monosodium\s+glutamate[^;]*",
    r"not\s+recommended\s+for\s+(?:infants|children)[^;]*",
    r"may\s+contain[^;]*",
    r"manufactured\s+(?:in|on)\s+(?:a\s+)?(?:shared|the\s+same)[^;]*",
    r"best\s+before[^;]*",
    r"serving\s+suggestion[^;]*",
    r"\*?\s*approx(?:imate)?\s+values?[^;]*",
]

ALLERGEN_PATTERN = re.compile(
    r"(?:allergen\s+(?:information|advice|declaration)\s*:?\s*)?"
    r"contains\s*:?\s*((?:[A-Za-z][A-Za-z\s\-]*?)(?:\s*(?:,|and|&)\s*[A-Za-z][A-Za-z\s\-]*?)*)"
    r"\s*(?:\.|;|$)",
    re.IGNORECASE,
)

# Indian label synonym -> canonical name. Kept small and evidence-relevant:
# these are the aliases that change a product's score, not a full food thesaurus.
SYNONYMS = {
    "maida": "refined wheat flour",
    "refined wheat flour maida": "refined wheat flour",
    "wheat flour maida": "refined wheat flour",
    "atta": "whole wheat flour",
    "whole wheat flour atta": "whole wheat flour",
    "gehun ka atta": "whole wheat flour",
    "suji": "semolina",
    "sooji": "semolina",
    "rava": "semolina",
    "besan": "gram flour",
    "vanaspati": "partially hydrogenated vegetable oil",
    "bakery shortening": "hydrogenated vegetable fat",
    "edible vegetable fat": "vegetable fat",
    "edible vegetable oil": "vegetable oil",
    "edible veg fat": "vegetable fat",
    "edible veg oil": "vegetable oil",
    "palmolein": "palm oil",
    "palmolein oil": "palm oil",
    "rbd palmolein": "palm oil",
    "liquid glucose": "glucose syrup",
    "invert syrup": "invert sugar",
    "invert sugar syrup": "invert sugar",
    "hfcs": "high fructose corn syrup",
    "milk solids": "milk solids",
    "skimmed milk powder": "skimmed milk powder",
    "iodised salt": "salt",
    "iodized salt": "salt",
    "common salt": "salt",
    "namak": "salt",
    "cocoa solids": "cocoa solids",
    "chinni": "sugar",
    "shakkar": "sugar",
    "gur": "jaggery",
    "khand": "sugar",
}

# Additive codes. Both optional suffixes are load-bearing, and dropping either one
# silently names a different chemical:
#   roman    INS 500(ii) is sodium bicarbonate; INS 500(i) is sodium carbonate
#   letter   INS 472e is DATEM; bare INS 472 is a different ester family, and
#            INS 150d (sulphite ammonia caramel) is not INS 150a (plain caramel)
# The letter class must run to `f`, not `d` - 472e and 160f are both real and a
# `[a-d]` class silently truncated them.
# Sub-parts appear as roman numerals - INS 500(ii) - but a minority of real Indian
# labels print them as Arabic digits instead: "EMULSIFIERS [322(1) & 4711]".
# Accepting both, and normalising Arabic to roman, recovers codes that would
# otherwise be read as the wrong chemical or as garbage.
_ARABIC_TO_ROMAN = {"1": "i", "2": "ii", "3": "iii", "4": "iv", "5": "v"}

_ITEM = (
    r"(\d{3,4})\s*"
    r"(?:\(\s*([ivx]{1,4}|[1-5])\s*\)|(?<=\d)([ivx]{1,4})\b)?\s*"
    r"([a-f])?(?![a-z0-9])"
)

# A run of codes sharing one prefix: "RAISING AGENTS [INS 503(ii), 500(ii)]".
# Only the first code carries the INS, so scanning for prefixed codes alone finds
# 503(ii) and misses 500(ii) entirely. The lookbehind stops "Vitamin E 300" from
# being read as additive E300.
RUN_PATTERN = re.compile(
    rf"(?<!vitamin )\b(?:INS|E)\s*[-:]?\s*{_ITEM}"
    rf"(?:\s*(?:,|&|and)\s*{_ITEM})*",
    re.IGNORECASE,
)
ITEM_PATTERN = re.compile(_ITEM, re.IGNORECASE)

# After canonicalisation every code is a bracket-free token: INS500ii, INS472e.
CANON_PATTERN = re.compile(r"\bINS(\d{3,4})([ivx]*)([a-f]?)\b", re.IGNORECASE)

# A bare 3-4 digit number sitting alone inside an additive-class parenthesis,
# e.g. "Flavour Enhancers (627, 631)". Only trusted in that context.
BARE_CODE_PATTERN = re.compile(r"^\s*(\d{3,4})\s*([ivx]*)\s*([a-f])?\s*$", re.IGNORECASE)

# `] AND` / `) AND` joins two sibling ingredients: "FLOUR TREATMENT AGENTS
# [INS 1101(ii)] AND EMULSIFIER ... [INS 472e]". Splitting on a bare "and" would
# wreck "mono and diglycerides", so the split only fires straight after a closing
# bracket, which is where a group genuinely ends.
AND_AFTER_GROUP = re.compile(r"([\]\)\}])\s+(?:and|&)\s+", re.IGNORECASE)

# Additives written as names rather than INS numbers. Open Food Facts recognises
# these through its ingredient taxonomy; measured on this corpus, name-only
# additives account for roughly a third of all codes OFF finds, so a
# number-only parser silently under-reports additive load.
ADDITIVE_NAMES: dict[str, str] = {
    # acids and acidity regulators
    "citric acid": "e330", "sodium citrate": "e331", "tartaric acid": "e334",
    "malic acid": "e296", "lactic acid": "e270", "acetic acid": "e260",
    "phosphoric acid": "e338", "sodium phosphate": "e339",
    "tricalcium phosphate": "e341", "calcium phosphate": "e341",
    "sodium tripolyphosphate": "e451", "sodium polyphosphate": "e452",
    # raising agents
    "sodium bicarbonate": "e500ii", "baking soda": "e500ii",
    "sodium carbonate": "e500i", "ammonium bicarbonate": "e503ii",
    "sodium aluminium phosphate": "e541", "calcium carbonate": "e170",
    # emulsifiers and stabilisers
    "lecithin": "e322", "soy lecithin": "e322", "soya lecithin": "e322",
    "mono and diglycerides": "e471", "monoglycerides": "e471",
    "mono- and diglycerides": "e471",
    "mono and diglycerides of fatty acids": "e471",
    "datem": "e472e", "polysorbate": "e433", "polysorbate 80": "e433",
    "carboxymethylcellulose": "e466", "sodium carboxymethylcellulose": "e466",
    "sodium stearoyl lactylate": "e481", "polyglycerol polyricinoleate": "e476",
    # thickeners
    "xanthan gum": "e415", "guar gum": "e412", "locust bean gum": "e410",
    "carrageenan": "e407", "pectin": "e440", "acacia gum": "e414",
    "sodium alginate": "e401", "modified starch": "e1400",
    # antioxidants and preservatives
    "ascorbic acid": "e300", "vitamin c": "e300", "sodium ascorbate": "e301",
    "tocopherol": "e306", "tocopherols": "e306", "mixed tocopherols": "e306",
    "tbhq": "e319", "bha": "e320", "bht": "e321",
    "butylated hydroxyanisole": "e320", "butylated hydroxytoluene": "e321",
    "sodium benzoate": "e211", "benzoic acid": "e210",
    "potassium sorbate": "e202", "sorbic acid": "e200",
    "sodium metabisulphite": "e223", "sodium metabisulfite": "e223",
    "sulphur dioxide": "e220", "sulfur dioxide": "e220",
    "sodium nitrite": "e250", "sodium nitrate": "e251",
    # flavour enhancers
    "monosodium glutamate": "e621", "msg": "e621",
    "disodium inosinate": "e631", "disodium guanylate": "e627",
    "disodium ribonucleotides": "e635",
    # colours
    "tartrazine": "e102", "sunset yellow": "e110", "sunset yellow fcf": "e110",
    "carmoisine": "e122", "azorubine": "e122", "ponceau 4r": "e124",
    "erythrosine": "e127", "indigo carmine": "e132",
    "brilliant blue": "e133", "brilliant blue fcf": "e133",
    "fast green fcf": "e143", "allura red": "e129",
    "titanium dioxide": "e171", "caramel colour": "e150",
    "caramel color": "e150", "curcumin": "e100", "annatto": "e160b",
    "beta carotene": "e160a", "paprika extract": "e160c",
    "beetroot red": "e162", "carmine": "e120", "cochineal": "e120",
    # sweeteners
    "aspartame": "e951", "sucralose": "e955", "acesulfame potassium": "e950",
    "acesulfame k": "e950", "saccharin": "e954", "sodium saccharin": "e954",
    "steviol glycosides": "e960", "stevia": "e960", "neotame": "e961",
    "sorbitol": "e420", "maltitol": "e965", "xylitol": "e967",
    "erythritol": "e968", "isomalt": "e953", "mannitol": "e421",
    # anticaking, glazing, misc
    "silicon dioxide": "e551", "calcium silicate": "e552",
    "magnesium silicate": "e553", "shellac": "e904", "gelatin": "e441",
    "gelatine": "e441",
}

PERCENT_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")

# Placeholder used to hide INS sub-part parens from the paren splitter.
_SUB_OPEN, _SUB_CLOSE = "\x01", "\x02"


# --------------------------------------------------------------------------- #
# data model
# --------------------------------------------------------------------------- #


@dataclass
class Ingredient:
    """One node of the ingredient tree."""

    raw: str
    name: str
    percent: float | None = None
    ecode: str | None = None  # normalised additive code, e.g. "e500ii"
    function: str | None = None  # additive class of the PARENT, e.g. "raising agent"
    depth: int = 0
    rank: int = 0  # position among siblings, 1 = first
    children: list["Ingredient"] = field(default_factory=list)
    unparsed: bool = False

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class ParsedLabel:
    text: str
    ingredients: list[Ingredient]
    allergens: list[str] = field(default_factory=list)
    boilerplate: list[str] = field(default_factory=list)
    ecodes: list[str] = field(default_factory=list)
    parse_failed: bool = False

    @property
    def flat(self) -> list[Ingredient]:
        out: list[Ingredient] = []
        for top in self.ingredients:
            out.extend(top.walk())
        return out

    def names(self) -> list[str]:
        return [i.name for i in self.flat if i.name]

    def top_level_names(self) -> list[str]:
        return [i.name for i in self.ingredients if i.name]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def normalise_text(text: str) -> str:
    """Unicode-normalise, collapse whitespace, unify bullet/dash separators."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("’", "'").replace("，", ",")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def canonical_ecode(number: str, roman: str | None = None, letter: str | None = None) -> str:
    """`500`, `ii`, None -> `e500ii`. Matches Open Food Facts' additives_tags form."""
    code = f"e{int(number)}"
    if roman:
        code += re.sub(r"[^a-z]", "", roman.lower())
    if letter:
        code += letter.lower()
    return code


def canonicalise_codes(text: str) -> str:
    """Rewrite every INS/E run as bracket-free tokens: `INS 503(ii), 500(ii)`
    becomes `INS503ii, INS500ii`.

    Doing this before any bracket-aware splitting solves two problems at once. The
    `(ii)` can no longer be mistaken for a nested sub-ingredient, and the second
    code in a shared-prefix run recovers the `INS` it never had on the label.
    """

    def repl(m: re.Match) -> str:
        tokens = []
        for item in ITEM_PATTERN.finditer(m.group(0)):
            num, sub_paren, roman_bare, letter = item.groups()
            sub = (sub_paren or roman_bare or "").lower()
            roman = _ARABIC_TO_ROMAN.get(sub, sub)
            tokens.append(f"INS{int(num)}{roman}{(letter or '').lower()}")
        return ", ".join(tokens) if tokens else m.group(0)

    return RUN_PATTERN.sub(repl, text)


def split_top_level(text: str, separators: str = ",;") -> list[str]:
    """Split on separators that sit at parenthesis depth zero."""
    parts, buf, depth = [], [], 0
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch in separators and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


_OPENERS = "([{"
_CLOSERS = ")]}"


def _split_head_and_groups(token: str) -> tuple[str, list[str]]:
    """`Refined Wheat Flour (Maida) (63%)` -> (`Refined Wheat Flour`, [`Maida`, `63%`]).

    Square brackets count as grouping too: Indian seasoning blocks are routinely
    written `Seasoning [Spices (Onion), Salt, Acidity Regulator (330)]`.
    """
    head_chars, groups, depth, buf = [], [], 0, []
    for ch in token:
        if ch in _OPENERS:
            depth += 1
            if depth == 1:
                continue
        elif ch in _CLOSERS:
            depth -= 1
            if depth == 0:
                groups.append("".join(buf).strip())
                buf = []
                continue
            depth = max(0, depth)
        if depth == 0:
            head_chars.append(ch)
        else:
            buf.append(ch)
    if buf:  # unbalanced brackets - keep what we have
        groups.append("".join(buf).strip())
    return "".join(head_chars).strip(), [g for g in groups if g]


def clean_name(name: str) -> str:
    name = PERCENT_PATTERN.sub("", name)
    name = re.sub(r"^[\s\-*.•·:]+|[\s\-*.•·:]+$", "", name)
    name = re.sub(r"\s{2,}", " ", name)
    return name.strip().lower()


def apply_synonym(name: str) -> str:
    key = re.sub(r"[^a-z0-9\s]", " ", name)
    key = re.sub(r"\s{2,}", " ", key).strip()
    return SYNONYMS.get(key, name)


def _extract_percent(token: str) -> float | None:
    m = PERCENT_PATTERN.search(token)
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return value if 0 < value <= 100 else None


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #


def _parse_token(token: str, *, depth: int, rank: int, function: str | None) -> Ingredient | None:
    raw = token.strip()
    if not raw:
        return None

    head, groups = _split_head_and_groups(token)
    percent = _extract_percent(token)

    # Is the token itself an additive code? Codes have already been canonicalised
    # to the bracket-free `INS500ii` form by this point.
    ecode = None
    m = CANON_PATTERN.search(head or raw)
    if m:
        ecode = canonical_ecode(m.group(1), m.group(2), m.group(3))
    elif function:
        # Inside "Flavour Enhancers (627, 631)" a bare number is an INS code.
        bare = BARE_CODE_PATTERN.match(head or raw)
        if bare:
            ecode = canonical_ecode(bare.group(1), bare.group(2), bare.group(3))

    name = apply_synonym(clean_name(head or raw))
    node = Ingredient(
        raw=raw,
        name=name,
        percent=percent,
        ecode=ecode,
        function=function,
        depth=depth,
        rank=rank,
    )

    # Does this token introduce a class of additives? If so its children inherit
    # that role and are not themselves treated as standalone ingredients.
    child_function = function
    stripped = re.sub(r"[^a-z\s-]", "", name).strip()
    if stripped in FUNCTION_CLASSES:
        child_function = stripped.rstrip("s") if stripped.endswith("s") else stripped

    for group in groups:
        # A pure percentage group is a quantity, not a sub-ingredient.
        if PERCENT_PATTERN.fullmatch(group.strip()):
            continue
        for j, sub in enumerate(split_top_level(group), 1):
            child = _parse_token(sub, depth=depth + 1, rank=j, function=child_function)
            if child is None:
                continue
            # `Refined Wheat Flour (Maida)` collapses to the same canonical name
            # once the synonym is applied - keep the parent, drop the echo.
            if child.name == node.name and not child.ecode and not child.children:
                continue
            node.children.append(child)

    # An additive written as a name rather than a number - resolved only after the
    # children are known. "Caramel Colour (INS 150d)" must not also register the
    # generic `e150` from the parent's name, or the additive is counted twice.
    if not node.ecode and not any(c.ecode for c in node.children):
        node.ecode = ADDITIVE_NAMES.get(re.sub(r"\s{2,}", " ", node.name).strip())

    if not node.name and not node.ecode and not node.children:
        node.unparsed = True
    return node


def parse_ingredients(text: str | None) -> ParsedLabel:
    """Parse a raw ingredient declaration. Never raises - failure is a flag."""
    if not text or not str(text).strip():
        return ParsedLabel(text="", ingredients=[], parse_failed=True)

    original = normalise_text(str(text))

    # 1. A full stop ends a clause on these labels ("... INS 223. CONTAINS ..."),
    #    but must not split a decimal. Convert clause-ending stops to semicolons
    #    so the existing top-level splitter handles both.
    working = re.sub(r"(?<![0-9])\.(?![0-9])", ";", original)

    # 2. Pull out allergen statements before stripping boilerplate, since the
    #    "contains ..." wording overlaps.
    allergens: list[str] = []
    for m in ALLERGEN_PATTERN.finditer(working):
        body = m.group(1)
        # Skip additive-class boilerplate misread as an allergen list.
        if re.search(r"permitted|flavou?r|colou?r|preservat|monosodium", body, re.I):
            continue
        for a in re.split(r",|\band\b|&", body, flags=re.IGNORECASE):
            a = a.strip(" .;:").lower()
            if 2 < len(a) < 30:
                allergens.append(a)
    if allergens:
        working = ALLERGEN_PATTERN.sub(" ", working)

    # 3. Strip declarative boilerplate - but harvest any additive code out of it
    #    first. "Contains Permitted Natural Colour (INS 160c)" is boilerplate
    #    wrapping a real declaration, and dropping the E-number loses a genuine
    #    additive.
    boilerplate: list[str] = []
    rescued: list[str] = []
    for pattern in BOILERPLATE_PATTERNS:
        for m in re.finditer(pattern, working, re.IGNORECASE):
            chunk = m.group(0).strip()
            boilerplate.append(chunk)
            rescued.extend(extract_ecodes(chunk))
        working = re.sub(pattern, " ", working, flags=re.IGNORECASE)

    # 4. Drop a leading "Ingredients:" label.
    working = re.sub(r"^\s*ingredients?\s*[:\-]\s*", "", working, flags=re.IGNORECASE)
    working = normalise_text(working)

    # 5. Canonicalise additive runs, turn `] AND` into a separator, then split.
    working = canonicalise_codes(working)
    working = AND_AFTER_GROUP.sub(r"\1, ", working)
    tokens = split_top_level(working)

    ingredients: list[Ingredient] = []
    for i, token in enumerate(tokens, 1):
        node = _parse_token(token, depth=0, rank=i, function=None)
        if node and (node.name or node.ecode or node.children):
            ingredients.append(node)

    label = ParsedLabel(
        text=original,
        ingredients=ingredients,
        allergens=sorted(set(allergens)),
        boilerplate=boilerplate,
        parse_failed=not ingredients,
    )
    label.ecodes = sorted({n.ecode for n in label.flat if n.ecode} | set(rescued))
    return label


def extract_ecodes(text: str | None) -> list[str]:
    """Fast path: just the additive codes, for when the tree is not needed."""
    if not text:
        return []
    canon = canonicalise_codes(normalise_text(str(text)))
    found = {
        canonical_ecode(m.group(1), m.group(2), m.group(3))
        for m in CANON_PATTERN.finditer(canon)
    }
    return sorted(found)


def render_tree(label: ParsedLabel) -> str:
    """Human-readable dump, used in the app's parser-inspection view."""
    lines = []
    for node in label.flat:
        bits = ["  " * node.depth + f"- {node.name or node.raw}"]
        if node.percent is not None:
            bits.append(f"[{node.percent:g}%]")
        if node.ecode:
            bits.append(f"({node.ecode.upper()})")
        if node.function:
            bits.append(f"<{node.function}>")
        lines.append(" ".join(bits))
    return "\n".join(lines)
