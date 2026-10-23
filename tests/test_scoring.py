"""
Regression tests for the India Food Health Index.

Most of these exist because the bug they check for actually happened during
development and was found by running against real data. The comment on each says
what went wrong, so a future change that reintroduces it fails loudly.

Run:
    python -m pytest tests/ -q
    python tests/test_scoring.py     # works without pytest installed
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scoring.additives import additive_risk, lookup
from scoring.categories import classify
from scoring.index import score_product
from scoring.ingredients import extract_ecodes, parse_ingredients
from scoring.nutrients import num, nutri_score, searo_screen
from scoring.processing import assess_processing

# The real Open Food Facts record for barcode 8901719134845, used as the primary
# parser fixture. Values transcribed from the live API, not invented.
PARLE_G_INGREDIENTS = (
    "REFINED WHEAT FLOUR (MAIDA) 68%, SUGAR, REFINED PALM OIL, "
    "INVERT SUGAR SYRUP (SUGAR, CITRIC ACID), IODISED SALT, "
    "RAISING AGENTS [INS 503(ii), 500(ii)], MILK SOLIDS, "
    "FLOUR TREATMENT AGENTS [INS 1101(ii)] AND EMULSIFIER OF VEGETABLE ORIGIN "
    "[INS 472e]"
)
PARLE_G_ROW = {
    "code": "8901719134845", "product_name": "Parle-G Biscuit", "brands": "Parle",
    "categories_tags": ["en:biscuits"], "ingredients_text": PARLE_G_INGREDIENTS,
    "energy_kcal": 454.0, "fat": 13.0, "saturated_fat": 6.0,
    "carbohydrates": 77.3, "sugars": 25.5, "added_sugars": 21.31, "fiber": None,
    "proteins": 6.9, "salt": 0.74, "sodium": 0.296, "trans_fat": None,
    "additives": [], "issues": [], "repairs": [],
}


# --------------------------------------------------------------------------- #
# ingredient parsing
# --------------------------------------------------------------------------- #


def test_shared_prefix_ins_run():
    """`[INS 503(ii), 500(ii)]` - only the first code carries the INS prefix.

    Scanning for prefixed codes alone found 503(ii) and read the second as bare
    `500`, dropping the (ii). INS 500(ii) is sodium bicarbonate; INS 500 is
    sodium carbonate. Different chemical, silently.
    """
    codes = set(parse_ingredients(PARLE_G_INGREDIENTS).ecodes)
    assert "e500ii" in codes, codes
    assert "e503ii" in codes, codes


def test_letter_suffix_survives():
    """INS 472e is DATEM. A `[a-d]` letter class truncated it to e472."""
    assert "e472e" in extract_ecodes("EMULSIFIER [INS 472e]")
    assert "e150d" in extract_ecodes("Caramel Colour (INS 150d)")
    assert "e160f" in extract_ecodes("Colour (INS 160f)")


def test_and_after_bracket_splits_ingredients():
    """`] AND` joins two siblings; a bare "and" must NOT split."""
    label = parse_ingredients(PARLE_G_INGREDIENTS)
    tops = label.top_level_names()
    assert "flour treatment agents" in tops, tops
    assert any("emulsifier" in t for t in tops), tops
    # "mono and diglycerides" is one ingredient, not two.
    mono = parse_ingredients("Palm Oil, Mono and Diglycerides, Salt.")
    assert "mono and diglycerides" in mono.top_level_names()


def test_vitamin_e_is_not_additive_e300():
    """"Vitamin E 300 mg" was being read as additive E300 (ascorbic acid)."""
    codes = extract_ecodes("Whole Wheat Flour, Vitamin E 300 mg, Antioxidant (INS 319).")
    assert "e300" not in codes, codes
    assert "e319" in codes


def test_bracket_groups_and_bare_codes():
    """Square and curly brackets group; a bare number inside an additive class
    is an INS code, but only in that context."""
    text = ("Potato, Oil, Seasoning [Spices (Onion), Salt, "
            "Flavour Enhancers (627, 631), Acidity Regulator (330)], "
            "Anticaking Agents {INS 341 (iii), 551}.")
    codes = set(parse_ingredients(text).ecodes)
    for expected in ("e627", "e631", "e330", "e341iii", "e551"):
        assert expected in codes, (expected, codes)


def test_arabic_subpart_normalised_to_roman():
    """Some labels print `322(1)` rather than `322(i)`."""
    assert "e322i" in extract_ecodes("EMULSIFIERS [INS 322(1)]")


def test_additive_name_without_number():
    """Additives declared by name only - roughly a third of what OFF finds."""
    codes = set(parse_ingredients(
        "Palm Oil, Xanthan Gum, Sodium Benzoate, Titanium Dioxide, "
        "Ascorbic Acid.").ecodes)
    for expected in ("e415", "e211", "e171", "e300"):
        assert expected in codes, (expected, codes)


def test_no_double_count_name_and_code():
    """"Caramel Colour (INS 150d)" must yield e150d only, not also generic e150."""
    codes = set(parse_ingredients("Water, Caramel Colour (INS 150d).").ecodes)
    assert codes == {"e150d"}, codes


def test_allergens_split_case_insensitively():
    """"CONTAINS WHEAT AND MILK" - the uppercase AND did not match \\band\\b."""
    label = parse_ingredients("Flour, Sugar. ALLERGEN INFORMATION: CONTAINS WHEAT AND MILK.")
    assert set(label.allergens) == {"wheat", "milk"}, label.allergens


def test_one_ingredient_per_line_is_split():
    """Flattening newlines into spaces merged a whole list into a single item."""
    label = parse_ingredients("Fish oil 73.9%\nsalmon 60%\nanchovy 35%\nsardine 4%")
    assert len(label.top_level_names()) == 4, label.top_level_names()


def test_pasted_nutrition_table_is_cut_off():
    label = parse_ingredients(
        "Milk solids, Soyabean oil, Minerals NUTRITION INFORMATION Per 100 g "
        "Energy 480 kcal Protein 12 g")
    assert label.top_level_names() == ["milk solids", "soyabean oil", "minerals"], \
        label.top_level_names()


def test_parser_never_raises():
    for bad in (None, "", "   ", "???", "[[[", "INS", "500)", "a" * 5000,
                "Energy.protrin.carbohydrate."):
        parse_ingredients(bad)  # must not raise


# --------------------------------------------------------------------------- #
# additives
# --------------------------------------------------------------------------- #


def test_msg_carries_no_penalty():
    """The anti-scaremongering guarantee. If this fails, the register drifted."""
    assessment = additive_risk(["e621", "e627", "e631", "e635"])
    assert assessment.risk_0_100 == 0.0, assessment
    assert not assessment.flagged
    assert len(assessment.cleared) == 4


def test_saccharin_and_msg_are_explicitly_cleared():
    for code in ("e954", "e621"):
        additive = lookup(code)
        assert additive is not None and additive.penalty == 0, code
        assert additive.note, code  # the reason must be recorded


def test_southampton_colour_is_the_top_penalty():
    tartrazine = lookup("e102")
    assert tartrazine.penalty == 6
    assert additive_risk(["e102"]).risk_0_100 > additive_risk(["e471"]).risk_0_100


def test_combination_rules_fire():
    """Benzoate + ascorbic acid, and the Southampton colour + benzoate pair."""
    assessment = additive_risk(["e110", "e211", "e300"])
    keys = {c.key for c in assessment.combinations}
    assert keys == {"benzoate_plus_ascorbate", "southampton_plus_benzoate"}, keys


def test_invalid_vs_uncatalogued_codes():
    """A typo is a data-quality signal; an uncatalogued real additive is not.

    Both used to be charged the same 0.5 "unknown" penalty, which meant 488
    occurrences of ordinary permitted additives inflated risk scores.
    """
    assessment = additive_risk(["e3221", "e1700", "e888"])
    assert set(assessment.invalid_codes) == {"e3221", "e1700"}, assessment.invalid_codes
    assert assessment.uncatalogued_codes == ["e888"]


def test_lookup_falls_back_to_parent():
    assert lookup("e500ii") is not None
    assert lookup("e331iii") is not None
    assert lookup("e1101ii") is not None
    assert lookup("e9999") is None


def test_diminishing_returns():
    """Eight harmless gums must not outweigh one Southampton colour."""
    benign = additive_risk(["e412", "e415", "e410", "e440", "e414", "e401",
                            "e460", "e461"])
    one_bad = additive_risk(["e102"])
    assert one_bad.risk_0_100 > benign.risk_0_100, (one_bad, benign)


# --------------------------------------------------------------------------- #
# categories
# --------------------------------------------------------------------------- #


def test_cola_is_not_water():
    """OFF tags colas `en:carbonated-waters`; a `-waters` suffix match filed
    Thums Up, Pepsi and Mountain Dew as water, scoring them A on every model."""
    for tags in (["en:carbonated-waters"], ["en:waters"]):
        result = classify({"categories_tags": tags, "product_name": "Mountain Dew",
                           "energy_kcal": 49.0, "sugars": 12.3})
        assert result.key != "water", (tags, result.key)


def test_plain_water_still_water():
    result = classify({"categories_tags": ["en:waters"],
                       "product_name": "Bisleri Water",
                       "energy_kcal": 0.0, "sugars": 0.0})
    assert result.key == "water"


def test_non_alcoholic_beer_is_not_alcohol():
    """`non-alcoholic-beverages` ends with `-alcoholic-beverages`."""
    result = classify({"categories_tags": ["en:non-alcoholic-beverages"],
                       "product_name": "Ginger Beer non-alcoholic"})
    assert result.key != "alcohol", result.key


def test_khatta_meetha_is_not_flour():
    """Substring matching found "atta" inside "khatta"."""
    result = classify({"categories_tags": [], "product_name": "Haldiram Khatta Meetha"})
    assert result.key == "salty_snacks", (result.key, result.matched_on)


def test_clear_majority_of_tags_beats_one_stray_tag():
    """Kurkure Masala Munch has four salty-snack tags and one stray biscuit tag."""
    tags = ["en:snacks", "en:salty-snacks", "en:appetizers", "en:biscuits-and-crackers",
            "en:chips-and-fries", "en:crisps", "en:puffed-salty-snacks"]
    assert classify({"categories_tags": tags,
                     "product_name": "Kurkure Masala Munch"}).key == "salty_snacks"


def test_one_extra_tag_does_not_override_the_specific_rule():
    """Plain "most tags wins" moved milk shakes into plain milk and cost 1.3 points
    of agreement with Open Food Facts. A narrow lead must not flip the category."""
    tags = ["en:milks", "en:milks-liquid-and-powder", "en:milk-shakes"]
    assert classify({"categories_tags": tags,
                     "product_name": "Chocolate milk shake"}).key == "dairy_drink"


def test_chocolate_with_milk_tags_is_not_milk():
    """Two chocolate tags and two milk tags is a tie, and dairy must not win ties."""
    tags = ["en:dairies", "en:snacks", "en:cocoa-and-its-products",
            "en:milks-liquid-and-powder", "en:milks", "en:chocolates"]
    assert classify({"categories_tags": tags,
                     "product_name": "Dairy Milk Silk Minis"}).key == "confectionery"


def test_name_beats_raw_ingredient_tags_for_snacks():
    """Banana chips are tagged as fruit, gathiya as pulses. The name says snack."""
    fruit = classify({"categories_tags": ["en:fruit-based-foods-and-beverages",
                                          "en:fruits-and-vegetables-based-foods"],
                      "product_name": "Yellow banana chips"})
    assert fruit.key == "salty_snacks", fruit.key
    pulses = classify({"categories_tags": ["en:legumes-and-their-products", "en:pulses"],
                       "product_name": "Papdi gathiya"})
    assert pulses.key == "salty_snacks", pulses.key
    # A plain pulse is still a pulse, including moong dal, which is also the name of
    # a fried snack.
    for plain in ("Toor dal", "Moong dal"):
        assert classify({"categories_tags": ["en:legumes-and-their-products", "en:pulses"],
                         "product_name": plain}).key == "staples", plain


def test_name_override_ignores_brand_and_flavour_words():
    """A pickle from a brand containing "bourbon", and chocolate-flavoured oats,
    were both pulled into snack categories by an over-broad override."""
    pickle = classify({"categories_tags": ["en:fruits-and-vegetables-based-foods"],
                       "product_name": "Achard legumes", "brands": "Le Bourbon"})
    assert pickle.key == "fruit_veg", pickle.key
    oats = classify({"categories_tags": ["en:cereals-and-their-products", "en:cereal-grains"],
                     "product_name": "High Protein Oats (Dark Chocolate)"})
    assert oats.key not in ("confectionery", "biscuits"), oats.key


def test_collagen_products_are_refused_as_supplements():
    assert classify({"categories_tags": [], "product_name": "collagen refreshers"}
                    ).scoreable is False


def test_supplements_are_refused():
    for row in ({"categories_tags": ["en:dietary-supplements"], "product_name": "X"},
                {"categories_tags": [], "product_name": "Gold Standard Whey Protein"},
                {"categories_tags": [], "product_name": "Unknown", "proteins": 75.0,
                 "carbohydrates": 5.0}):
        assert classify(row).scoreable is False, row


def test_spices_and_infant_food_refused():
    assert classify({"categories_tags": ["en:herbs-and-spices"],
                     "product_name": "Turmeric Powder"}).scoreable is False
    assert classify({"categories_tags": [],
                     "product_name": "Cerelac Stage 1"}).scoreable is False


# --------------------------------------------------------------------------- #
# nutrients
# --------------------------------------------------------------------------- #


def test_nan_is_treated_as_missing():
    """Parquet stores gaps as NaN. `nan > threshold` is False, so a NaN silently
    scored as zero penalty AND did not register as missing - grading empty
    records A."""
    assert num(float("nan")) is None
    assert num(None) is None
    assert num("not a number") is None
    assert num("3.5") == 3.5

    empty = {k: float("nan") for k in
             ("energy_kcal", "fat", "saturated_fat", "carbohydrates", "sugars",
              "proteins", "sodium", "salt", "fiber")}
    score = nutri_score(empty, family="general")
    assert score.missing, "an all-NaN panel must report missing fields"


def test_parle_g_matches_off_nutriscore():
    """OFF's own grade for barcode 8901719134845 is 'e'."""
    score = nutri_score(PARLE_G_ROW, family="general")
    assert score.grade == "E", (score.grade, score.score)


