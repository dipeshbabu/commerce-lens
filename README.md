# CommerceLens

Open-source product, catalog, and price intelligence extraction for developers.

CommerceLens turns messy e-commerce pages into structured product, listing, and price-history data using schema.org JSON-LD parsing, OpenGraph metadata, DOM heuristics, confidence scoring, catalog crawling, optional browser rendering, SQLite snapshots, change detection, and a clean Python SDK / CLI / FastAPI interface.

> Goal: commerce-ready product data, not just raw HTML.

## Why CommerceLens?

Most scraping tools return raw HTML, Markdown, or brittle selector outputs. CommerceLens is designed around normalized commerce objects: product name, brand, price, currency, availability, images, description, SKU, ratings, review counts, canonical URL, listing product cards, confidence scores, extraction provenance, price history, and product-level change events.

CommerceLens is currently in early v0.4 development. The current release focuses on product page extraction, listing/category extraction, basic catalog crawling, JSONL/CSV export, optional Playwright rendering for JavaScript-heavy pages, and local price intelligence through SQLite-backed product snapshots.

## Features in v0.4

- Product page extraction
- Listing/category page extraction
- Basic catalog crawling by following next-page links
- Optional Playwright browser rendering
- Rendered HTML snapshot saving
- Full-page screenshot saving
- JSON-LD / schema.org Product parsing
- OpenGraph metadata fallback
- DOM heuristic fallback
- Product card extraction
- Pagination discovery
- Price and currency normalization
- Availability normalization
- Image extraction
- Field-level confidence scores
- Source provenance for extracted fields
- SQLite product snapshot storage
- Product identity keys
- Price history lookup
- Price drop detection
- Price increase detection
- Availability change detection
- Back-in-stock detection
- Batch product monitoring
- JSON, JSONL, and CSV export
- Python SDK
- CLI
- FastAPI API
- Lightweight default install; browser support is optional

## Installation

Static extraction and price monitoring:

```bash
pip install -e .
```

Browser rendering support:

```bash
pip install -e ".[browser]"
playwright install chromium
```

Or install from requirements:

```bash
pip install -r requirements.txt
```

## Python SDK

Extract a product page:

```python
from commercelens import extract_product

result = extract_product("https://example.com/products/sample")
print(result.product.name)
print(result.product.price.amount)
print(result.product.availability)
```

Render a JavaScript-heavy product page before extraction:

```python
from commercelens import extract_product

result = extract_product(
    "https://example.com/products/sample",
    render=True,
    screenshot_path="debug/product.png",
    html_snapshot_path="debug/product.html",
)
```

Monitor a product price:

```python
from commercelens import monitor_product

result = monitor_product("https://example.com/products/sample", db_path="prices.db")
print(result.product_key)
print(result.has_change)
print(result.change)
```

Monitor many product URLs:

```python
from commercelens import monitor_products

batch = monitor_products(
    [
        "https://example.com/products/sample",
        "https://example.com/products/another-sample",
    ],
    db_path="prices.db",
)
print(batch.changes)
```

Read price history:

```python
from commercelens import PriceSnapshotStore

store = PriceSnapshotStore("prices.db")
history = store.history("PRODUCT_KEY_FROM_MONITOR_RESULT")
for snapshot in history:
    print(snapshot.captured_at, snapshot.amount, snapshot.currency, snapshot.availability)
```

Extract from local or already-fetched HTML:

```python
from commercelens import extract_product_from_html

html = """<html>...</html>"""
result = extract_product_from_html(html, url="https://example.com/products/sample")
```

Extract a listing/category page:

```python
from commercelens import extract_listing

listing = extract_listing("https://example.com/collections/shoes")
for item in listing.products:
    print(item.name, item.price, item.url)
```

Render a JavaScript-heavy listing page before extraction:

```python
from commercelens import extract_listing

listing = extract_listing(
    "https://example.com/collections/shoes",
    render=True,
    screenshot_path="debug/listing.png",
    html_snapshot_path="debug/listing.html",
)
```

Crawl a catalog by following next-page links:

```python
from commercelens import crawl_catalog

catalog = crawl_catalog("https://example.com/collections/shoes", max_pages=5)
print(catalog.product_count)
```

Render each catalog page during crawl and save debug artifacts:

```python
from commercelens import crawl_catalog

catalog = crawl_catalog(
    "https://example.com/collections/shoes",
    max_pages=5,
    render=True,
    debug_dir="debug/catalog",
)
```

## CLI

Extract from a product URL:

```bash
commercelens product https://example.com/products/sample
```

Render first, then extract:

```bash
commercelens product https://example.com/products/sample \
  --render \
  --screenshot debug/product.png \
  --html-snapshot debug/product.html
```

Save a price snapshot and detect changes:

```bash
commercelens monitor https://example.com/products/sample --db prices.db
```

