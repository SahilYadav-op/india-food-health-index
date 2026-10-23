"""
Evidence-graded register of food additives found on Indian labels.

This module is where consumer food apps most often go wrong, so its design rules
are worth stating plainly.

RULE 1 - the penalty tracks the strength of the evidence, not the strength of the
internet's opinion. Every entry carries an `evidence` grade and a source. Four
substances that are heavily attacked online get a penalty of ZERO here, with the
reason recorded, because the evidence does not support one:

  MSG (INS 621) and the ribonucleotides INS 627/631/635
      "Chinese restaurant syndrome" traces to a 1968 letter to a medical journal.
      Double-blind trials have not reproduced it. JECFA ADI "not specified",
      FDA GRAS. FSSAI's mandatory "not recommended for infants below 12 months"
      declaration is precautionary labelling, not a toxicological finding. MSG is
      12.3% sodium against table salt's 39.3%, so replacing salt with MSG lowers
      total sodium - a WHO-compatible reduction strategy.
  Saccharin (INS 954)
      Delisted from the US NTP carcinogen report in 2000 and from California
      Prop 65 in 2001. IARC Group 3. The rat bladder-tumour mechanism depends on
      rat-specific urine chemistry.
  Food-grade carrageenan (INS 407)
      The colitis and tumour-promotion literature concerns DEGRADED carrageenan
      (poligeenan, ~10-20 kDa), which is not authorised as a food additive
      anywhere. Food-grade carrageenan is >100 kDa. Retains a token marker
      penalty for one observational cancer signal, not the poligeenan data.
  Palm oil / palmolein
      Handled in nutrients.py, not here, and deliberately carries no penalty of
      its own. Its LDL effect (+0.24 mmol/L) is fully explained by its 40-50%
      saturated fat, which the nutrition panel already penalises. Charging it
      twice is double-counting.

RULE 2 - separate "the regulators disagree" from "this is proven harmful".
Titanium dioxide is the clearest case: EFSA could not exclude genotoxicity and
the EU banned it in August 2022, while JECFA reviewed the same dossier in 2023
and kept the ADI unchanged, and India had not banned it when last checked
(July 2026). The honest label is regulatory divergence.

RULE 3 - do not stack a penalty that the nutrition panel already charges. Sodium
is penalised from the declared sodium figure. The sodium-bearing additives here
(INS 500, 331, 339, 451) therefore carry only their own non-sodium penalty; their
sodium contribution is already in the panel.

RULE 4 - some risks are combinations, not substances. Sodium benzoate is
unremarkable alone but can decarboxylate to benzene in the presence of ascorbic
acid, accelerated by heat and light. That is encoded as a co-occurrence rule, not
as a penalty on benzoate.

Penalties are on a 0-10 per-additive scale and aggregate with diminishing returns
(see `additive_risk`), so eight harmless thickeners never outweigh one Southampton
colour.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Evidence grades, strongest first.
STRONG = "strong"      # RCT or consistent cohorts with a plausible mechanism
MODERATE = "moderate"  # one good RCT, or large consistent observational evidence
LIMITED = "limited"    # animal / in-vitro / single small trial / single cohort
DIVERGENT = "divergent"  # regulators disagree; no settled human finding
NONE = "none"          # evidence does not support a penalty


@dataclass(frozen=True)
class Additive:
    ecode: str
    ins: str
    name: str
    functional_class: str
    penalty: int
    evidence: str
    nova_cosmetic: bool = False
    permitted_in_india: bool = True
    note: str = ""
    sources: tuple[str, ...] = field(default_factory=tuple)


def _a(*args, **kwargs) -> Additive:
    return Additive(*args, **kwargs)


# --------------------------------------------------------------------------- #
# the register
# --------------------------------------------------------------------------- #

REGISTER: dict[str, Additive] = {}


def _add(a: Additive) -> None:
    REGISTER[a.ecode] = a


# ---- colours: the Southampton Six ----------------------------------------- #
# McCann, Lancet 2007: randomised, double-blind, placebo-controlled crossover in
# 297 children; two colour+benzoate mixes significantly increased hyperactivity.
# The EU has required "may have an adverse effect on activity and attention in
# children" on these since 20 July 2010. FSSAI's list of permitted synthetic
# colours includes tartrazine, sunset yellow, carmoisine and ponceau 4R. This is
# the best-evidenced additive penalty in the register.
_SOUTHAMPTON_SRC = (
    "McCann et al., Lancet 2007;370:1560-67",
    "Regulation (EC) 1333/2008 Annex V",
)
for _code, _ins, _name, _india in [
    ("e102", "102", "Tartrazine", True),
    ("e104", "104", "Quinoline Yellow", False),
    ("e110", "110", "Sunset Yellow FCF", True),
    ("e122", "122", "Carmoisine (Azorubine)", True),
    ("e124", "124", "Ponceau 4R", True),
    ("e129", "129", "Allura Red AC", False),
]:
    _add(_a(_code, _ins, _name, "colour", 6, MODERATE, nova_cosmetic=True,
            permitted_in_india=_india,
            note="One of the six 'Southampton colours'. A randomised controlled "
                 "trial linked these to increased hyperactivity and reduced "
                 "attention in children, and the EU has required a warning on "
                 "them since 2010. India has no equivalent warning requirement.",
            sources=_SOUTHAMPTON_SRC))

# EFSA cut the ADIs for quinoline yellow, sunset yellow and ponceau 4R after
# re-evaluation; ponceau 4R fell from 4 to 0.7 mg/kg bw/day.

_add(_a("e127", "127", "Erythrosine", "colour", 5, LIMITED, nova_cosmetic=True,
        note="The US FDA revoked its authorisation for use in food in January "
             "2025, after studies showing cancer in male rats (a mechanism FDA "
             "described as specific to rats). Food makers there have until "
             "January 2027 to reformulate. It is on FSSAI's list of permitted "
             "synthetic colours.",
        sources=("FDA revocation of FD&C Red No. 3, January 2025",
                 "FSSAI permitted synthetic colours")))

for _code, _ins, _name in [("e132", "132", "Indigo Carmine"),
                           ("e133", "133", "Brilliant Blue FCF"),
                           ("e143", "143", "Fast Green FCF")]:
    _add(_a(_code, _ins, _name, "colour", 1, NONE, nova_cosmetic=True,
            note="A permitted synthetic colour with no behavioural signal "
                 "comparable to the Southampton colours. Counted only as a sign "
                 "of industrial formulation, not as a hazard.",
            sources=("FSSAI permitted synthetic colours",)))

# Caramel classes: III and IV carry 4-methylimidazole, formed with ammonia.
for _code, _ins, _name, _pen in [("e150a", "150a", "Caramel (plain)", 0),
                                 ("e150b", "150b", "Caramel (caustic sulphite)", 1),
                                 ("e150c", "150c", "Caramel (ammonia)", 2),
                                 ("e150d", "150d", "Caramel (sulphite ammonia)", 2)]:
    _add(_a(_code, _ins, _name, "colour", _pen,
            LIMITED if _pen else NONE, nova_cosmetic=True,
            note=("Ammonia-process caramels contain 4-methylimidazole, which "
                  "carries a rodent carcinogenicity signal and a California "
                  "Prop 65 listing. Plain caramel does not."
                  if _pen >= 2 else
                  "Plain caramel colour, made by heating sugar. No safety signal."),
            sources=("EFSA Journal 2011;9(3):2004",)))

# Natural colours: no hazard penalty, but still ultra-processing markers.
for _code, _ins, _name in [("e100", "100", "Curcumin"),
                           ("e160a", "160a", "Carotenes"),
                           ("e160b", "160b", "Annatto"),
                           ("e160c", "160c", "Paprika extract"),
                           ("e162", "162", "Beetroot Red"),
                           ("e163", "163", "Anthocyanins")]:
    _add(_a(_code, _ins, _name, "colour", 0, NONE, nova_cosmetic=True,
            note="A colour of natural origin with no safety concern at permitted "
                 "levels. Its presence still signals a formulated product."))

_add(_a("e120", "120", "Carmine / Cochineal", "colour", 1, LIMITED,
        nova_cosmetic=True,
        note="Insect-derived, a recognised though uncommon allergen, and not "
             "vegetarian - which matters to many Indian consumers independently "
             "of health.",
        sources=("EFSA Journal 2015;13(11):4288",)))

# ---- titanium dioxide: the regulatory-divergence case --------------------- #
_add(_a("e171", "171", "Titanium Dioxide", "colour", 5, DIVERGENT,
        nova_cosmetic=True,
        note="Regulators disagree. EFSA concluded in 2021 that a concern for "
             "genotoxicity could not be excluded and could set no ADI, and the "
             "EU banned it from food in August 2022. JECFA reviewed the same "
             "evidence in 2023 and left the ADI unchanged, and India had not "
             "banned it when this was last checked (July 2026). This penalty "
             "reflects the precautionary EU position, not a demonstrated human "
             "harm.",
        sources=("EFSA Journal 2021;19(5):6585",
                 "Commission Regulation (EU) 2022/63",
                 "JECFA 97th meeting, 2023")))

# ---- sweeteners ----------------------------------------------------------- #
# WHO's 2023 guideline advises against non-sugar sweeteners for weight control,
# but it is a CONDITIONAL recommendation on low-certainty evidence and explicitly
# excludes people with diabetes. The penalty is deliberately kept well below the
# free-sugar penalty it displaces - otherwise the model would perversely rank a
# full-sugar cola above a diet one.
_NSS_NOTE = (
    "WHO advises against non-sugar sweeteners for weight control (2023), but "
    "that recommendation is conditional, rests on low-certainty evidence, and "
    "does not apply to people with diabetes. Penalised less than the sugar it "
    "replaces."
)
_NSS_SRC = ("WHO guideline on non-sugar sweeteners, 15 May 2023",)

_add(_a("e951", "951", "Aspartame", "sweetener", 2, LIMITED, nova_cosmetic=True,
        note=_NSS_NOTE + " IARC classified aspartame Group 2B in 2023 - a hazard "
             "class, not a dose estimate - and JECFA reaffirmed the 40 mg/kg "
             "ADI the same day. A 70 kg adult would need 9-14 cans a day to "
             "reach it. Genuine risk only in phenylketonuria, which the label "
             "must declare.",
        sources=_NSS_SRC + ("IARC/JECFA joint release, 14 July 2023",)))
_add(_a("e950", "950", "Acesulfame Potassium", "sweetener", 2, LIMITED,
        nova_cosmetic=True, note=_NSS_NOTE, sources=_NSS_SRC))
_add(_a("e955", "955", "Sucralose", "sweetener", 2, LIMITED, nova_cosmetic=True,
        note=_NSS_NOTE + " Claims about thermal breakdown above ~120 C come from "
             "model chemistry and are irrelevant to unheated products.",
        sources=_NSS_SRC))
_add(_a("e952", "952", "Cyclamate", "sweetener", 2, LIMITED, nova_cosmetic=True,
        note=_NSS_NOTE, sources=_NSS_SRC))
_add(_a("e961", "961", "Neotame", "sweetener", 2, LIMITED, nova_cosmetic=True,
        note=_NSS_NOTE, sources=_NSS_SRC))
_add(_a("e960", "960", "Steviol Glycosides", "sweetener", 1, LIMITED,
        nova_cosmetic=True,
        note="Plant-derived but still a non-sugar sweetener covered by the WHO "
             "2023 advice. JECFA ADI 4 mg/kg bw/day as steviol equivalents.",
        sources=_NSS_SRC))

# Saccharin: penalty ZERO, and the reason is recorded so it cannot drift back.
_add(_a("e954", "954", "Saccharin", "sweetener", 0, NONE, nova_cosmetic=True,
        note="Frequently listed as a cancer risk online; it is not. Delisted "
             "from the US NTP carcinogen report in 2000 and California Prop 65 "
             "in 2001, and IARC Group 3. The rat bladder-tumour mechanism "
             "depends on rat-specific urine chemistry and does not apply to "
             "humans.",
        sources=("NTP 9th Report on Carcinogens, 2000",
                 "OEHHA Prop 65 delisting, 6 April 2001")))

# Polyols are outside the WHO NSS guideline.
for _code, _ins, _name in [("e420", "420", "Sorbitol"), ("e421", "421", "Mannitol"),
                           ("e965", "965", "Maltitol"), ("e967", "967", "Xylitol"),
                           ("e968", "968", "Erythritol"), ("e953", "953", "Isomalt")]:
    _add(_a(_code, _ins, _name, "sweetener", 1, NONE, nova_cosmetic=True,
            note="A sugar alcohol, outside the scope of WHO's non-sugar-sweetener "
                 "advice. Main effect is laxative at higher doses."))

# ---- emulsifiers, thickeners, stabilisers --------------------------------- #
_EMULSIFIER_NOTE = (
    "Emulsifier evidence is real but early: mouse and ex-vivo work shows "
    "microbiome disruption, one 11-day trial in 16 people at doses far above "
    "normal intake showed modest effects, and one French cohort reported a "
    "cancer association. Emulsifier intake is also an almost perfect proxy for "
    "ultra-processed food intake, which confounds the cohort finding. Penalised "
    "as a processing marker, not as an established hazard."
)
_EMULSIFIER_SRC = (
    "Chassaing et al., Nature 2015;519:92-96",
    "Chassaing et al., Gastroenterology 2022;162:743-756",
    "Sellem et al., PLOS Medicine 2024;21(2):e1004338",
)
for _code, _ins, _name, _pen in [
    ("e433", "433", "Polysorbate 80", 3),
    ("e466", "466", "Carboxymethylcellulose", 3),
    ("e471", "471", "Mono- and Diglycerides of Fatty Acids", 2),
    ("e472e", "472e", "DATEM", 2),
    ("e472c", "472c", "Citric Acid Esters of Mono/Diglycerides", 2),
    ("e470", "470", "Fatty Acid Salts", 1),
    ("e476", "476", "Polyglycerol Polyricinoleate", 1),
    ("e481", "481", "Sodium Stearoyl Lactylate", 1),
    ("e491", "491", "Sorbitan Monostearate", 1),
]:
    _add(_a(_code, _ins, _name, "emulsifier", _pen, LIMITED, nova_cosmetic=True,
            note=_EMULSIFIER_NOTE, sources=_EMULSIFIER_SRC))

_add(_a("e407", "407", "Carrageenan", "thickener", 2, LIMITED, nova_cosmetic=True,
        note="Often described online as causing colitis. That literature is "
             "about DEGRADED carrageenan (poligeenan), which is not permitted as "
             "a food additive anywhere; food-grade carrageenan is a much larger "
             "molecule. This small penalty reflects one observational breast-"
             "cancer association, not the poligeenan data. EFSA made the group "
             "ADI temporary in 2018 pending better measurement methods.",
        sources=("EFSA Journal 2018;16(4):5238",
                 "Sellem et al., PLOS Medicine 2024;21(2):e1004338")))

for _code, _ins, _name in [("e412", "412", "Guar Gum"), ("e415", "415", "Xanthan Gum"),
                           ("e410", "410", "Locust Bean Gum"),
                           ("e440", "440", "Pectin"), ("e414", "414", "Acacia Gum"),
                           ("e401", "401", "Sodium Alginate"),
                           ("e460", "460", "Cellulose"),
                           ("e461", "461", "Methylcellulose")]:
    _add(_a(_code, _ins, _name, "thickener", 1, NONE, nova_cosmetic=True,
            note="A soluble-fibre thickener with no established safety concern. "
                 "Counted only as a marker of industrial formulation."))

# ---- preservatives -------------------------------------------------------- #
_add(_a("e211", "211", "Sodium Benzoate", "preservative", 1, LIMITED,
        note="Unremarkable on its own at permitted levels. Two caveats: it can "
             "form benzene when combined with ascorbic acid, especially in warm "
             "or sunlit drinks (scored separately as a combination), and it was "
             "one of the two variables in the Southampton hyperactivity trial, "
             "so its effect cannot be separated from the colours there. JECFA "
             "raised the group ADI to 20 mg/kg bw in 2021.",
        sources=("JECFA 92nd meeting, 2021", "EFSA Journal 2016;14(3):4433")))
for _code, _ins, _name in [("e210", "210", "Benzoic Acid"),
                           ("e212", "212", "Potassium Benzoate"),
                           ("e213", "213", "Calcium Benzoate")]:
    _add(_a(_code, _ins, _name, "preservative", 1, LIMITED,
            note="Same class as sodium benzoate; see the benzene combination rule.",
            sources=("JECFA 92nd meeting, 2021",)))

# Sulphites: a genuine, documented reaction in a real subgroup.
for _code, _ins, _name in [("e220", "220", "Sulphur Dioxide"),
                           ("e221", "221", "Sodium Sulphite"),
                           ("e223", "223", "Sodium Metabisulphite"),
                           ("e224", "224", "Potassium Metabisulphite"),
                           ("e228", "228", "Potassium Bisulphite")]:
    _add(_a(_code, _ins, _name, "preservative", 2, STRONG,
            note="Sulphites trigger bronchoconstriction in a minority of people "
                 "with asthma - one of the few additive effects with solid "
                 "clinical evidence. In the EU, labels must declare sulphites "
                 "above 10 mg/kg.",
            sources=("EFSA Journal 2016;14(4):4438",
                     "Regulation (EU) 1169/2011, Annex II")))

# Nitrites and nitrates: the marker that identifies processed meat.
for _code, _ins, _name in [("e249", "249", "Potassium Nitrite"),
                           ("e250", "250", "Sodium Nitrite"),
                           ("e251", "251", "Sodium Nitrate"),
                           ("e252", "252", "Potassium Nitrate")]:
    _add(_a(_code, _ins, _name, "preservative", 4, MODERATE,
            note="IARC classifies PROCESSED MEAT as Group 1 carcinogenic to "
                 "humans - 18% higher colorectal cancer risk per 50 g eaten "
                 "daily - and these curing salts are what identify a product as "
                 "processed meat. EFSA's 2017 review found the additive itself "
                 "safe at permitted levels but could not separate its "
                 "contribution from the meat matrix.",
            sources=("IARC Monographs Vol. 114, 2015",
                     "EFSA Journal 2017;15(6):4786")))

for _code, _ins, _name in [("e200", "200", "Sorbic Acid"),
                           ("e202", "202", "Potassium Sorbate"),
                           ("e270", "270", "Lactic Acid"),
                           ("e260", "260", "Acetic Acid"),
                           ("e296", "296", "Malic Acid")]:
    _add(_a(_code, _ins, _name, "preservative", 0, NONE,
            note="No safety concern at permitted levels."))

# ---- antioxidants --------------------------------------------------------- #
_add(_a("e320", "320", "BHA (Butylated Hydroxyanisole)", "antioxidant", 2, LIMITED,
        note="Widely described as a carcinogen. IARC did classify it Group 2B in "
             "1986, but on rat and hamster FORESTOMACH tumours - and humans have "
             "no forestomach. IARC later judged the mechanism not relevant to "
             "humans without formally revoking the class. Penalised modestly as "
             "a marker of cheap frying fat, not as a carcinogen.",
        sources=("IARC Monographs Vol. 40, 1986", "JECFA ADI 0-0.5 mg/kg bw")))
_add(_a("e321", "321", "BHT", "antioxidant", 1, LIMITED,
        note="No carcinogenicity classification. JECFA ADI 0-0.3 mg/kg bw. "
             "Treated as a cheap-fat marker.",
        sources=("JECFA ADI 0-0.3 mg/kg bw",)))
_add(_a("e319", "319", "TBHQ", "antioxidant", 1, LIMITED,
        note="JECFA ADI 0-0.7 mg/kg bw. The immunotoxicity signal is from mice "
             "only. Used in frying oils and fried snacks, so it works as a "
             "cheap-fat marker.",
        sources=("JECFA ADI 0-0.7 mg/kg bw",)))
_add(_a("e300", "300", "Ascorbic Acid (Vitamin C)", "antioxidant", 0, NONE,
        note="Vitamin C. No penalty. Relevant only because it can react with "
             "benzoate preservatives to form benzene."))
for _code, _ins, _name in [("e301", "301", "Sodium Ascorbate"),
                           ("e306", "306", "Tocopherols (Vitamin E)"),
                           ("e330", "330", "Citric Acid"),
                           ("e331", "331", "Sodium Citrate"),
                           ("e333", "333", "Calcium Citrate")]:
    _add(_a(_code, _ins, _name, "antioxidant", 0, NONE,
            note="No safety concern at permitted levels."))

# ---- phosphates ----------------------------------------------------------- #
_PHOSPHATE_NOTE = (
    "EFSA set a group limit of 40 mg/kg body weight per day as phosphorus in "
    "2019 and found that infants, toddlers and children already exceed it on "
    "average. The limit also does not apply to people with reduced kidney "
    "function, around 10% of the population. Additive phosphate is absorbed "
    "almost completely, unlike the phosphorus naturally bound in food. EFSA "
    "found no consistent link to cardiovascular outcomes - the concern is "
    "cumulative exposure, especially in children."
)
_PHOSPHATE_SRC = ("EFSA Journal 2019;17(6):5674",)
for _code, _ins, _name in [("e338", "338", "Phosphoric Acid"),
                           ("e339", "339", "Sodium Phosphates"),
                           ("e340", "340", "Potassium Phosphates"),
                           ("e341", "341", "Calcium Phosphates"),
                           ("e343", "343", "Magnesium Phosphates"),
                           ("e450", "450", "Diphosphates"),
                           ("e451", "451", "Triphosphates"),
                           ("e452", "452", "Polyphosphates")]:
    _add(_a(_code, _ins, _name, "acidity regulator", 3, MODERATE,
            nova_cosmetic=False, note=_PHOSPHATE_NOTE, sources=_PHOSPHATE_SRC))

# ---- aluminium-bearing additives ------------------------------------------ #
_ALU_NOTE = (
    "JECFA allows 2 mg aluminium/kg body weight per week and EFSA half that - a "
    "genuine twofold disagreement - but both concluded permitted uses are "
    "acceptable. The aluminium-Alzheimer's link that drives most online alarm is "
    "not supported; it originated in dialysis encephalopathy. The real concern "
    "is cumulative intake in children who eat a lot of baked goods."
)
for _code, _ins, _name in [("e541", "541", "Sodium Aluminium Phosphate"),
                           ("e520", "520", "Aluminium Sulphate"),
                           ("e554", "554", "Sodium Aluminosilicate"),
                           ("e555", "555", "Potassium Aluminium Silicate")]:
    _add(_a(_code, _ins, _name, "raising agent", 2, LIMITED, note=_ALU_NOTE,
            sources=("EFSA Journal 2018;16(7):5372", "JECFA 74th meeting, 2011")))

# ---- flavour enhancers: penalty ZERO, reason recorded --------------------- #
_MSG_NOTE = (
    "No penalty. The 'Chinese restaurant syndrome' story began with a 1968 "
    "letter to a medical journal, and double-blind trials have not reproduced "
    "it. JECFA sets no numerical limit and the FDA treats MSG as "
    "generally recognised as safe. FSSAI's mandatory 'not recommended for "
    "infants below 12 months' wording is precautionary labelling, not a finding "
    "of harm. MSG is 12.3% sodium against table salt's 39.3%, so using it to "
    "replace some salt actually lowers total sodium. Any sodium it does "
    "contribute is already counted in the panel figure."
)
_MSG_SRC = ("FDA Q&A on MSG",
            "J Acad Nutr Diet 2021 on the history of the MSG scare",
            "JECFA: ADI not specified")
for _code, _ins, _name in [("e621", "621", "Monosodium Glutamate"),
                           ("e627", "627", "Disodium Guanylate"),
                           ("e631", "631", "Disodium Inosinate"),
                           ("e635", "635", "Disodium Ribonucleotides")]:
    _add(_a(_code, _ins, _name, "flavour enhancer", 0, NONE, nova_cosmetic=True,
            note=_MSG_NOTE, sources=_MSG_SRC))

# ---- raising / anticaking / misc ------------------------------------------ #
for _code, _ins, _name in [("e500", "500", "Sodium Carbonates"),
                           ("e501", "501", "Potassium Carbonates"),
                           ("e503", "503", "Ammonium Carbonates"),
                           ("e504", "504", "Magnesium Carbonates"),
                           ("e551", "551", "Silicon Dioxide"),
                           ("e552", "552", "Calcium Silicate"),
                           ("e553", "553", "Magnesium Silicate"),
                           ("e170", "170", "Calcium Carbonate"),
                           ("e296", "296", "Malic Acid"),
                           ("e322", "322", "Lecithin"),
                           ("e327", "327", "Calcium Lactate"),
                           ("e336", "336", "Potassium Tartrates"),
                           ("e262", "262", "Sodium Acetates"),
                           ("e575", "575", "Glucono-delta-lactone"),
                           ("e1100", "1100", "Amylase"),
                           ("e1101", "1101", "Protease / Bromelain / Papain"),
                           ("e1400", "1400", "Dextrin"),
                           ("e1422", "1422", "Acetylated Distarch Adipate"),
                           ("e1442", "1442", "Hydroxypropyl Distarch Phosphate")]:
    _add(_a(_code, _ins, _name, "processing aid", 0, NONE,
            note="No safety concern at permitted levels. Modified starches and "
                 "enzymes still signal industrial formulation."))

# Modified starches are NOVA "rare culinary use" markers even at zero penalty.
for _code in ("e1400", "e1422", "e1442"):
    REGISTER[_code] = Additive(**{**REGISTER[_code].__dict__, "nova_cosmetic": False})

_add(_a("e904", "904", "Shellac", "glazing agent", 0, NONE, nova_cosmetic=True,
        note="Insect-derived resin. No health concern, but not vegetarian, which "
             "matters to many Indian consumers."))
_add(_a("e441", "441", "Gelatin", "gelling agent", 0, NONE,
        note="Animal-derived. No health concern; relevant to vegetarian and "
             "religious dietary requirements."))

# ---- long tail ------------------------------------------------------------ #
# Measured on the India corpus, these account for ~1,150 additive occurrences.
# Catalogued explicitly so they resolve to a real entry with a real penalty
# instead of falling through to the unrecognised-code path.

# Propionates: bread preservatives. One mechanistic human/animal study linked
# propionate to insulin counter-regulation; nothing outcome-level.
for _code, _ins, _name in [("e280", "280", "Propionic Acid"),
                           ("e281", "281", "Sodium Propionate"),
                           ("e282", "282", "Calcium Propionate"),
                           ("e283", "283", "Potassium Propionate")]:
    _add(_a(_code, _ins, _name, "preservative", 1, LIMITED,
            note="A mould inhibitor used in packaged bread. One small human and "
                 "mouse study linked propionate to insulin counter-regulatory "
                 "hormones; there is no outcome-level evidence. Small penalty.",
            sources=("Tirosh et al., Sci Transl Med 2019;11:eaav0120",)))

# Emulsifiers: same class and same evidence base as those above.
for _code, _ins, _name in [("e435", "435", "Polysorbate 60"),
                           ("e436", "436", "Polysorbate 65"),
                           ("e442", "442", "Ammonium Phosphatides"),
                           ("e445", "445", "Glycerol Esters of Wood Rosin"),
                           ("e475", "475", "Polyglycerol Esters of Fatty Acids"),
                           ("e477", "477", "Propylene Glycol Esters"),
                           ("e492", "492", "Sorbitan Tristearate")]:
    _add(_a(_code, _ins, _name, "emulsifier", 1, LIMITED, nova_cosmetic=True,
            note=_EMULSIFIER_NOTE, sources=_EMULSIFIER_SRC))

_add(_a("e385", "385", "Calcium Disodium EDTA", "sequestrant", 1, LIMITED,
        note="A chelating agent with a low ADI (2.5 mg/kg bw). Poorly absorbed, "
             "and the concern is mineral binding at high intakes rather than "
             "toxicity.",
        sources=("EFSA Journal 2018;16(6):5299",)))
_add(_a("e923", "923", "Ammonium Persulphate", "flour treatment agent", 1, LIMITED,
        note="A flour oxidiser that is not permitted in the EU.",
        sources=("Codex CXG 36-1989",)))
_add(_a("e1520", "1520", "Propylene Glycol", "humectant", 1, LIMITED,
        note="JECFA ADI 25 mg/kg bw, with no concern at food-use levels. It is a "
             "different chemical from ethylene glycol.",
        sources=("JECFA ADI 0-25 mg/kg bw",)))

# Bare `e150` with no class letter: could be any caramel including the ammonia
# processes, so it takes the cautious middle value rather than zero.
_add(_a("e150", "150", "Caramel Colour (class unspecified)", "colour", 1, LIMITED,
        nova_cosmetic=True,
        note="The label does not say which of the four caramel classes was used. "
             "Classes III and IV contain 4-methylimidazole; classes I and II do "
             "not. Scored cautiously in the middle.",
        sources=("EFSA Journal 2011;9(3):2004",)))

# Potassium chloride is a salt SUBSTITUTE - a sodium-reduction tool, not a risk.
_add(_a("e508", "508", "Potassium Chloride", "salt substitute", 0, NONE,
        note="Used to replace part of the sodium in a product. WHO supports "
             "potassium-based salt substitution as a blood-pressure measure. "
             "Caution applies only to people with advanced kidney disease.",
        sources=("WHO sodium reduction guidance",)))

# Modified starches: no toxicological concern, but genuine NOVA markers.
for _code, _ins, _name in [("e1410", "1410", "Monostarch Phosphate"),
                           ("e1412", "1412", "Distarch Phosphate"),
                           ("e1414", "1414", "Acetylated Distarch Phosphate"),
                           ("e1420", "1420", "Acetylated Starch"),
                           ("e1450", "1450", "Starch Sodium Octenyl Succinate"),
                           ("e1451", "1451", "Acetylated Oxidised Starch"),
                           ("e14xx", "14xx", "Modified Starch (unspecified)")]:
    _add(_a(_code, _ins, _name, "modified starch", 0, NONE,
            note="A chemically modified starch. No safety concern, but it is one "
                 "of the ingredients never found in a home kitchen, so it counts "
                 "towards the ultra-processing assessment."))

# Enzymes, gases, waxes, mineral salts, natural colours, antioxidants: benign.
for _code, _ins, _name, _cls in [
    ("e101", "101", "Riboflavin (Vitamin B2)", "colour"),
    ("e141", "141", "Copper Chlorophyllins", "colour"),
    ("e160f", "160f", "Beta-apo-8-carotenal Ester", "colour"),
    ("e234", "234", "Nisin", "preservative"),
    ("e242", "242", "Dimethyl Dicarbonate", "preservative"),
    ("e290", "290", "Carbon Dioxide", "carbonating agent"),
    ("e304", "304", "Ascorbyl Palmitate", "antioxidant"),
    ("e307", "307", "Alpha-Tocopherol", "antioxidant"),
    ("e307b", "307b", "Tocopherol Concentrate", "antioxidant"),
    ("e316", "316", "Sodium Erythorbate", "antioxidant"),
    ("e334", "334", "Tartaric Acid", "acidity regulator"),
    ("e335", "335", "Sodium Tartrate", "acidity regulator"),
    ("e337", "337", "Potassium Sodium Tartrate", "acidity regulator"),
    ("e386", "386", "Disodium EDTA", "sequestrant"),
    ("e392", "392", "Rosemary Extract", "antioxidant"),
    ("e406", "406", "Agar", "gelling agent"),
    ("e407a", "407a", "Processed Eucheuma Seaweed", "thickener"),
    ("e413", "413", "Tragacanth", "thickener"),
    ("e418", "418", "Gellan Gum", "gelling agent"),
    ("e422", "422", "Glycerol", "humectant"),
    ("e425", "425", "Konjac", "thickener"),
    ("e509", "509", "Calcium Chloride", "firming agent"),
    ("e510", "510", "Ammonium Chloride", "flour treatment agent"),
    ("e516", "516", "Calcium Sulphate", "firming agent"),
    ("e524", "524", "Sodium Hydroxide", "acidity regulator"),
    ("e525", "525", "Potassium Hydroxide", "acidity regulator"),
    ("e536", "536", "Potassium Ferrocyanide", "anticaking agent"),
    ("e900", "900", "Polydimethylsiloxane", "antifoaming agent"),
    ("e900a", "900a", "Polydimethylsiloxane", "antifoaming agent"),
    ("e903", "903", "Carnauba Wax", "glazing agent"),
    ("e941", "941", "Nitrogen", "packaging gas"),
    ("e1102", "1102", "Glucose Oxidase", "enzyme"),
    ("e1104", "1104", "Lipase", "enzyme"),
    ("e1105", "1105", "Lysozyme", "preservative"),
]:
    _add(_a(_code, _ins, _name, _cls, 0, NONE,
            note="No safety concern at permitted levels."))

# The highest INS number in the Codex system is 1521. Anything above that, or
# below 100, is not a real additive code - it is a label typo, an OCR error, or a
# misread quantity. Distinguishing this from "a real additive we have not
# catalogued" matters: the first is a data-quality signal, the second is not.
INS_MIN, INS_MAX = 100, 1525


# --------------------------------------------------------------------------- #
# combination rules
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CombinationRule:
    key: str
    requires: tuple[frozenset[str], ...]
    penalty: int
    evidence: str
    note: str
    sources: tuple[str, ...] = field(default_factory=tuple)


COMBINATION_RULES: tuple[CombinationRule, ...] = (
    CombinationRule(
        key="benzoate_plus_ascorbate",
        requires=(frozenset({"e210", "e211", "e212", "e213"}),
                  frozenset({"e300", "e301"})),
        penalty=2,
        evidence=LIMITED,
        note="This product contains both a benzoate preservative and added "
             "vitamin C. The two can react to form small amounts of benzene, "
             "faster when the product is warm or in sunlight. Surveys found "
             "almost all drinks below the drinking-water benchmark, so the risk "
             "is small, but the combination is avoidable and manufacturers have "
             "reformulated away from it.",
        sources=("FDA CFSAN benzene in beverages Q&A",),
    ),
    CombinationRule(
        key="southampton_plus_benzoate",
        requires=(frozenset({"e102", "e104", "e110", "e122", "e124", "e129"}),
                  frozenset({"e210", "e211", "e212", "e213"})),
        penalty=2,
        evidence=MODERATE,
        note="This is the exact combination tested in the Southampton trial - a "
             "warning-labelled colour together with sodium benzoate - which is "
             "what produced the measured increase in hyperactivity in children.",
        sources=("McCann et al., Lancet 2007;370:1560-67",),
    ),
)


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #


@dataclass
class AdditiveAssessment:
    known: list[Additive]
    uncatalogued_codes: list[str]
    invalid_codes: list[str]
    combinations: list[CombinationRule]
    raw_penalty: float
    risk_0_100: float
    cosmetic_marker_count: int
    worst: Additive | None

    @property
    def flagged(self) -> list[Additive]:
        """Additives that actually carry a penalty, worst first."""
        return sorted((a for a in self.known if a.penalty > 0),
                      key=lambda a: -a.penalty)

    @property
    def cleared(self) -> list[Additive]:
        """Additives present but explicitly not penalised - shown to the user so
        the app corrects misconceptions instead of silently ignoring them."""
        return [a for a in self.known if a.penalty == 0 and a.evidence == NONE]


def lookup(ecode: str) -> Additive | None:
    """Resolve an additive code, falling back to its parent class.

    Labels print sub-parts - INS 500(ii), INS 471, INS 150d - and the register is
    keyed on the most specific form available. `e500ii` falls back to `e500`, and
    `e472e` is tried before `e472`.
    """
    code = ecode.lower().strip()
    if code in REGISTER:
        return REGISTER[code]
    # Strip a trailing roman-numeral sub-part: e500ii -> e500.
    import re
    stripped = re.sub(r"(i+v?|iv|v?i*)$", "", code)
    if stripped != code and stripped in REGISTER:
        return REGISTER[stripped]
    # Strip a trailing letter: e472e -> e472.
    if len(code) > 2 and code[-1].isalpha() and code[:-1] in REGISTER:
        return REGISTER[code[:-1]]
    return None


def additive_risk(ecodes: list[str]) -> AdditiveAssessment:
    """Turn a list of additive codes into a 0-100 risk sub-score.

    Aggregation is deliberately non-linear. A plain sum would let a product with
    eight harmless gums and starches score worse than one carrying a single
    Southampton colour, which inverts the evidence. Instead the worst additive
    dominates and each additional one contributes progressively less:

        raw = max(penalty) + 0.5 * (second) + 0.33 * (third) + 0.25 * (fourth) ...

    then combination-rule penalties are added at full weight, since those encode
    a specific documented interaction rather than a repeated generic concern.
    """
    import re as _re

    codes = sorted({c.lower() for c in ecodes if c})
    known: list[Additive] = []
    uncatalogued: list[str] = []
    invalid: list[str] = []

    for code in codes:
        found = lookup(code)
        if found:
            known.append(found)
            continue
        digits = _re.match(r"e(\d{1,4})", code)
        if digits and INS_MIN <= int(digits.group(1)) <= INS_MAX:
            # A real permitted additive we simply have no risk entry for. Counted
            # and shown, but not penalised - inventing a penalty for an
            # uncatalogued substance would be exactly the unevidenced guessing
            # this module exists to avoid.
            uncatalogued.append(code)
        else:
            invalid.append(code)

    penalties = sorted((a.penalty for a in known if a.penalty > 0), reverse=True)
    raw = 0.0
    for i, p in enumerate(penalties):
        raw += p / (i + 1)

    present = {a.ecode for a in known}
    # Combination rules must see the codes as printed too, so a label carrying
    # e500ii still matches a rule written against e500.
    present |= {a.ecode for a in known}
    fired: list[CombinationRule] = []
    for rule in COMBINATION_RULES:
        if all(present & group for group in rule.requires):
            fired.append(rule)
            raw += rule.penalty

    # A code outside the Codex numbering range is a label typo or an OCR error -
    # real examples from this corpus include "INS 3221" (for 322(i)) and
    # "INS 1700". That is a data-quality signal, so it costs a little to stop a
    # garbled label from reading as clean, but it is never treated as a hazard.
    # Codes that ARE valid but uncatalogued cost nothing.
    raw += 0.5 * len(invalid)

    # Map to 0-100. A raw of 12 or more is treated as the practical ceiling: that
    # is a Southampton colour (6) plus both combination rules (4) plus a
    # substantial second additive, which is about as bad as Indian labels get.
    risk = min(100.0, 100.0 * raw / 12.0)

    return AdditiveAssessment(
        known=known,
        uncatalogued_codes=uncatalogued,
        invalid_codes=invalid,
        combinations=fired,
        raw_penalty=round(raw, 2),
        risk_0_100=round(risk, 1),
        cosmetic_marker_count=sum(1 for a in known if a.nova_cosmetic),
        worst=max(known, key=lambda a: a.penalty) if known else None,
    )


def register_summary() -> dict:
    """Counts by evidence grade - used in the app's methodology page."""
    out: dict[str, int] = {}
    for a in REGISTER.values():
        out[a.evidence] = out.get(a.evidence, 0) + 1
    return {"total": len(REGISTER), "by_evidence": out,
            "zero_penalty": sum(1 for a in REGISTER.values() if a.penalty == 0),
            "combination_rules": len(COMBINATION_RULES)}
