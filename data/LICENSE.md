# Licence for the files in this folder

`products.parquet`, `quarantine.parquet` and `validation_report.json` are a derivative database built from Open Food Facts.

Contains information from Open Food Facts (https://world.openfoodfacts.org), which is made available under the Open Database License (ODbL) 1.0: https://opendatacommons.org/licenses/odbl/1-0/

The individual contents of the Open Food Facts database are made available under the Database Contents License 1.0: https://opendatacommons.org/licenses/dbcl/1-0/

## What was changed

- Records were limited to products listed for India that have an energy value.
- Unit mistakes were corrected: sodium and salt entered in milligrams instead of grams, and energy entered in kilojoules instead of kilocalories.
- A single impossible value (for example saturated fat above total fat) was blanked.
- Columns were added: parsed ingredient lists, additive codes, data quality flags and the repairs applied.
- Records that could not be repaired are kept in `quarantine.parquet`.

## Terms

This derivative database is shared under the ODbL 1.0. If you use or pass it on, credit Open Food Facts, say what you changed, and keep the same licence.

The ODbL covers the data only. It does not cover the code in this repository, and nothing here is endorsed by Open Food Facts or its contributors.
