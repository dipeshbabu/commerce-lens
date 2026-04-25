# CommerceLens

Open-source product, catalog, monitoring, alerting, matching, and price intelligence extraction for developers.

CommerceLens turns messy e-commerce pages into structured product, listing, price-history, alert, and product-matching data using schema.org JSON-LD parsing, OpenGraph metadata, DOM heuristics, confidence scoring, catalog crawling, optional browser rendering, SQLite/Postgres snapshots, change detection, configurable alert rules, dataset connectors, persistent monitoring jobs, worker execution, API keys, and a clean Python SDK / CLI / FastAPI interface.

> Goal: commerce-ready product intelligence, not just raw HTML.

## Why CommerceLens?

Most scraping tools return raw HTML, Markdown, screenshots, or brittle selector outputs. CommerceLens is designed around normalized commerce objects: product name, brand, price, currency, availability, images, description, SKU, ratings, review counts, canonical URL, listing product cards, confidence scores, extraction provenance, price history, product-level change events, alerts, cross-store product matches, persistent monitor jobs, and run history.

CommerceLens is currently in early v0.7 development. The current release focuses on product page extraction, listing/category extraction, catalog crawling, JSONL/CSV export, optional Playwright rendering for JavaScript-heavy pages, local price intelligence through SQLite-backed product snapshots, optional PostgreSQL storage for hosted deployments, config-driven alert monitoring, dataset import/export, product matching, persistent monitoring jobs, worker execution, API keys, and Docker deployment.

## Features in v0.7

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
- Optional PostgreSQL product snapshot backend
- Storage backend abstraction for hosted deployments
- Product identity keys
- Price history lookup
- Price drop detection
- Price increase detection
- Availability change detection
- Back-in-stock detection
- Batch product monitoring
- Config-driven alert rules
- Alert delivery to stdout, file, webhook, Slack, and email
- Dry-run alert payload generation
- GitHub Actions scheduled monitoring workflow
- Dataset import from txt, CSV, JSON, and JSONL
- Dataset export to CSV, JSON, and JSONL
- Transparent product matching across datasets/domains
- Stable webhook envelopes for alert events
- Persistent monitoring jobs
- Interval and manual job schedules
- Worker tick and long-running worker loop
- Job run history with status, errors, durations, events, deliveries, and warnings
- Optional API key authentication for hosted deployments
- Docker and docker-compose deployment files
- Python SDK
- CLI
- FastAPI API
- Lightweight default install; browser and Postgres support are optional

## Installation

Static extraction, price monitoring, matching, alerts, and worker jobs:

```bash
pip install -e .
```

Browser rendering support:

```bash
pip install -e ".[browser]"
playwright install chromium
```

PostgreSQL backend support:

```bash
pip install -e ".[postgres]"
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

Monitor a product price with local SQLite:

```python
from commercelens import monitor_product

result = monitor_product("https://example.com/products/sample", db_path="prices.db")
print(result.product_key)
print(result.has_change)
print(result.change)
```

Use the hosted-ready storage abstraction:

```python
from commercelens import StorageConfig, monitor_product

result = monitor_product(
    "https://example.com/products/sample",
    storage_config=StorageConfig(backend="sqlite", sqlite_path="prices.db"),
)
```

Use PostgreSQL for hosted deployments:

```python
from commercelens import StorageConfig, monitor_product

result = monitor_product(
    "https://example.com/products/sample",
    storage_config=StorageConfig(
        backend="postgres",
        postgres_dsn="postgresql://user:password@localhost:5432/commercelens",
    ),
)
```

Run a monitor config and build alert payloads without delivering them:

```python
from commercelens import load_monitor_config, run_monitor_config

config = load_monitor_config("examples/monitor_config.json")
result = run_monitor_config(config, dry_run=True)
print(result.events)
```

Match products across datasets:

```python
from commercelens import ProductRecord, match_products

left = [ProductRecord(name="Nike Air Max 90", brand="Nike", amount=120, currency="USD")]
right = [ProductRecord(name="Nike Air Max 90 Shoes", brand="Nike", amount=125, currency="USD")]

matches = match_products(left, right, threshold=0.72)
print(matches.matches)
```

Read price history:

```python
from commercelens import PriceSnapshotStore

store = PriceSnapshotStore("prices.db")
history = store.history("PRODUCT_KEY_FROM_MONITOR_RESULT")
for snapshot in history:
    print(snapshot.captured_at, snapshot.amount, snapshot.currency, snapshot.availability)
```

Extract a listing/category page:

```python
from commercelens import extract_listing

listing = extract_listing("https://example.com/collections/shoes")
for item in listing.products:
    print(item.name, item.price, item.url)
```

Crawl a catalog by following next-page links:

```python
from commercelens import crawl_catalog

catalog = crawl_catalog("https://example.com/collections/shoes", max_pages=5)
print(catalog.product_count)
```

Render dynamic pages:

```python
from commercelens import extract_product

