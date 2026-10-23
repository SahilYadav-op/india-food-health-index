"""
Assign every product a scoring category.

Why this module exists: no nutrient profiling model works on one universal scale.
Cooking oil is ~900 kcal and ~100 g fat per 100 g and is not a snack; plain milk
and a cola are both liquids but not comparable; a spice powder is eaten a gram at
a time. Every credible model - Nutri-Score, the Health Star Rating, WHO SEARO -
splits food into categories before applying thresholds, and getting the split
wrong is the fastest way to produce an absurd score.

Two outputs matter downstream:

  category            which threshold table and which peer group to use
  scoreable           whether a health score is meaningful at all

`scoreable = False` is a deliberate refusal, not a failure. A whey protein isolate
at 80 g protein and 1 g sugar per 100 g scores near-perfect on every nutrient
model ever published, which is meaningless - it is a supplement, not a food.
Infant formula is regulated separately in India under the IMS Act and must never
carry a consumer health ranking. Salt, sugar and spice powders are eaten by the
gram, so a per-100 g verdict is misleading. In all these cases the app shows an
explanation instead of a number.

Assignment is a three-step cascade:

  1. Open Food Facts `categories_tags` matched against an ordered rule table.
     Most specific rules first, because OFF tags are hierarchical and a biscuit
     also carries `en:snacks` and `en:plant-based-foods`.
  2. Product name and brand keywords, including Hindi/transliterated terms
     (namkeen, atta, dalia, chivda) that OFF's English taxonomy misses.
  3. Nutrient signature as a last resort - a 100 g fat, 900 kcal product with no
     name and no tags is a cooking oil whatever the record says.

Measured on the 3,374-product India corpus, step 1 alone covers 73%; the cascade
is what handles the remaining 918 products with no category tag at all.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# the category set
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CategorySpec:
    key: str
    display: str
    scoreable: bool = True
    # Nutri-Score/HSR treat these families with separate algorithms.
    family: str = "general"
    note: str = ""


CATEGORIES: dict[str, CategorySpec] = {c.key: c for c in [
    # --- beverages -------------------------------------------------------- #
    CategorySpec("water", "Water", family="water"),
    CategorySpec("beverage_sweetened", "Sweetened drink", family="beverage"),
    CategorySpec("beverage_unsweetened", "Unsweetened drink", family="beverage"),
    CategorySpec("juice", "Fruit juice", family="beverage"),
    CategorySpec("dairy_drink", "Milk-based drink", family="beverage"),

    # --- dairy ------------------------------------------------------------ #
    CategorySpec("milk", "Milk"),
    CategorySpec("dairy_fermented", "Curd / yoghurt"),
    CategorySpec("cheese", "Cheese / paneer", family="cheese"),
    CategorySpec("dairy_dessert", "Dairy dessert"),

    # --- fats ------------------------------------------------------------- #
    CategorySpec("fats_oils", "Cooking oil / fat", family="fat",
                 note="Judged against other cooking fats, not against food in general."),
    CategorySpec("nuts_seeds", "Nuts & seeds", family="fat"),

    # --- snacks ----------------------------------------------------------- #
    CategorySpec("biscuits", "Biscuits & cookies"),
    CategorySpec("salty_snacks", "Chips & namkeen"),
    CategorySpec("confectionery", "Chocolate & sweets"),
    CategorySpec("desserts_frozen", "Ice cream & frozen dessert"),

    # --- staples and meals ------------------------------------------------ #
    CategorySpec("breakfast_cereal", "Breakfast cereal"),
    CategorySpec("noodles_pasta", "Noodles & pasta"),
    CategorySpec("bread_bakery", "Bread & bakery"),
    CategorySpec("staples", "Flour, rice & pulses"),
    CategorySpec("ready_meal", "Ready-to-eat meal"),
    CategorySpec("meat_fish_eggs", "Meat, fish & eggs"),
    CategorySpec("fruit_veg", "Fruit & vegetables"),
    CategorySpec("spreads", "Spreads & jams"),
    CategorySpec("condiments", "Sauces & condiments"),

    # --- not scoreable ---------------------------------------------------- #
    CategorySpec("cooking_ingredient", "Cooking ingredient", scoreable=False,
                 family="ingredient",
                 note="Used by the gram as an ingredient, so a per-100 g health "
                      "score would be misleading."),
    CategorySpec("spices", "Spices & masala", scoreable=False, family="ingredient",
                 note="Eaten in gram quantities; per-100 g figures do not reflect "
                      "what you actually consume."),
    CategorySpec("supplement", "Supplement", scoreable=False, family="excluded",
                 note="Supplements are formulated to hit nutrient targets, so any "
                      "nutrient-based score flatters them. Not comparable to food."),
    CategorySpec("infant_food", "Infant food", scoreable=False, family="excluded",
                 note="Infant nutrition is regulated separately in India under the "
                      "IMS Act, 1992. This app does not rank it."),
    CategorySpec("alcohol", "Alcoholic drink", scoreable=False, family="excluded",
                 note="Alcohol's health effect is driven by the ethanol, which no "
                      "nutrient panel captures."),
    CategorySpec("non_food", "Not food", scoreable=False, family="excluded",
                 note="Not a human food product."),
    CategorySpec("general", "Other packaged food"),
]}


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #

# (category, off tag substrings, name/brand keywords)
# Ordered: the FIRST match wins, so specific families precede general ones.
RULES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    # ---- hard exclusions first, they must never be overridden ------------ #
    ("non_food", (
        "pet-food", "cat-food", "dog-food", "animal-feed", "non-food-products",
        "cosmetics", "medicines",
    ), ("pet food", "dog food", "cat food", "cattle feed", "goat feed",
        "poultry feed", "shampoo", "detergent")),

    ("infant_food", (
        "infant", "baby-food", "baby-milk", "follow-on-milk", "first-infant-milk",
        "toddler",
    ), ("infant formula", "baby food", "cerelac", "lactogen", "nan pro", "dexolac",
        "farex", "baby cereal", "stage 1", "stage 2")),

    ("supplement", (
        "dietary-supplements", "bodybuilding-supplements", "food-supplements",
        "protein-powders", "meal-replacement", "vitamins", "mineral-supplements",
        "sports-nutrition", "gainers",
    ), ("whey protein", "protein powder", "protein isolate", "protein concentrate",
        "mass gainer", "weight gainer", "bcaa", "creatine", "pre workout",
        "pre-workout", "multivitamin", "capsule", "tablet", "softgel",
        "supplement", "amino acid", "glutamine", "electrolyte powder", "ors",
        "whey", "casein", "collagen", "gold standard", "isolate", "nutrition powder",
        "health drink powder", "meal replacement")),

    ("alcohol", (
        "alcoholic-beverages", "beers", "wines", "spirits", "whiskies", "rums",
        "vodkas", "liqueurs", "ciders",
    ), ("beer", "lager", "whisky", "whiskey", "vodka", "rum ", "brandy", "wine",
        "tequila", "gin ", "liqueur")),

    # ---- cooking ingredients -------------------------------------------- #
    ("spices", (
        "spices", "condiments-and-spices", "herbs-and-spices", "curry-powders",
        "masalas", "seasonings", "chilli-powders", "turmeric",
    ), ("masala", "garam masala", "chilli powder", "chilli pwd", "turmeric",
        "haldi", "jeera powder", "coriander powder", "dhania", "spice mix",
        "seasoning", "asafoetida", "hing", "kasuri methi", "black pepper powder")),

    ("cooking_ingredient", (
        "salts", "table-salt", "sugars", "granulated-sugar", "baking-powder",
        "baking-soda", "yeasts", "food-colouring", "essences", "vinegars",
        "gelling-agents", "starches", "food-additives",
    ), ("iodised salt", "iodized salt", "table salt", "rock salt", "sendha namak",
        "black salt", "kala namak", "baking powder", "baking soda", "cooking soda",
        "eno", "citric acid", "food colour", "vanilla essence", "yeast",
        "corn starch", "corn flour", "custard powder", "vinegar", "gelatin")),

    # ---- fats ------------------------------------------------------------ #
    ("fats_oils", (
        "fats", "vegetable-fats", "vegetable-oils", "olive-oils", "butters",
        "ghees", "margarines", "cooking-oils", "sunflower-oils", "mustard-oils",
        "coconut-oils", "groundnut-oils",
    ), ("refined oil", "sunflower oil", "mustard oil", "kachi ghani", "groundnut oil",
        "rice bran oil", "soyabean oil", "soybean oil", "olive oil", "coconut oil",
        "sesame oil", "til oil", "ghee", "vanaspati", "dalda", "margarine",
        "butter", "cooking oil", "blended oil", "palmolein")),

    ("nuts_seeds", (
        "nuts-and-their-products", "nuts", "almonds", "cashew",
        "peanut-butters", "nut-butters", "dried-fruits-and-nuts", "walnuts",
        "pistachios", "sunflower-seeds", "chia-seeds", "flax", "pumpkin-seeds",
    ), ("almond", "badam", "cashew", "kaju", "walnut", "akhrot", "pistachio",
        "pista", "peanut butter", "almond butter", "chia seed", "flax seed",
        "alsi", "pumpkin seed", "sunflower seed", "melon seed", "magaz",
        "mixed nuts", "trail mix", "makhana", "fox nut")),

    # ---- beverages ------------------------------------------------------- #
    # Plain water only. Open Food Facts tags colas as `en:carbonated-waters`, and
    # a naive "-waters" suffix match filed Thums Up, Pepsi and Mountain Dew as
    # water - which then scored them A on every model. The qualifier list below is
    # checked against the whole tag before the rule may fire.
    ("water", ("waters", "mineral-waters", "spring-waters", "drinking-water",
               "natural-mineral-waters", "still-waters"),
     ("mineral water", "packaged drinking water", "bisleri", "aquafina",
      "kinley", "drinking water")),

    ("juice", (
        "fruit-juices", "fruit-nectars", "vegetable-juices", "100-fruit-juices",
        "concentrated-fruit-juices", "juice", "juices",
    ), ("fruit juice", "100% juice", "real juice", "tropicana", "nectar",
        "orange juice", "apple juice", "mixed fruit juice")),

    ("beverage_sweetened", (
        "carbonated-drinks", "sodas", "colas", "energy-drinks", "sports-drinks",
        "sweetened-beverages", "fruit-drinks", "squashes", "syrups-for-beverages",
        "iced-teas", "lemonades", "non-alcoholic-beverages",
    ), ("cola", "pepsi", "coca cola", "coke", "thums up", "sprite", "fanta",
        "limca", "mirinda", "mountain dew", "7up", "soft drink", "soda",
        "energy drink", "red bull", "monster", "sting", "glucon", "rasna",
        "tang", "frooti", "maaza", "slice", "appy", "jumpin", "squash",
        "sharbat", "rooh afza", "iced tea", "lemonade", "nimbu pani")),

    ("dairy_drink", (
        "milk-drinks", "flavoured-milks", "chocolate-milks", "milk-shakes",
        "lassi", "buttermilks", "malted-milk-drinks", "dairy-drinks",
    ), ("flavoured milk", "flavored milk", "milk shake", "milkshake", "lassi",
        "buttermilk", "chaas", "chhach", "kefir", "bournvita", "horlicks",
        "complan", "boost", "pediasure", "milo")),

    ("beverage_unsweetened", (
        "teas", "coffees", "green-teas", "herbal-teas", "instant-coffees",
        "plant-based-beverages", "soy-milks", "almond-milks", "coconut-milks",
        "soy-drinks", "flavoured-waters", "flavored-waters", "sparkling-waters",
        "carbonated-waters",
    ), ("soy drink", "green tea", "black tea", "tea bag", "instant coffee", "filter coffee",
        "coffee powder", "soy milk", "soya milk", "almond milk", "oat milk",
        "coconut water", "nariyal pani")),

    # ---- dairy ----------------------------------------------------------- #
    ("cheese", ("cheeses", "processed-cheese", "paneer", "cottage-cheese",
                "cheese-spreads", "mozzarella"),
     ("cheese", "paneer", "cheddar", "mozzarella", "cheese slice",
      "cheese spread", "cream cheese")),

    ("dairy_fermented", (
        "fermented-milk-products", "yogurts", "curds", "greek-yogurts",
        "dahi", "probiotic-drinks",
    ), ("curd", "dahi", "yoghurt", "yogurt", "greek yogurt", "probiotic",
        "shrikhand", "misti doi", "mishti doi")),

    ("dairy_dessert", (
        "dairy-desserts", "puddings", "custards", "condensed-milks", "khoa",
        "milk-sweets", "indian-sweets",
    ), ("condensed milk", "milkmaid", "rasgulla", "gulab jamun", "rasmalai",
        "kheer", "payasam", "basundi", "peda", "barfi", "burfi", "mithai",
        "soan papdi", "kalakand", "milk cake", "laddu", "ladoo", "laddoo",
        "halwa", "jalebi", "mysore pak")),

    ("milk", ("milks", "milks-liquid-and-powder", "toned-milks", "whole-milks",
              "skimmed-milks", "milk-powders", "creams", "uht-milks"),
     ("toned milk", "double toned", "full cream milk", "cow milk", "buffalo milk",
      "milk powder", "skimmed milk powder", "dairy whitener", "fresh cream",
      "amul taaza", "amul gold", "amul slim")),

    # ---- snacks ---------------------------------------------------------- #
    ("biscuits", (
        "biscuits", "biscuits-and-cakes", "biscuits-and-crackers", "cookies",
        "crackers", "digestive-biscuits", "sandwich-biscuits", "rusks", "wafers",
    ), ("biscuit", "cookie", "parle-g", "parle g", "marie", "monaco", "krackjack",
        "good day", "bourbon", "hide & seek", "hide and seek", "oreo", "jim jam",
        "nutrichoice", "digestive", "cream biscuit", "rusk", "toast", "khari",
        "wafer", "milk bikis", "tiger", "little hearts", "50-50")),

    ("salty_snacks", (
        "salty-snacks", "chips-and-fries", "crisps", "potato-crisps", "appetizers",
        "extruded-snacks", "popcorn", "nachos", "namkeen", "savoury-snacks",
        "puffed-snacks", "papad",
    ), ("chips", "crisps", "wafers salted", "kurkure", "lays", "bingo", "uncle chipps",
        "namkeen", "bhujia", "sev", "mixture", "chivda", "chiwda", "farsan",
        "moong dal", "masala peanut", "aloo bhujia", "popcorn", "nachos",
        "puffs", "papad", "papadum", "fryums", "murukku", "chakli", "mathri",
        "khakhra", "banana chips", "tapioca chips", "gathiya", "ganthiya",
        "papdi", "khatta meetha",
        "navratan", "dal moth", "peanut masala", "salted peanut")),

    ("confectionery", (
        "confectioneries", "candies", "chocolates", "chocolate-bars", "toffees",
        "chewing-gum", "lollipops", "sugar-confectionery", "cocoa-and-its-products",
        "nougats", "marshmallows",
    ), ("chocolate", "dairy milk", "5 star", "munch", "kitkat", "kit kat",
        "perk", "gems", "eclairs", "toffee", "candy", "lollipop", "chewing gum",
        "centre fresh", "center fresh", "mentos", "polo", "alpenliebe",
        "melody", "coffee bite", "pulse candy", "chikki", "gajak", "jaggery candy")),

    ("desserts_frozen", (
        "ice-creams", "frozen-desserts", "ice-creams-and-sorbets", "kulfi",
        "frozen-yogurts",
    ), ("ice cream", "icecream", "kulfi", "frozen dessert", "cornetto",
        "cassata", "sorbet", "gelato", "choco bar")),

    # ---- staples and meals ---------------------------------------------- #
    ("breakfast_cereal", (
        "breakfast-cereals", "mueslis", "cereal-flakes", "corn-flakes", "granolas",
        "oat-flakes", "puffed-cereals", "porridges",
    ), ("weetabix", "chocapic", "corn flakes", "cornflakes", "muesli", "granola", "oats", "rolled oats",
        "instant oats", "dalia", "daliya", "porridge", "chocos", "poha",
        "upma mix", "breakfast cereal")),

    ("noodles_pasta", (
        "pastas", "noodles", "instant-noodles", "macaroni", "vermicelli",
        "spaghetti", "cup-noodles",
    ), ("noodles", "maggi", "yippee", "top ramen", "chowmein", "chow mein",
        "hakka", "pasta", "macaroni", "spaghetti", "penne", "vermicelli",
        "semiya", "seviyan")),

    ("bread_bakery", (
        "breads", "cakes", "pastries", "buns", "muffins", "croissants",
        "bakery-products", "sliced-breads", "pizza-crusts", "doughnuts",
    ), ("bread", "pav", "bun", "cake", "muffin", "pastry", "croissant",
        "doughnut", "donut", "pizza base", "burger bun", "brownie",
        "swiss roll", "cup cake")),

    ("staples", (
        "cereals-and-their-products", "flours", "wheat-flours", "rices",
        "legumes-and-their-products", "pulses", "lentils", "atta", "semolina",
        "gram-flours", "millets", "quinoa", "cereal-grains", "dals",
    ), ("atta", "maida", "chakki fresh", "whole wheat flour", "besan", "sooji",
        "suji", "rava", "semolina", "basmati", "rice ", "dal", "daal", "chana",
        "rajma", "moong", "masoor", "toor", "arhar", "urad", "millet", "ragi",
        "jowar", "bajra", "quinoa", "sabudana", "poha rice")),

    ("ready_meal", (
        "ready-made-meals", "prepared-meals", "canned-meals", "frozen-meals",
        "soups", "instant-mixes", "curries", "meal-kits", "frozen-foods",
        "combination-meals", "microwave-meals", "fresh-meals", "soup-powder",
        "instant-soups",
    ), ("ready to eat", "ready-to-eat", "instant mix", "dosa mix", "idli mix",
        "gulab jamun mix", "soup", "cup soup", "frozen paratha", "frozen roti",
        "samosa", "spring roll", "nuggets", "french fries", "biryani",
        "pulao", "dal makhani", "paneer butter masala", "poha mix", "upma")),

    ("meat_fish_eggs", (
        "meats", "meat-preparations", "poultry", "chicken", "fishes",
        "seafood", "eggs", "sausages", "canned-fishes", "processed-meats",
    ), ("chicken", "mutton", "fish", "prawn", "tuna", "sausage", "salami",
        "ham ", "bacon", "kebab", "seekh", "egg ", "meat")),

    ("fruit_veg", (
        "fruits-and-vegetables-based-foods", "canned-vegetables", "dried-fruits",
        "canned-fruits", "frozen-vegetables", "pickled-vegetables", "raisins",
        "dates", "olives", "sweet-corn",
    ), ("raisin", "kishmish", "dates", "khajur", "anjeer", "fig ", "prunes",
        "dried mango", "frozen peas", "sweet corn", "canned tomato",
        "tomato puree", "coconut desiccated")),

    ("spreads", (
        "spreads", "sweet-spreads", "jams", "marmalades", "honeys",
        "chocolate-spreads", "fruit-preserves", "plant-based-spreads",
    ), ("jam", "marmalade", "honey", "shahad", "nutella", "chocolate spread",
        "fruit spread", "mayonnaise", "mayo")),

    ("condiments", (
        "condiments", "sauces", "ketchup", "tomato-ketchups", "mustards",
        "salad-dressings", "pickles", "chutneys", "vinaigrettes", "soy-sauces",
        "mayonnaises",
    ), ("ketchup", "tomato sauce", "chilli sauce", "soy sauce", "sauce",
        "pickle", "achar", "chutney", "dressing", "mustard", "dip ")),
]

# Broad OFF tags that must never decide a category on their own - they sit at the
# top of the taxonomy and every Indian snack carries them.
GENERIC_TAGS = {
    "en:plant-based-foods-and-beverages", "en:plant-based-foods", "en:snacks",
    "en:sweet-snacks", "en:beverages", "en:beverages-and-beverages-preparations",
    "en:dairies", "en:cereals-and-potatoes", "en:groceries", "en:desserts",
    "en:breakfasts", "en:dried-products", "en:fermented-foods", "en:frozen-foods",
    "en:canned-foods", "en:meals", "en:fresh-foods", "en:food-preparations",
}


# --------------------------------------------------------------------------- #
# assignment
# --------------------------------------------------------------------------- #


def as_list(value) -> list[str]:
    """Coerce a tag field to a list of strings.

    Parquet round-trips list columns as numpy arrays, whose truthiness raises
    rather than returning False, so `value or []` is not safe here.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    try:
        return [str(v) for v in value if v is not None and str(v) != "nan"]
    except TypeError:
        return []