def test_beverage_sweetener_penalty():
    """A diet drink must not outscore water on the beverage algorithm."""
    base = {"energy_kcal": 0.5, "sugars": 0.0, "saturated_fat": 0.0,
            "salt": 0.02, "proteins": 0.0, "fiber": 0.0}
    plain = nutri_score(base, family="beverage", ecodes=[])
    diet = nutri_score(base, family="beverage", ecodes=["e951"])
    assert diet.score == plain.score + 4, (plain.score, diet.score)


def test_protein_cap_applies_above_11_a_points():
    row = {"energy_kcal": 500, "fat": 30, "saturated_fat": 15, "sugars": 30,
           "salt": 2.0, "proteins": 20, "fiber": 0.0}
    score = nutri_score(row, family="general")
    assert score.protein_capped
    # Cheese keeps its protein points under the 2023 rules.
    assert not nutri_score(row, family="cheese", is_cheese=True).protein_capped


def test_searo_flags_high_sodium_noodles():
    row = {"fat": 15.0, "sodium": 1.4, "energy_kcal": 450, "sugars": 3.0,
           "saturated_fat": 7.0}
    result = searo_screen(row, "noodles_pasta")
    assert result.applicable and not result.passes
    fields = {b[0] for b in result.breaches}
    assert "sodium_g" in fields and "total_fat" in fields, fields


