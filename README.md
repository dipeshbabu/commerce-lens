# CommerceLens

Open-source product, catalog, and price intelligence extraction for developers.

CommerceLens turns messy e-commerce pages into structured product data using schema.org JSON-LD parsing, OpenGraph metadata, DOM heuristics, confidence scoring, and a clean Python SDK / CLI / FastAPI interface.

> Goal: commerce-ready product data, not just raw HTML.

## Why CommerceLens?

Most scraping tools return raw HTML, Markdown, or brittle selector outputs. CommerceLens is designed around normalized commerce objects: product name, brand, price, currency, availability, images, description, SKU, ratings, review counts, canonical URL, confidence scores, and extraction provenance.

CommerceLens is currently in early v0.1 development. The first release focuses on reliable product page extraction. Listing extraction, catalog crawling, browser rendering, price monitoring, and LLM fallback are planned next.

## Features in v0.1

- Product page extraction
- JSON-LD / schema.org Product parsing
- OpenGraph metadata fallback
- DOM heuristic fallback
- Price and currency normalization
- Availability normalization
- Image extraction
- Field-level confidence scores
- Source provenance for extracted fields
- Python SDK
- CLI
- FastAPI API
- Lightweight dependencies, no heavy ML model required

## Installation

```bash
pip install -e .
```

Or install from requirements:

```bash
pip install -r requirements.txt
```

## Python SDK

```python
from commercelens import extract_product

result = extract_product("https://example.com/products/sample")
print(result.product.name)
print(result.product.price.amount)
print(result.product.availability)
print(result.model_dump_json(indent=2))
```

You can also extract from local or already-fetched HTML:

```python
from commercelens import extract_product_from_html

html = """<html>...</html>"""
result = extract_product_from_html(html, url="https://example.com/products/sample")
```

## CLI

Extract from a URL:

```bash
commercelens product https://example.com/products/sample
```

Extract from local HTML:

```bash
commercelens html ./product.html --url https://example.com/products/sample
```

Write JSON output:

```bash
commercelens product https://example.com/products/sample --out product.json
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

Extract from HTML:

```bash
curl -X POST http://127.0.0.1:8000/v1/extract/product \
  -H "Content-Type: application/json" \
  -d '{"html":"<html><body><h1 class=\"product-title\">Sample</h1><span class=\"price\">$20.00</span></body></html>"}'
```

## Example response

```json
{
  "url": "https://example.com/products/sample",
  "page_type": "product",
  "product": {
    "name": "Sample Sneaker",
    "brand": "Acme",
    "description": "A comfortable running sneaker.",
    "price": {
      "amount": 89.99,
      "currency": "USD",
      "raw": "89.99"
    },
    "availability": "in_stock",
    "sku": "SNK-001",
    "rating": 4.6,
    "review_count": 128,
    "image_urls": ["https://example.com/images/sneaker.jpg"],
    "canonical_url": "https://example.com/products/sample",
    "source_url": "https://example.com/products/sample"
  },
  "confidence": 0.93,
  "fields": {
    "name": {
      "value": "Sample Sneaker",
      "confidence": 0.98,
      "source": "json_ld"
    },
    "price": {
      "value": {"amount": 89.99, "currency": "USD", "raw": "89.99"},
      "confidence": 0.96,
      "source": "json_ld"
    }
  },
  "warnings": []
}
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
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
- Webhook/email alert hooks

### v0.5: LLM fallback

- Schema-constrained extraction fallback
- Natural language extraction instructions
- Field-level validation against deterministic extractors

## Positioning

CommerceLens is not trying to be a generic scraper first. It is a commerce data engine: a focused toolkit for product, catalog, and price intelligence.

## License

MIT