result = extract_product(
    "https://example.com/products/sample",
    render=True,
    screenshot_path="debug/product.png",
    html_snapshot_path="debug/product.html",
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

Batch monitor many products:

```bash
commercelens monitor-batch examples/products.txt --db prices.db --out monitor_result.json
```

Create an alert config:

```bash
commercelens init-config commercelens.monitor.json
```

Run alerts in dry-run mode:

```bash
commercelens run commercelens.monitor.json --dry-run
```

Run alerts and deliver them:

```bash
commercelens run commercelens.monitor.json
```

Create a persistent monitoring job:

```bash
commercelens create-job commercelens.monitor.json \
  --name "Watch competitor prices" \
  --interval-minutes 360
```

List jobs and runs:

```bash
commercelens list-jobs
commercelens list-runs
```

Run a job immediately:

```bash
commercelens run-job job_xxxxxxxxxxxxxxxx --dry-run
```

Execute due jobs once:

```bash
commercelens worker-tick --dry-run
```

Run the worker loop:

```bash
commercelens worker --poll-seconds 60
```

Create an API key for hosted deployments:

```bash
commercelens create-api-key --name "local dev"
```

Export latest tracked products:

```bash
commercelens export-history --db prices.db --out latest_products.jsonl
commercelens export-history --db prices.db --out latest_products.csv
```

Load and normalize a product dataset:

```bash
commercelens load-records examples/products_a.csv --out normalized.json
```

Match products across two datasets:

```bash
commercelens match-records examples/products_a.csv examples/products_b.csv --threshold 0.72 --out matches.json
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

Export listing products as JSONL or CSV:

```bash
commercelens listing https://example.com/collections/shoes --format jsonl --out products.jsonl
commercelens listing https://example.com/collections/shoes --format csv --out products.csv
```

Crawl a catalog:

```bash
commercelens crawl https://example.com/collections/shoes --max-pages 5 --format jsonl --out catalog.jsonl
```

Run the API server:

```bash
commercelens serve --host 0.0.0.0 --port 8000 --reload
```

## Alert config example

```json
{
  "db_path": "prices.db",
  "render": false,
  "targets": [
    {"url": "https://example.com/products/sample", "tags": ["demo"]}
  ],
  "rules": [
    {
      "name": "major-price-drop",
      "condition": "percent_drop_at_least",
      "threshold": 10,
      "destinations": [
        {"type": "stdout"},
        {"type": "file", "file_path": "alerts.jsonl"}
      ]
    }
  ]
}
```

Supported alert conditions include `any_change`, `price_drop`, `price_increase`, `back_in_stock`, `availability_change`, `price_below`, `price_above`, `percent_drop_at_least`, and `percent_increase_at_least`.

Supported destinations include `stdout`, `file`, `webhook`, `slack`, and `email`.

See `docs/alerts.md` for the complete alert monitoring guide.

## Hosted worker service

CommerceLens can run as a lightweight hosted monitoring service.

Run with Docker Compose:

```bash
docker compose up --build
```

The compose stack runs two processes:

```text
api:    FastAPI server on port 8000
worker: background worker loop polling due jobs
```

See `docs/worker-service.md` for the complete hosted service guide.

## Hosted data layer and connectors

See `docs/hosted_data_layer.md` for full examples covering:

- SQLite and PostgreSQL storage backends
- monitoring with a backend object
- dataset import/export
- product matching
- webhook envelopes
- API examples

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

Monitor a product:

```bash
curl -X POST http://127.0.0.1:8000/v1/monitor/product \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/products/sample", "db_path":"prices.db"}'
```

Run alert monitoring with inline config:

```bash
curl -X POST http://127.0.0.1:8000/v1/alerts/run \
  -H "Content-Type: application/json" \
  -d '{
    "dry_run": true,
    "config": {
      "db_path": "prices.db",
      "targets": [{"url": "https://example.com/products/sample"}],
      "rules": [{"name": "any", "condition": "any_change", "destinations": [{"type": "stdout"}]}]
    }
  }'
```

Create a persistent monitoring job:

```bash
curl -X POST http://127.0.0.1:8000/v1/jobs \
  -H "Content-Type: application/json" \
  -d @job.json
```

Run due jobs once:

```bash
curl -X POST "http://127.0.0.1:8000/v1/worker/tick?dry_run=true"
```

Match product records:

```bash
curl -X POST http://127.0.0.1:8000/v1/match/products \
  -H "Content-Type: application/json" \
  -d '{
    "left": [{"name": "Nike Air Max 90", "brand": "Nike", "amount": 120, "currency": "USD"}],
    "right": [{"name": "Nike Air Max 90 Shoes", "brand": "Nike", "amount": 125, "currency": "USD"}],
    "threshold": 0.72
  }'
```

Run alert monitoring from a file path:

```bash
curl -X POST http://127.0.0.1:8000/v1/alerts/run-file \
  -H "Content-Type: application/json" \
  -d '{"path":"examples/monitor_config.json", "dry_run": true}'
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

To test price monitoring and alerts locally:

```bash
commercelens monitor https://example.com/products/sample --db prices.db
commercelens history PRODUCT_KEY_FROM_MONITOR_RESULT --db prices.db
commercelens init-config commercelens.monitor.json
commercelens run commercelens.monitor.json --dry-run
```

To test product matching:

```bash
commercelens match-records examples/products_a.csv examples/products_b.csv --threshold 0.72
```

To test hosted jobs:

```bash
commercelens init-config commercelens.monitor.json
commercelens create-job commercelens.monitor.json --name "demo" --interval-minutes 1
commercelens worker-tick --dry-run
commercelens list-runs
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

### v0.5: Alerts and scheduled monitoring

- Alert rules
- Webhook, Slack, email, file, and stdout delivery
- Dry-run alert payloads
- GitHub Actions scheduled monitoring
- API and SDK alert runner

### v0.6: Hosted-ready data layer and connectors

- Storage backend abstraction
- Optional PostgreSQL snapshot backend
- Product matching across domains
- Dataset import/export connectors
- Webhook event envelopes

### v0.7: Worker queue and hosted monitoring service

- Persistent monitoring jobs
- Interval and manual schedules
- Job run history
- Worker tick and worker loop
- retry/backoff policies
- API keys
- hosted deployment template

## Positioning

CommerceLens is not trying to be a generic scraper first. It is a commerce data engine: a focused toolkit for product, catalog, monitoring, alerting, matching, scheduled jobs, and price intelligence.

## License

MIT