def test_searo_excludes_non_sugar_sweeteners():
    result = searo_screen({"total_sugars": 0.0}, "beverage_sweetened", ["e955"])
    assert result.exclusions


# --------------------------------------------------------------------------- #
# processing
# --------------------------------------------------------------------------- #


def test_preservative_alone_is_not_ultra_processed():
    """The NOVA asymmetry. Preservatives, antioxidants and acidity regulators are
    NOT cosmetic additives and must not trigger group 4 on their own."""
    label = parse_ingredients(
        "Mango, Iodised Salt, Mustard Oil, Chilli Powder, Preservative (INS 211).")
    assert assess_processing(label).nova_group == 3


def test_colour_triggers_ultra_processed():
    label = parse_ingredients("Water, Sugar, Colour (INS 102).")
    assert assess_processing(label).nova_group == 4


def test_plural_markers_detected():
    """"Added Flavours" did not match because of a strict trailing boundary."""
    label = parse_ingredients("Water, Sugar, Added Flavours.")
    assert assess_processing(label).nova_group == 4


def test_single_ingredient_is_group_one():
    assert assess_processing(parse_ingredients("Whole Wheat Flour (Atta).")).nova_group == 1


def test_no_ingredients_returns_none_not_a_guess():
    assessment = assess_processing(parse_ingredients(None))
    assert assessment.nova_group is None
    assert assessment.confident is False