def _norm(text: str | None) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text)).lower()
    t = re.sub(r"[^a-z0-9%&\s-]", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


@dataclass
class CategoryResult:
    key: str
    display: str
    scoreable: bool
    family: str
    note: str
    method: str  # "tags" | "name" | "nutrients" | "fallback"
    matched_on: str = ""

    @property
    def spec(self) -> CategorySpec:
        return CATEGORIES[self.key]


def _result(key: str, method: str, matched_on: str = "") -> CategoryResult:
    spec = CATEGORIES[key]
    return CategoryResult(
        key=spec.key, display=spec.display, scoreable=spec.scoreable,
        family=spec.family, note=spec.note, method=method, matched_on=matched_on,
    )


# Prefixes that invert a tag's meaning. `en:non-alcoholic-beverages` must not
# match the `alcoholic-beverages` rule - that mis-filed every cola as alcohol.
NEGATING_PREFIXES = ("non-", "no-", "sans-", "free-", "without-")


def _tag_matches(leaf: str, part: str) -> bool:
    """True if `leaf` names `part` as a whole hyphen-delimited chunk, unnegated.

    So "fats" and "vegetable-fats" match the part "fats", but "low-fat-milk" and
    "non-alcoholic-beverages" do not match "fats"/"alcoholic-beverages".
    """
    if leaf == part:
        return True
    if leaf.endswith("-" + part):
        head = leaf[: -len(part) - 1]
        # Reject when the immediately preceding chunk negates.
        if any(head == p.rstrip("-") or head.endswith("-" + p.rstrip("-"))
               for p in NEGATING_PREFIXES):
            return False
        return True
    return leaf.startswith(part + "-")


# A tag naming water is only PLAIN water if none of these qualifiers appear in it.
# `en:carbonated-waters`, `en:flavoured-waters` and `en:tonic-waters` are drinks.
WATER_DISQUALIFIERS = ("carbonated", "flavoured", "flavored", "sweetened",
                       "tonic", "soda", "sparkling", "coconut", "vitamin",
                       "energy", "cola")

# Tags a rule must ignore even though they match its wording. The milk rule has
# the tag part "creams", and `en:ice-creams` ends in "-creams", so every ice cream
# in the data was being filed as milk.
TAG_DISQUALIFIERS = {
    "water": WATER_DISQUALIFIERS,
    "milk": ("ice-cream",),
}


# These win outright on a single tag: a supplement or an infant food must never
# be outvoted by however many snack tags a contributor also attached.
PRIORITY_KEYS = ("non_food", "infant_food", "supplement", "alcohol")


# Another category only overrides the first rule that matched when it has at least
# this many MORE supporting tags. Picked by testing against Open Food Facts' own
# Nutri-Score grades on 1,730 products: plain "most tags wins" scored 89.5%,
# first-match scored 90.8%, and margins of 3 and 4 both held 90.8% while still
# fixing the case below. A margin of 2 slipped to 90.6%.
OVERRIDE_MARGIN = 3

PLAIN_DAIRY = {"milk", "dairy_fermented", "cheese", "dairy_dessert"}
SNACK_KEYS = {"biscuits", "salty_snacks", "confectionery", "bread_bakery",
              "desserts_frozen"}

# Tags for these describe the raw ingredient (banana, pulses, flour), while the
# product is a snack made from it. When the product NAME contains a word that can
# only mean a snack, the name wins. The list is short on purpose: a first version
# reused the full keyword lists and filed a vegetable pickle as a biscuit (a brand
# contained "bourbon"), plain moong dal as a snack ("moong dal" is also a namkeen)
# and chocolate-flavoured oats as confectionery. Only the product name is checked,
# never the brand.
RAW_INGREDIENT_KEYS = {"fruit_veg", "staples"}
_SNACK_WORDS = (
    (re.compile(r"(?<![a-z])(chips|crisps|namkeen|bhujia|gathiya|ganthiya)(?![a-z])"),
     "salty_snacks"),
    (re.compile(r"(?<![a-z])(laddu|ladoo|laddoo|chikki)(?![a-z])"), "confectionery"),
)


def _snack_from_name(name: str) -> tuple[str, str] | None:
    for pattern, category in _SNACK_WORDS:
        m = pattern.search(name)
        if m:
            return category, m.group(1)
    return None


def _match_tags(tags: list[str]) -> tuple[str, str] | None:
    """Pick a category from Open Food Facts tags.

    Rules are ordered most specific first, and the first one that matches wins.
    The exception is a clear majority: Kurkure Masala Munch carries four tags for
    a salty snack (`salty-snacks`, `chips-and-fries`, `crisps`,
    `puffed-salty-snacks`) and one stray `biscuits-and-crackers`, and the stray
    tag used to win because the biscuit rule comes first.
    """
    useful = [t for t in tags if t not in GENERIC_TAGS]
    if not useful:
        return None

    hits: dict[str, tuple[int, int, str]] = {}  # key -> (tags matched, rule rank, first tag)
    for rank, (key, tag_parts, _) in enumerate(RULES):
        count, first_tag = 0, None
        for tag in useful:
            leaf = tag.split(":")[-1].lower().replace(" ", "-")
            if any(q in leaf for q in TAG_DISQUALIFIERS.get(key, ())):
                continue
            if any(_tag_matches(leaf, part) for part in tag_parts):
                count += 1
                first_tag = first_tag or tag
        if count:
            # A supplement or an infant food is never outvoted by snack tags.
            if key in PRIORITY_KEYS:
                return key, first_tag
            hits[key] = (count, rank, first_tag)

    if not hits:
        return None

    first_key = min(hits, key=lambda k: hits[k][1])
    leader = max(hits, key=lambda k: (hits[k][0], -hits[k][1]))
    if leader != first_key and hits[leader][0] >= hits[first_key][0] + OVERRIDE_MARGIN:
        return leader, hits[leader][2]

    # A plain dairy tag shouldn't win a tie against a snack tag. "Dairy Milk Silk
    # Minis" carries two chocolate tags and two milk tags, and the milk rule is
    # checked first, so a chocolate bar was filed as milk.
    if first_key in PLAIN_DAIRY:
        snack = [k for k in hits if k in SNACK_KEYS and hits[k][0] >= hits[first_key][0]]
        if snack:
            best = max(snack, key=lambda k: (hits[k][0], -hits[k][1]))
            return best, hits[best][2]
    return first_key, hits[first_key][2]


# Name keywords are matched on word boundaries, compiled once. Substring matching
# produced real errors: "atta" inside "khatta meetha" filed a namkeen as flour.
_NAME_PATTERNS: list[tuple[str, list[tuple[re.Pattern, str]]]] = [
    (key, [(re.compile(rf"(?<![a-z0-9]){re.escape(kw.strip())}(?![a-z0-9])"), kw.strip())
           for kw in keywords])
    for key, _, keywords in RULES
]


def _match_name(text: str) -> tuple[str, str] | None:
    for key, patterns in _NAME_PATTERNS:
        for pattern, kw in patterns:
            if pattern.search(text):
                return key, kw
    return None


def _match_nutrients(row: dict) -> tuple[str, str] | None:
    fat = row.get("fat")
    energy = row.get("energy_kcal")
    protein = row.get("proteins")
    carbs = row.get("carbohydrates")

    # Essentially pure fat.
    if fat is not None and fat >= 80 and (energy is None or energy >= 700):
        return "fats_oils", "fat>=80g/100g"
    # Protein-dominant powder: >50 g protein and little else is a supplement.
    if protein is not None and protein >= 50 and (carbs or 0) < 30:
        return "supplement", "protein>=50g/100g"
    # There used to be a rule here filing anything with ~0 energy as water. It put
    # a vitamin gummy with an empty panel at 10/10 "Excellent". A blank panel looks
    # exactly like water, so only a tag or a name may say something is water.
    return None


# Open Food Facts tags are crowd-edited and sometimes wrong in ways that matter
# more than usual. A soft drink filed as alcohol is the worst misclassification
# this app can make in India, so the product name gets a veto over the tag.
_ALCOHOL_VETO = re.compile(
    r"non[\s-]?alcoholic|alcohol[\s-]?free|zero[\s-]?alcohol|virgin\b|vinegar|"
    r"root beer|ginger beer|beer shampoo"
)


# Categories where a sodium value of exactly 0 almost always means the field was
# left blank, because a biscuit, a sauce or a bowl of noodles always has salt.
SALT_ALWAYS_PRESENT = {"biscuits", "salty_snacks", "bread_bakery", "noodles_pasta",
                       "cheese", "condiments", "ready_meal"}

_FLAVOURED_WATER = re.compile(
    r"flavou?r|lemon|lime|citron|orange|zero|sugar[\s-]?free|tonic|electrolyte|"
    r"vitamin|sports?\b"
)

# Water is defined physically, not by its tag: it carries no energy and no sugar.
# Some Indian records are tagged `en:waters` outright while being soft drinks -
# Mountain Dew was one - and being filed as water handed them a perfect score on
# every nutrient model. A nutrient test catches every such mis-tag without needing
# to enumerate brand names.
WATER_MAX_KCAL = 5.0
WATER_MAX_SUGARS = 0.5


def _veto(key: str, text: str, row: dict) -> str | None:
    """Return a corrected category when the evidence contradicts the tag."""
    if key == "alcohol" and _ALCOHOL_VETO.search(text):
        if "vinegar" in text:
            return "cooking_ingredient"
        return "beverage_sweetened"

    if key == "water":
        energy = _num(row.get("energy_kcal"))
        sugars = _num(row.get("sugars"))
        if (energy is not None and energy > WATER_MAX_KCAL) or \
           (sugars is not None and sugars > WATER_MAX_SUGARS):
            return "beverage_sweetened"
        # Zero-calorie but not plain: flavoured, sugar-free or sports drinks are
        # beverages under Nutri-Score 2023, not water.
        if _FLAVOURED_WATER.search(text):
            return "beverage_unsweetened"
    return None


def _num(value) -> float | None:
    """Coerce to a real float, mapping NaN to None (parquet stores gaps as NaN)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def classify(row: dict) -> CategoryResult:
    """Assign a scoring category to one product row.

    `row` needs: categories_tags, product_name, brands, and optionally the
    per-100 g nutrient columns. Missing keys are tolerated.

    A row can carry `category_override` (used when someone types a label in by
    hand and picks the category themselves). That choice is taken as given.
    """
    override = row.get("category_override")
    if override in CATEGORIES:
        return _result(override, "chosen by the user")

    tags = as_list(row.get("categories_tags"))
    text = " ".join(filter(None, [_norm(row.get("product_name")),
                                  _norm(row.get("brands")),
                                  _norm(row.get("quantity"))]))

    hit = _match_tags(tags)
    if hit:
        corrected = _veto(hit[0], text, row)
        if corrected:
            return _result(corrected, "tags+veto", f"{hit[1]} vetoed by name")
        if hit[0] in RAW_INGREDIENT_KEYS:
            snack = _snack_from_name(_norm(row.get("product_name")))
            if snack:
                return _result(snack[0], "name over tags",
                               f"{snack[1]} (tags said {hit[0]})")
        return _result(hit[0], "tags", hit[1])

    if text:
        hit = _match_name(text)
        if hit:
            corrected = _veto(hit[0], text, row)
            if corrected:
                return _result(corrected, "name+veto", f"{hit[1]} vetoed by name")
            return _result(hit[0], "name", hit[1])

    hit = _match_nutrients(row)
    if hit:
        return _result(hit[0], "nutrients", hit[1])

    # A generic tag is still better than nothing for the peer group.
    for tag in tags:
        if tag in ("en:beverages", "en:beverages-and-beverages-preparations"):
            return _result("beverage_unsweetened", "fallback", tag)
        if tag == "en:dairies":
            return _result("milk", "fallback", tag)

    return _result("general", "fallback")
