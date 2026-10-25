# India Food Health Index

Scores packaged food listed for India from 1 to 10, using the nutrition panel and ingredient list printed on the back of the pack.

[![Live](https://img.shields.io/badge/●-Live-brightgreen?style=for-the-badge)](https://india-packaged-food-analysis.streamlit.app/) [Open the app](https://india-packaged-food-analysis.streamlit.app/)

![Python 3.11](https://img.shields.io/badge/python-3.11-blue) ![Data: ODbL](https://img.shields.io/badge/data-ODbL%201.0-lightgrey)

## Why I made this

The front of a food pack says things like "no added preservatives", "baked, not fried" or "made with real fruit". In India these claims are regulated: FSSAI's 2018 claims rules set conditions on claims such as "no added sugar" and restrict words like "natural" and "pure". But a claim can meet the rules and still tell you very little about how one product compares with another. As of October 2026 India has no mandatory front-of-pack warning label like Chile's or Mexico's. FSSAI has proposed one and the Supreme Court is still considering it.

The nutrition table and the ingredient list are on every pack, in small type on the back. This project reads those two things and turns them into one score you can compare across products, with the reasons shown.

## What you can do in the app

- Search a product by name, brand or barcode and see its score and how it got there.
- See higher-scoring products in the same category. A suggestion has to score at least 2 points higher and can't have more sugar, saturated fat or sodium than the product you looked up.
- Compare up to three products side by side.
- Type in the numbers from a pack yourself ("Check a label") to score a product that isn't in the dataset or has missing data. A box left empty counts as unknown, never as zero.
- See how much of the daily limits for sodium, added sugar, saturated fat, trans fat and total fat a portion uses up. The limits come from WHO guidance and match the reference values FSSAI prints on labels.
- Browse everything, or see the highest and lowest scores in each category.

Every product page links to its source record on Open Food Facts and shows when that record was last edited, so you can check the numbers or fix them.

The daily limits are shown next to the score but aren't part of it. They only make sense for a portion, and only about half the products have a serving size on record. The score already uses WHO's per-100 g limits for each category, so adding the daily limits would count the same sodium and sugar twice.

## How the score works

Four parts, each taken from a published source:

| Part | Weight | Source |
|---|---|---|
| Nutrients | 50% | Nutri-Score 2023 algorithm, applied to the nutrition panel |
| Processing | 25% | NOVA classification, worked out from the ingredient list |
| Additives | 15% | A table of 173 additives graded by strength of evidence (EFSA, JECFA, IARC) |
| WHO screen | 10% | WHO nutrient profile model for South-East Asia, a limit per nutrient for each category |

Going over WHO's limits also lowers the highest score a product can get: 7 for one limit, 5 for two, 4 for three or more. Ultra-processed products top out at 8, and Nutri-Score E products at 4. This is so a product with a lot of salt can't make up for it with some added protein, which is a known weakness of star ratings.

The scale describes the score, not the product. The ratings run from "Excellent" at 10 to "Lowest" at 1, and nothing is called harmful, unhealthy or toxic. The score comes from label data and published methods, and says nothing about whether a product is safe.

The app's "How it works" page has the full list of caps and the 1 to 10 scale.

## Where the data comes from

Product data comes from [Open Food Facts](https://world.openfoodfacts.org), an open database that anyone can edit. I pulled the products listed for India that have an energy value (about 3,400, and 3,386 after cleaning) through their public API and cached every response. The harvester waits long enough between requests to stay inside their published limit of 15 product reads a minute.

"Listed for India" isn't the same as "sold in India". Some records are labels from other countries that carry an India tag.

I didn't scrape any shopping sites. Amazon.in's robots.txt disallows it and BigBasket blocks requests outright, so I left them alone.

Label data has a lot of mistakes, so the pipeline fixes what it can. The most common one is sodium entered in milligrams where grams were expected. Dropping those records would have removed a lot of well-known products, so the value is corrected instead. Other values can't be fixed. A biscuit or a sauce listed with 0 sodium is almost always a blank field, and scoring it would count a blank as the best possible result, so those products get no score. The Data quality page in the app lists what was found.

## How well it matches

I checked the results against Open Food Facts' own calculations for the same products:

- Nutri-Score grade: 89.7% exact match, 97.7% within one grade (1,730 products)
- NOVA group: 85.2% match (1,895 products)

Open Food Facts is crowd-sourced too, so this shows the score agrees with another implementation, not that either one is correct. Checking a few hundred labels by hand is the next thing to do.

The Nutri-Score figure is about a point lower than an earlier version of this project. The difference is oats and similar cereals. Open Food Facts tags every cereal grain as "seeds" and grades them with the nuts-and-seeds version of the algorithm. The Nutri-Score rules define that version by nuts and seed products, not cereals, so I grade oats as ordinary food and accept the mismatch.

## Limits

- Only about a fifth of Open Food Facts' India products have both a full nutrition panel and a full ingredient list. 40.7% of the products here get no score, because the panel is incomplete or doesn't add up, or because they're supplements, spices, infant food, cooking ingredients or alcohol.
- WHO's model has no limits for some kinds of products, so the WHO part is left out for 12% of the scored products and the other three parts are reweighted.
- Everything is per 100 g, so a small packet and a large one score the same.
- The weights, the points taken off per WHO limit, the band edges and the cap values are my own choices. WHO's model is pass or fail and doesn't say how bad a breach is, so turning it into a number needed a judgement call.
- Some products are filed in the wrong category because their source tags are wrong.

## Choices that might surprise you

- MSG isn't penalised. The scare started with a 1968 letter and blinded trials haven't reproduced the symptoms. Saccharin and food-grade carrageenan get no penalty either.
- Palm oil has no penalty of its own. Its effect on cholesterol comes from its saturated fat, which is already counted.

## Disclaimer and corrections

This is a student project. A score is an automated calculation from label data. It is not medical or dietary advice, not a safety or quality rating, and not a statement of fact about any company or product. The data can be wrong or out of date, so check the pack. Product and brand names are used only to identify products and belong to their owners. This project isn't affiliated with or endorsed by any brand, by Open Food Facts, FSSAI, WHO or anyone else mentioned. It is provided as it is, without warranty.

If you own a brand or you spot a mistake, [open an issue](https://github.com/SahilYadav-op/india-food-health-index/issues) with the barcode and what is wrong. The app has the same text on its About page.

## Run it locally

```bash
git clone https://github.com/SahilYadav-op/india-food-health-index.git
cd india-food-health-index
pip install -r requirements.txt
streamlit run app.py
```

The scored dataset is already in `data/`. To rebuild it from Open Food Facts:

```bash
python pipeline/harvest_off.py --max-products 4000
python pipeline/build_dataset.py --report
```

At the API's rate limit that takes hours for a few thousand products. For a bigger pull, use the bulk export instead with `--source dump`.

Tests (74 of them, no pytest needed):

```bash
python tests/test_scoring.py
```

## Project layout

```
app.py                  the Streamlit app
data/                   cleaned products, a data quality report and the data licence
pipeline/
  harvest_off.py        pulls products from Open Food Facts
  build_dataset.py      fixes and checks the records
scoring/
  ingredients.py        reads Indian ingredient lists, including INS codes
  categories.py         sorts products into categories
  nutrients.py          Nutri-Score 2023 and the WHO screen
  processing.py         NOVA group
  additives.py          the additive table
  index.py              combines the four parts into the 1 to 10 score
  suggest.py            higher-scoring products in the same category
  limits.py             daily limits from WHO and FSSAI, and how much a portion uses
  custom.py             turns numbers typed from a pack into a row to score
tests/test_scoring.py
```

Built with Python, pandas, pyarrow and Streamlit. There is no machine learning in the scoring. Every score comes from published thresholds, so you can trace it by hand.

## Author

Sahil Yadav · [GitHub](https://github.com/SahilYadav-op) · [LinkedIn](https://www.linkedin.com/in/sahilgod01/)

## Licence

The code is open source under the [MIT licence](LICENSE). You can use it, copy it and change it, including for your own version of this project.

The cleaned data in `data/` is separate. It is a derivative of Open Food Facts and is shared under the [Open Database License](https://opendatacommons.org/licenses/odbl/1-0/). See [data/LICENSE.md](data/LICENSE.md). Contains information from Open Food Facts. Anything built from the data has to credit Open Food Facts and stay under the same licence.