# --------------------------------------------------------------------------- #
# the index
# --------------------------------------------------------------------------- #


def test_index_range_and_shape():
    result = score_product(PARLE_G_ROW)
    assert result.scoreable
    assert 1 <= result.score <= 10
    assert result.band is not None and result.band.score == result.score
    assert len(result.pillars) == 4


def test_missing_pillars_do_not_award_free_points():
    """A product with no ingredient list used to get 100/100 on the processing and
    additive pillars - a free 40 points for having less data."""
    no_ingredients = dict(PARLE_G_ROW, ingredients_text=None)
    with_ingredients = score_product(PARLE_G_ROW)
    without = score_product(no_ingredients)
    unassessed = [p.key for p in without.pillars if not p.assessed]
    assert set(unassessed) == {"processing", "additive"}, unassessed
    assert without.composite_0_100 <= with_ingredients.composite_0_100 + 25


def test_caps_can_only_lower():
    for row in (PARLE_G_ROW, dict(PARLE_G_ROW, sodium=1.5, salt=3.75)):
        result = score_product(row)
        if result.binding_cap:
            assert result.score <= result.binding_cap.ceiling
            assert result.score <= (result.uncapped_score or 10)


def test_incomplete_panel_is_refused_not_guessed():
    result = score_product(dict(PARLE_G_ROW, energy_kcal=None, sodium=None))
    assert result.scoreable is False
    assert "incomplete" in result.refusal_reason.lower()


