"""
Harvest packaged-food products sold in India from Open Food Facts.

Two paths, both implemented:

  api   (default)  Enumerate India barcodes via the search-a-licious index, then
                   fetch each product from the v2 product API. Targeted and small,
                   but one HTTP request per product. Use for <10k products.

  dump             Stream the official CSV export (~1.3 GB gzipped, ~4M rows) and
                   keep only rows whose countries_tags contain en:india. No API
                   pressure, no rate limit, complete. Use for full rebuilds.

Why both: the search index does NOT contain ingredients_text or additives_tags
(verified 2026-07-26), so barcode enumeration alone is not enough - the ingredient
list, which is half of this project, has to come from the product API or the dump.

Every response is cached under data/raw/products/ as one JSON per barcode, so a
re-run costs zero requests. Delete the cache to force a refresh.

Licence: Open Food Facts data is ODbL 1.0. Any redistribution of this dataset or a
derived database must credit Open Food Facts and stay under ODbL. See README.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PRODUCT_CACHE = RAW / "products"

SEARCH_URL = "https://search.openfoodfacts.org/search"
PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}"
DUMP_URL = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz"

# Open Food Facts asks every client to identify itself. An anonymous or spoofed
# User-Agent is the one thing that reliably gets a project blocked.
USER_AGENT = (
    "IndiaFoodHealthIndex/0.1 (student research project; "
    "https://github.com/SahilYadav-op/india-food-health-index; sahilyadav.sy2004@gmail.com)"
)

# Open Food Facts' documented limits are 15 requests a minute per IP for product
# reads and 10 a minute for search. These delays keep under both. (An earlier
# version waited 0.75 s between product reads, about 80 a minute, which is over
# the limit and produced a long run of HTTP 429 responses.) For anything bigger
# than a few thousand products, use `--source dump` instead of the API.
PRODUCT_DELAY_S = 4.5  # about 13 requests a minute
SEARCH_DELAY_S = 6.5  # about 9 requests a minute

# Fields we ask the product API for. Keep this list tight: OFF documents that
# requesting fewer fields is materially cheaper on their side.
PRODUCT_FIELDS = ",".join(
    [
        "code",
        "product_name",
        "generic_name",
        "brands",
        "brands_tags",
        "categories",
        "categories_tags",
        "countries_tags",
        "quantity",
        "serving_size",
        "serving_quantity",
        "ingredients_text",
        "ingredients_text_en",
        "ingredients_tags",
        "ingredients_analysis_tags",
        "ingredients_n",
        "additives_tags",
        "additives_n",
        "allergens_tags",
        "traces_tags",
        "labels_tags",
        "nova_group",
        "nutriscore_grade",
        "nutriscore_score",
        "nutriscore_data",
        "nutrient_levels",
        "nutriments",
        "nutrition_data_per",
        "no_nutrition_data",
        "image_front_url",
        "image_ingredients_url",
        "image_nutrition_url",
        "completeness",
        "states_tags",
        "data_quality_errors_tags",
        "last_modified_t",
        "created_t",
    ]
)

# Columns kept from the CSV dump. The dump has ~200 columns; these are the ones
# that map onto our schema.
DUMP_COLUMNS = [
    "code",
    "product_name",
    "generic_name",
    "brands",
    "categories_tags",
    "countries_tags",
    "quantity",
    "serving_size",
    "ingredients_text",
    "additives_n",
    "additives_tags",
    "allergens",
    "labels_tags",
    "nova_group",
    "nutriscore_grade",
    "nutriscore_score",
    "image_url",
    "image_ingredients_url",
    "image_nutrition_url",
    "last_modified_t",
    "energy-kcal_100g",
    "energy_100g",
    "fat_100g",
    "saturated-fat_100g",
    "trans-fat_100g",
    "cholesterol_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "added-sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "sodium_100g",
    "fruits-vegetables-nuts-estimate-from-ingredients_100g",
]

log = logging.getLogger("harvest")


# --------------------------------------------------------------------------- #
# session
# --------------------------------------------------------------------------- #


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def get_json(session: requests.Session, url: str, *, params: dict | None = None,
             attempts: int = 4, timeout: int = 60) -> dict | None:
    """GET with exponential backoff. Returns None if the resource is unavailable.

    OFF returns 503 with an HTML maintenance page under load, so a JSON decode
    failure is treated the same as a 5xx: retry, then give up.
    """
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            r = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            log.warning("request failed (%s/%s) %s: %s", attempt, attempts, url, exc)
        else:
            if r.status_code == 404:
                return None
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", delay * 4))
                log.warning("rate limited, sleeping %.0fs", wait)
                time.sleep(wait)
                continue
            if r.ok:
                try:
                    return r.json()
                except ValueError:
                    log.warning("non-JSON body (%s/%s) from %s", attempt, attempts, url)
            else:
                log.warning("HTTP %s (%s/%s) from %s", r.status_code, attempt, attempts, url)
        time.sleep(delay)
        delay *= 2
    return None


# --------------------------------------------------------------------------- #
# stage 1 - enumerate India barcodes
# --------------------------------------------------------------------------- #


@dataclass
class SearchStats:
    pages: int = 0
    codes: int = 0
    reported_count: int | None = None


def enumerate_india_codes(
    session: requests.Session,
    *,
    max_products: int,
    require_energy: bool = True,
) -> tuple[list[str], SearchStats]:
    """Page the search index for products whose countries_tags include en:india.

    `require_energy` filters to products that carry at least an energy value.
    Without it roughly half the India set is a bare barcode with a photo, which
    cannot be scored and only inflates the corpus.

    Sorted by `code` so paging is stable across runs - sorting by relevance makes
    deep pages return overlapping results.
    """
    query = 'countries_tags:"en:india"'
    if require_energy:
        query += " AND nutriments.energy-kcal_100g:[0 TO 2000]"

    codes: list[str] = []
    seen: set[str] = set()
    stats = SearchStats()
    page = 1
    page_size = 100

    while len(codes) < max_products:
        payload = get_json(
            session,
            SEARCH_URL,
            params={
                "q": query,
                "page": page,
                "page_size": page_size,
                "sort_by": "code",
                "fields": "code",
            },
        )
        if not payload:
            log.error("search failed on page %s, stopping enumeration", page)
            break

        stats.pages += 1
        if stats.reported_count is None:
            stats.reported_count = payload.get("count")
            log.info("search index reports %s India products matching filter",
                     stats.reported_count)

        hits = payload.get("hits") or []
        if not hits:
            break

        for h in hits:
            code = str(h.get("code") or "").strip()
            if code and code not in seen:
                seen.add(code)
                codes.append(code)

        log.info("page %s -> %s codes (total %s)", page, len(hits), len(codes))

        if len(hits) < page_size or page >= (payload.get("page_count") or page):
            break
        page += 1
        time.sleep(SEARCH_DELAY_S)

    stats.codes = len(codes)
    return codes[:max_products], stats


# --------------------------------------------------------------------------- #
# stage 2 - fetch full products
# --------------------------------------------------------------------------- #


def cache_path(code: str) -> Path:
    # Shard by the last two digits so no directory holds 50k files.
    return PRODUCT_CACHE / code[-2:] / f"{code}.json"


def fetch_products(session: requests.Session, codes: Iterable[str]) -> Iterator[dict]:
    """Yield full product dicts, hitting the network only for uncached barcodes."""
    codes = list(codes)
    fetched = cached = missing = 0

    for i, code in enumerate(codes, 1):
        path = cache_path(code)
        if path.exists():
            try:
                yield json.loads(path.read_text(encoding="utf-8"))
                cached += 1
                continue
            except (OSError, ValueError):
                log.warning("corrupt cache for %s, refetching", code)

        payload = get_json(
            session, PRODUCT_URL.format(code=code), params={"fields": PRODUCT_FIELDS}
        )
        time.sleep(PRODUCT_DELAY_S)

        if not payload or payload.get("status") != 1 or not payload.get("product"):
            missing += 1
            continue

        product = payload["product"]
        product.setdefault("code", code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(product, ensure_ascii=False), encoding="utf-8")
        fetched += 1
        yield product

        if i % 100 == 0:
            log.info("progress %s/%s (fetched %s, cached %s, missing %s)",
                     i, len(codes), fetched, cached, missing)

    log.info("fetch done: %s from network, %s from cache, %s unavailable",
             fetched, cached, missing)


# --------------------------------------------------------------------------- #
# dump path
# --------------------------------------------------------------------------- #


def harvest_from_dump(dest: Path, *, url: str = DUMP_URL, max_products: int | None = None) -> int:
    """Stream the full OFF CSV export and keep only India rows.

    Never materialises the 1.3 GB archive on disk - it is decompressed and
    filtered as it arrives. Expect this to take 20-60 minutes on a home
    connection and to yield far more India rows than the API path, because the
    dump includes products the search index has not reindexed.
    """
    session = make_session()
    log.info("streaming dump from %s", url)
    kept = 0

    with session.get(url, stream=True, timeout=(30, 300)) as r:
        r.raise_for_status()
        gz = gzip.GzipFile(fileobj=r.raw)
        text = io.TextIOWrapper(gz, encoding="utf-8", errors="replace", newline="")
        reader = csv.DictReader(text, delimiter="\t")

        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=DUMP_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for n, row in enumerate(reader, 1):
                if "en:india" in (row.get("countries_tags") or ""):
                    writer.writerow({k: row.get(k, "") for k in DUMP_COLUMNS})
                    kept += 1
                    if max_products and kept >= max_products:
                        break
                if n % 250_000 == 0:
                    log.info("scanned %s rows, kept %s India rows", f"{n:,}", f"{kept:,}")

    log.info("dump harvest complete: %s India rows -> %s", f"{kept:,}", dest)
    return kept


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=("api", "dump"), default="api")
    p.add_argument("--max-products", type=int, default=4000)
    p.add_argument("--all-products", action="store_true",
                   help="do not require an energy value (much larger, mostly unscoreable)")
    p.add_argument("--out", type=Path, default=RAW / "off_india_raw.jsonl")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    RAW.mkdir(parents=True, exist_ok=True)

    if args.source == "dump":
        harvest_from_dump(RAW / "off_india_dump.csv", max_products=args.max_products)
        return 0

    session = make_session()

    log.info("stage 1: enumerating India barcodes")
    codes, stats = enumerate_india_codes(
        session, max_products=args.max_products, require_energy=not args.all_products
    )
    (RAW / "india_codes.json").write_text(json.dumps(codes), encoding="utf-8")
    log.info("stage 1 done: %s barcodes over %s pages", stats.codes, stats.pages)

    if not codes:
        log.error("no barcodes enumerated - is the search index reachable?")
        return 1

    log.info("stage 2: fetching full product records (~%.0f min at %s req/s)",
             len(codes) * PRODUCT_DELAY_S / 60, round(1 / PRODUCT_DELAY_S, 1))
    written = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for product in fetch_products(session, codes):
            fh.write(json.dumps(product, ensure_ascii=False) + "\n")
            written += 1

    log.info("stage 2 done: %s products -> %s", written, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