Run it again later. If the price or availability changed, CommerceLens returns a change object.

Batch monitor many products:

```bash
commercelens monitor-batch examples/products.txt --db prices.db --out monitor_result.json
```

Show price history for a product key:

```bash
commercelens history PRODUCT_KEY_FROM_MONITOR_RESULT --db prices.db
```

Show latest detected changes across tracked products:

```bash
commercelens changes --db prices.db
```

Extract product cards from a listing page:

```bash
commercelens listing https://example.com/collections/shoes
```

Render a listing page and export products:

```bash
commercelens listing https://example.com/collections/shoes \
  --render \
  --format jsonl \
  --out products.jsonl
```

Export listing products as JSONL or CSV:

```bash
commercelens listing https://example.com/collections/shoes --format jsonl --out products.jsonl
commercelens listing https://example.com/collections/shoes --format csv --out products.csv
```

Crawl a catalog:

```bash
commercelens crawl https://example.com/collections/shoes --max-pages 5 --format jsonl --out catalog.jsonl
```

Render each crawled catalog page and save debug artifacts:

```bash
commercelens crawl https://example.com/collections/shoes \
  --max-pages 5 \
  --render \
  --debug-dir debug/catalog \
  --format jsonl \
  --out catalog.jsonl
```

Run the API server:

```bash
commercelens serve --host 0.0.0.0 --port 8000 --reload
```

## FastAPI API

Start the server:

```bash
uvicorn commercelens.api.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Extract a product:

```bash
curl -X POST http://127.0.0.1:8000/v1/extract/product \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/products/sample"}'
```

Render and extract a product:

```bash
curl -X POST http://127.0.0.1:8000/v1/extract/product \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/products/sample", "render": true, "screenshot_path":"debug/product.png", "html_snapshot_path":"debug/product.html"}'
```

Monitor a product:

```bash
curl -X POST http://127.0.0.1:8000/v1/monitor/product \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/products/sample", "db_path":"prices.db"}'
```

Batch monitor products:

```bash
curl -X POST http://127.0.0.1:8000/v1/monitor/batch \
  -H "Content-Type: application/json" \
  -d '{"urls":["https://example.com/products/sample", "https://example.com/products/another-sample"], "db_path":"prices.db"}'
```

Read price history by product key:

```bash
curl -X POST http://127.0.0.1:8000/v1/monitor/history \
  -H "Content-Type: application/json" \
  -d '{"product_key":"PRODUCT_KEY_FROM_MONITOR_RESULT", "db_path":"prices.db"}'
```

Read price history by URL:

```bash
curl -X POST http://127.0.0.1:8000/v1/monitor/history \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/products/sample", "db_path":"prices.db"}'
```

Extract a listing page:

```bash
curl -X POST http://127.0.0.1:8000/v1/extract/listing \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/collections/shoes"}'
```

Render and extract a listing page:

```bash
curl -X POST http://127.0.0.1:8000/v1/extract/listing \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/collections/shoes", "render": true, "screenshot_path":"debug/listing.png", "html_snapshot_path":"debug/listing.html"}'
```

Crawl a catalog:

```bash
curl -X POST http://127.0.0.1:8000/v1/crawl/catalog \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/collections/shoes", "max_pages": 5}'
```

Render crawled catalog pages:

```bash
curl -X POST http://127.0.0.1:8000/v1/crawl/catalog \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/collections/shoes", "max_pages": 5, "render": true, "debug_dir":"debug/catalog"}'
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

To test browser rendering manually:

```bash
pip install -e ".[browser]"
playwright install chromium
commercelens product https://example.com/products/sample --render
```

To test price monitoring locally:

```bash
commercelens monitor https://example.com/products/sample --db prices.db
commercelens history PRODUCT_KEY_FROM_MONITOR_RESULT --db prices.db
commercelens changes --db prices.db
```

## Product roadmap

### v0.1: Product extraction core

- Schema-first product extraction
- JSON-LD parser
- OpenGraph fallback
- DOM fallback
- CLI and FastAPI surface
- Basic tests

### v0.2: Catalog and listing extraction

- Category/listing page extraction
- Product card extraction
- Pagination discovery
- URL normalization
- JSONL/CSV export

### v0.3: Browser rendering and dynamic pages

- Optional Playwright renderer
- JavaScript-heavy product page support
- Screenshot/debug artifacts

### v0.4: Price intelligence

- SQLite product snapshots
- Price history
- Change detection
- Back-in-stock detection
- Batch monitoring

### v0.5: Alerts and LLM fallback

- Webhook/email alert hooks
- Schema-constrained extraction fallback
- Natural language extraction instructions
- Field-level validation against deterministic extractors

## Positioning

CommerceLens is not trying to be a generic scraper first. It is a commerce data engine: a focused toolkit for product, catalog, and price intelligence.

## License

MIT