def test_water_scores_ten_and_cola_does_not():
    water = score_product({
        "code": "1", "product_name": "Packaged Drinking Water",
        "categories_tags": ["en:waters"], "ingredients_text": "Water.",
        "energy_kcal": 0.0, "fat": 0.0, "saturated_fat": 0.0,
        "carbohydrates": 0.0, "sugars": 0.0, "proteins": 0.0, "sodium": 0.001,
        "salt": 0.0025, "fiber": 0.0, "additives": [], "issues": [], "repairs": [],
    })
    assert water.score == 10, (water.score, water.composite_0_100)

    cola = score_product({
        "code": "2", "product_name": "Cola", "categories_tags": ["en:carbonated-drinks"],
        "ingredients_text": ("Carbonated Water, Sugar, Acidity Regulator (INS 338), "
                             "Caramel Colour (INS 150d), Added Flavours."),
        "energy_kcal": 44.0, "fat": 0.0, "saturated_fat": 0.0,
        "carbohydrates": 11.0, "sugars": 11.0, "proteins": 0.0, "sodium": 0.008,
        "salt": 0.02, "fiber": 0.0, "additives": [], "issues": [], "repairs": [],
    })
    assert cola.score <= 5, (cola.score, cola.composite_0_100)


def test_ladder_describes_the_score_not_the_product():
    """Each rung says what the model scored, never what a product does to a person.

    "Scores low" is a statement about a calculation. "Harmful" or "poor" about a
    named product is a claim of fact the project can't prove, and a health claim
    about a food is also something Indian advertising rules treat carefully.
    """
    from scoring.index import LADDER
    assert set(LADDER) == set(range(1, 11))
    text = " ".join(f"{b.label} {b.meaning} {b.basis}" for b in LADDER.values()).lower()
    for banned in ("toxic", "poison", "harmful", "unhealthy", "dangerous", "unsafe",
                   "poor", "avoid", "destroy", "causes cancer", "cancer-causing",
                   "cures", "your health", "your diet"):
        assert banned not in text, banned
    assert all(b.meaning.startswith("Scores") for b in LADDER.values())


def test_no_claim_that_a_regulator_forbids_a_named_product():
    """Cap reasons state the numbers against WHO's limit. They never say WHO
    "would not permit" a product, which is a statement about a specific product's
    status that WHO has not made."""
    result = score_product(dict(PARLE_G_ROW, sodium=1.6, salt=4.0))
    text = " ".join(c.reason for c in result.caps_applied).lower()
    assert "would not permit" not in text and "not allowed" not in text, text
    assert "against" in text or "over" in text, text


# --------------------------------------------------------------------------- #
# bad panels and mis-filed categories found in the second audit
# --------------------------------------------------------------------------- #

_BISCUIT = dict(PARLE_G_ROW)


def test_blank_sodium_zero_is_refused_in_salty_categories():
    """51 scored products (a sauce, noodles, biscuits) listed sodium as exactly 0.
    A zero scores as best case, so a blank field made the product look better."""
    result = score_product(dict(_BISCUIT, sodium=0.0, salt=0.0))
    assert not result.scoreable
    assert "sodium" in result.refusal_reason.lower()


def test_saturated_fat_zero_with_high_total_fat_is_refused():
    result = score_product(dict(_BISCUIT, fat=25.0, saturated_fat=0.0))
    assert not result.scoreable


