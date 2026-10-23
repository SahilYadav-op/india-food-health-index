# India Food Health Index

Scores packaged food sold in India from 1 to 10, using the nutrition panel and ingredient list printed on the back of the pack.

[![Live](https://img.shields.io/badge/●-Live-brightgreen?style=for-the-badge)](https://india-packaged-food-analysis.streamlit.app/) [Open the app](https://india-packaged-food-analysis.streamlit.app/)

![Python 3.11](https://img.shields.io/badge/python-3.11-blue) ![Data: ODbL](https://img.shields.io/badge/data-ODbL%201.0-lightgrey)

## Why I made this

The front of an Indian food pack says things like "no added preservatives", "baked, not fried" or "made with real fruit". Those are marketing claims. They aren't checked the way the nutrition table is, and there's no standard way to compare one brand's claim with another's. India also has no front-of-pack warning label like Chile or Mexico do.

The parts of a pack a company has to print accurately are the nutrition table and the ingredient list, and they're in tiny type on the back. This project reads those two things and turns them into one score you can compare across products, with the reasons shown.

## What you can do in the app

- Search a product by name, brand or barcode and see its score and how it got there.
- See better options in the same category. A suggestion has to score at least 2 points higher and can't have more sugar, saturated fat or sodium than the product you looked up.
- Compare up to three products side by side.
- Browse everything, or see the best and worst in each category.

For example, Britannia NutriChoice Digestive gets 2/10. Per 100 g it has 481 kcal, 10.4 g saturated fat, 13.1 g sugar and 0.92 g salt, and it goes over four of the WHO's limits for biscuits. Its 7.3 g of fibre helps, but not enough to make up for the rest.

## How the score works

Four parts, each taken from a published source:

| Part | Weight | Source |
|---|---|---|
| Nutrients | 50% | Nutri-Score 2023 algorithm, applied to the nutrition panel |
| Processing | 25% | NOVA classification, worked out from the ingredient list |
| Additives | 15% | A table of 173 additives graded by strength of evidence (EFSA, JECFA, IARC) |
| WHO screen | 10% | WHO nutrient profile model for South-East Asia, pass or fail per nutrient |

Going over the WHO's limits also lowers the highest score a product can get: 7 for one limit, 5 for two, 4 for three or more. Ultra-processed products top out at 8, and Nutri-Score E products at 4. This is so a product with a lot of salt can't make up for it with some added protein, which is a known weakness of star ratings.

The app's "How it works" page has the full list of caps and the 1 to 10 scale.

## Where the data comes from

Product data comes from [Open Food Facts](https://world.openfoodfacts.org), an open database that anyone can add to. I pulled the India products that have an energy value through their public API (about 3,400, 3,386 after cleaning) and cached every response so nothing is fetched twice.

I didn't scrape any shopping sites. Amazon.in's robots.txt disallows it and BigBasket blocks requests outright, so I left them alone.

Label data has a lot of mistakes, so the pipeline fixes what it can. The most common one is sodium entered in milligrams where grams were expected. Dropping those records would have removed Marie Gold, Good Day and Kissan Ketchup, so the value is corrected instead. The Data quality page in the app lists what was found.

## How well it matches

I checked the results against Open Food Facts' own calculations for the same products:

- Nutri-Score grade: 90.8% exact match, 98.1% within one grade (1,730 products)
- NOVA group: 85.3% match (1,895 products)
- Additive codes: about 81% of the ones Open Food Facts finds (2,053 products)

Open Food Facts is crowd-sourced too, so this shows the score agrees with another implementation, not that either one is correct. Checking a few hundred labels by hand is the next thing to do.

## Limits

- Only about a fifth of Open Food Facts' India products have both a full nutrition panel and a full ingredient list. 38.5% of the products here get no score for that reason, or because they're supplements, spices, infant food, cooking ingredients or alcohol.
- Everything is per 100 g, so a small packet and a large one score the same.
- The weights, the points taken off per WHO limit, the band edges and the cap values are my own choices. WHO's model is pass or fail and doesn't say how bad a breach is, so turning it into a number needed a judgement call.
- Not medical advice, and no single food is good or bad on its own.

## Choices that might surprise you

- MSG isn't penalised. The scare started with a 1968 letter and blinded trials haven't reproduced the symptoms. Saccharin and food-grade carrageenan get no penalty either.
- Palm oil has no penalty of its own. Its effect on cholesterol comes from its saturated fat, which is already counted.
- Nothing is called toxic. The lowest rating says "harmful as a regular habit", because the evidence is about long-term eating patterns, not a single packet.

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

Tests (47 of them, no pytest needed):

```bash
python tests/test_scoring.py
```

## Project layout

```
app.py                  the Streamlit app
data/                   cleaned products and a data quality report
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
  suggest.py            better options in the same category
tests/test_scoring.py
```

Built with Python, pandas, pyarrow and Streamlit. There is no machine learning in the scoring. Every score comes from published thresholds, so you can trace it by hand.

## Author

Sahil Yadav · [GitHub](https://github.com/SahilYadav-op) · [LinkedIn](https://www.linkedin.com/in/sahilgod01/)

Product data © Open Food Facts contributors, available under the [Open Database License](https://opendatacommons.org/licenses/odbl/1-0/). Anything built from it has to credit Open Food Facts and stay under the same licence.