def test_all_zero_panel_refused_unless_a_drink():
    """A vitamin gummy with an empty panel scored 10/10 because zeros look like water."""
    empty = dict(_BISCUIT, energy_kcal=0.0, fat=0.0, saturated_fat=0.0,
                 carbohydrates=0.0, sugars=0.0, proteins=0.0, sodium=0.1, salt=0.25,
                 categories_tags=[], product_name="Gummy Vites", ingredients_text=None)
    assert not score_product(empty).scoreable
    diet_drink = dict(empty, categories_tags=["en:carbonated-drinks"],
                      product_name="Diet cola", ingredients_text="Water, Sweetener (INS 951).")
    assert score_product(diet_drink).scoreable   # zero is normal for a diet drink


def test_empty_panel_with_no_tags_is_not_filed_as_water():
    result = classify({"categories_tags": [], "product_name": "Gummy Vites",
                       "energy_kcal": 0.0, "fat": 0.0, "carbohydrates": 0.0,
                       "proteins": 0.0})
    assert result.key != "water", result.key


def test_ice_cream_is_not_milk():
    """The milk rule matched the tag part "creams", and `ice-creams` ends in it."""
    tags = ["en:desserts", "en:frozen-desserts", "en:ice-creams-and-sorbets",
            "en:ice-creams", "en:ice-cream-tubs"]
    assert classify({"categories_tags": tags, "product_name": "Vanilla tub"}).key == "desserts_frozen"


def test_oats_are_not_nuts_and_seeds():
    """Open Food Facts tags every cereal grain `en:seeds`."""
    tags = ["en:plant-based-foods", "en:breakfasts", "en:seeds",
            "en:cereals-and-their-products", "en:breakfast-cereals", "en:cereal-grains"]
    assert classify({"categories_tags": tags, "product_name": "Masala Oats"}).key != "nuts_seeds"


def test_flavoured_or_sugar_free_water_is_a_beverage():
    for name in ("Perrier Citron", "Gatorade zero sugar lemon lime"):
        result = classify({"categories_tags": ["en:waters"], "product_name": name,
                           "energy_kcal": 0.0, "sugars": 0.0})
        assert result.key != "water", (name, result.key)


def test_liquid_milk_gets_the_who_screen_but_powder_does_not():
    milk = {"energy_kcal": 58.0, "fat": 3.0, "sodium": 0.04, "sugars": 4.8}
    assert searo_screen(milk, "milk").applicable
    full_fat_buffalo = {"energy_kcal": 110.0, "fat": 8.5, "sodium": 0.05}
    assert searo_screen(full_fat_buffalo, "milk").breaches   # over WHO's 7 g fat limit
    powder = {"energy_kcal": 496.0, "fat": 26.0, "sodium": 0.37}
    assert not searo_screen(powder, "milk").applicable




# --------------------------------------------------------------------------- #
# suggestions
# --------------------------------------------------------------------------- #


def _scored_table(rows):
    import pandas as pd

    cols = ["code", "product_name", "brands", "category", "score", "confidence",
            "scoreable"]
    return pd.DataFrame(rows, columns=cols)


def test_alternatives_same_category_and_better_only():
    from scoring.suggest import better_alternatives

    table = _scored_table([
        ("1", "Cream biscuit", "A", "biscuits", 2, "high", True),
        ("2", "Oat biscuit", "B", "biscuits", 6, "high", True),
        ("3", "Marie biscuit", "C", "biscuits", 3, "high", True),    # not 2 points better
        ("4", "Plain chips", "D", "salty_snacks", 9, "high", True),   # other category
        ("5", "Ragi biscuit", "E", "biscuits", 7, "medium", True),
    ])
    out = better_alternatives(table, "1")
    assert list(out["code"]) == ["5", "2"], list(out["code"])


def test_alternatives_skip_low_confidence_unnamed_and_duplicates():
    from scoring.suggest import better_alternatives

    table = _scored_table([
        ("1", "Cream biscuit", "A", "biscuits", 2, "high", True),
        ("2", "Guess biscuit", "B", "biscuits", 9, "low", True),       # low confidence
        ("3", None, None, "biscuits", 8, "high", True),                # unnamed
        ("4", "Oat biscuit", "C", "biscuits", 6, "high", True),
        ("5", "oat biscuit ", "c", "biscuits", 6, "medium", True),     # same product, other barcode
    ])
    out = better_alternatives(table, "1")
    assert list(out["code"]) == ["4"], list(out["code"])


def test_alternatives_not_worse_on_headline_nutrients():
    """A higher overall score isn't a good suggestion if the sugar is higher."""
    import pandas as pd
    from scoring.suggest import better_alternatives

    rows = [
        # code, name, brand, category, score, confidence, scoreable, sugars, sat fat, sodium mg
        ("1", "Digestive", "A", "biscuits", 2, "high", True, 13.0, 10.0, 368.0),
        ("2", "Low sugar", "B", "biscuits", 6, "high", True, 4.0, 3.0, 54.0),
        ("3", "Sweet cookie", "C", "biscuits", 4, "high", True, 29.0, 5.0, 90.0),
        ("4", "Salty cracker", "D", "biscuits", 5, "high", True, 3.0, 2.0, 900.0),
        ("5", "Low sugar copy", "B", "biscuits", 6, "high", True, 4.0, 3.0, 54.0),
    ]
    cols = ["code", "product_name", "brands", "category", "score", "confidence",
            "scoreable", "sugars", "saturated_fat", "sodium_mg"]
    out = better_alternatives(pd.DataFrame(rows, columns=cols), "1")
    # 3 has more sugar, 4 has more sodium, 5 is the same panel as 2.
    assert list(out["code"]) == ["2"], list(out["code"])


def test_alternatives_skip_zero_sodium_in_salty_categories():
    """A wafer with 0 mg sodium is a blank field, not a good product."""
    import pandas as pd
    from scoring.suggest import better_alternatives

    rows = [
        ("1", "Digestive", "A", "biscuits", 2, "high", True, 13.0, 10.0, 368.0),
        ("2", "Blank sodium wafer", "B", "biscuits", 6, "high", True, 4.0, 0.0, 0.0),
        ("3", "Real biscuit", "C", "biscuits", 5, "high", True, 4.0, 3.0, 120.0),
    ]
    cols = ["code", "product_name", "brands", "category", "score", "confidence",
            "scoreable", "sugars", "saturated_fat", "sodium_mg"]
    out = better_alternatives(pd.DataFrame(rows, columns=cols), "1")
    assert list(out["code"]) == ["3"], list(out["code"])


def test_alternatives_skip_barcode_only_names():
    import pandas as pd
    from scoring.suggest import better_alternatives

    rows = [
        ("1", "Digestive", "A", "biscuits", 2, "high", True, True),
        ("2", "8901560043037", None, "biscuits", 7, "high", True, False),
        ("3", "Oat biscuit", "C", "biscuits", 6, "high", True, True),
    ]
    cols = ["code", "product_name", "brands", "category", "score", "confidence",
            "scoreable", "named"]
    out = better_alternatives(pd.DataFrame(rows, columns=cols), "1")
    assert list(out["code"]) == ["3"], list(out["code"])


def test_alternatives_empty_for_unscored_or_catch_all():
    from scoring.suggest import better_alternatives

    table = _scored_table([
        ("1", "Whey", "A", "supplement", None, "low", False),
        ("2", "Mystery", "B", "general", 2, "high", True),
        ("3", "Other mystery", "C", "general", 8, "high", True),
        ("4", "Chips", "D", "salty_snacks", 8, "high", True),
    ])
    assert better_alternatives(table, "1").empty   # not scored, nothing to improve on
    assert better_alternatives(table, "2").empty   # catch-all bucket has no real peers
    assert better_alternatives(table, "nope").empty


# --------------------------------------------------------------------------- #
# daily limits and typed-in labels
# --------------------------------------------------------------------------- #


def test_daily_share_arithmetic():
    from scoring.limits import daily_shares

    row = {"sodium": 0.8, "added_sugars": 10.0, "saturated_fat": 5.5,
           "trans_fat": 0.1, "fat": 20.0}
    shares = {s.label: s for s in daily_shares(row, 50)}
    # 50 g of a product with 800 mg sodium per 100 g gives 400 mg, a fifth of 2000 mg.
    assert round(shares["Sodium"].percent, 1) == 20.0
    assert round(shares["Sodium"].portions_to_limit, 1) == 5.0
    assert round(shares["Added sugar"].in_portion, 1) == 5.0
    assert round(shares["Saturated fat"].percent, 1) == 12.5   # 2.75 g of 22 g


def test_daily_share_uses_total_sugars_only_when_added_is_missing_and_says_so():
    from scoring.limits import daily_shares

    with_added = {s.label: s for s in daily_shares({"added_sugars": 4.0, "sugars": 20.0}, 100)}
    assert "Added sugar" in with_added and "Total sugars" not in with_added
    without = {s.label: s for s in daily_shares({"sugars": 20.0}, 100)}
    assert "Total sugars" in without and without["Total sugars"].note


def test_daily_share_skips_missing_values_instead_of_counting_zero():
    from scoring.limits import daily_shares

    labels = [s.label for s in daily_shares({"sodium": 0.5, "fat": float("nan")}, 100)]
    assert labels == ["Sodium"], labels
    assert daily_shares({"sodium": 0.5}, 0) == []


def test_serving_size_text_is_read():
    from scoring.limits import serving_grams

    assert serving_grams("45g") == 45
    assert serving_grams("30 g") == 30
    assert serving_grams("1 biscuit (10g)") == 10
    assert serving_grams("250 ml") == 250
    assert serving_grams("one cup") is None
    assert serving_grams(None) is None


def test_blank_input_is_unknown_not_zero():
    from scoring.custom import parse_number

    assert parse_number("") is None
    assert parse_number("   ") is None
    assert parse_number("0") == 0.0
    assert parse_number("12,5") == 12.5
    assert parse_number("<0.5") == 0.5
    for bad in ("abc", "-3", "1.2.3"):
        try:
            parse_number(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have been rejected")


def test_per_serving_numbers_are_scaled_to_100g():
    from scoring.custom import row_from_inputs

    row = row_from_inputs(
        name="x", category_key="biscuits", per_serving=True, serving_g=25.0,
        values={"energy_kcal": 120.0, "fat": 5.0}, sodium_mg=50.0, salt_g=None,
        ingredients=None)
    assert row["energy_kcal"] == 480.0 and row["fat"] == 20.0
    assert round(row["sodium"], 3) == 0.2          # 50 mg in 25 g = 200 mg per 100 g
    assert round(row["salt"], 3) == 0.5


def test_salt_is_converted_to_sodium_and_sodium_wins_when_both_given():
    from scoring.custom import row_from_inputs

    base = dict(name=None, category_key="biscuits", per_serving=False,
                serving_g=None, values={}, ingredients=None)
    only_salt = row_from_inputs(**base, sodium_mg=None, salt_g=1.0)
    assert round(only_salt["sodium"], 3) == 0.4
    both = row_from_inputs(**base, sodium_mg=100.0, salt_g=5.0)
    assert round(both["sodium"], 3) == 0.1


def test_per_serving_without_a_serving_size_is_an_error():
    from scoring.custom import row_from_inputs

    try:
        row_from_inputs(name=None, category_key="biscuits", per_serving=True,
                        serving_g=None, values={}, sodium_mg=None, salt_g=None,
                        ingredients=None)
    except ValueError:
        return
    raise AssertionError("expected a ValueError")


def test_typed_label_scores_and_missing_fields_are_refused_not_guessed():
    from scoring.custom import row_from_inputs

    full = row_from_inputs(
        name="Test biscuit", category_key="biscuits", per_serving=False,
        serving_g=None, ingredients="Wheat flour, sugar, palm oil, salt",
        values={"energy_kcal": 480.0, "proteins": 7.0, "carbohydrates": 70.0,
                "sugars": 25.0, "fat": 18.0, "saturated_fat": 9.0},
        sodium_mg=400.0, salt_g=None)
    assert score_product(full).scoreable
    # Leave out sodium: blank is unknown, so there is nothing to score.
    no_sodium = dict(full, sodium=None, salt=None)
    refused = score_product(no_sodium)
    assert not refused.scoreable and "sodium" in refused.refusal_reason


def test_chosen_category_is_taken_as_given():
    row = {"category_override": "milk", "product_name": "Chocolate bar",
           "categories_tags": ["en:chocolates"]}
    assert classify(row).key == "milk"
    assert classify(dict(row, category_override="not a category")).key != "milk"


def test_input_warnings_catch_typing_mistakes():
    from scoring.custom import input_warnings

    sat_over_fat = input_warnings({"fat": 5.0, "saturated_fat": 9.0})
    assert any("Saturated fat" in w for w in sat_over_fat)
    kj = input_warnings({"energy_kcal": 2000.0, "fat": 20.0, "carbohydrates": 60.0,
                         "proteins": 8.0})
    assert any("kilojoules" in w for w in kj), kj
    assert input_warnings({"energy_kcal": 480.0, "fat": 18.0, "saturated_fat": 9.0,
                           "carbohydrates": 70.0, "sugars": 25.0, "proteins": 7.0}) == []


if __name__ == "__main__":
    import traceback

    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception:
            failed.append(name)
            print(f"FAIL {name}")
            traceback.print_exc(limit=3)
    print(f"\n{passed}/{len(tests)} passed")
    if failed:
        print("failed:", ", ".join(failed))
        sys.exit(1)
