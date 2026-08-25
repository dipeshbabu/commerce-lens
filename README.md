# CommerceLens

Monitor competitor prices, availability, and catalog changes without maintaining a
collection of scraping scripts.

[![CI](https://github.com/dipeshbabu/commerce-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/dipeshbabu/commerce-lens/actions/workflows/ci.yml)

CommerceLens turns product and category pages into normalized commerce records, captures
their history, and emits useful changes such as price drops, price increases, availability
updates, and products added to or removed from a catalog.

It is built for ecommerce brands, retailers, marketplaces, agencies, procurement teams,
and developers who need commerce data they can monitor instead of raw HTML they still
have to interpret.

## The workflow

1. Add product pages, category pages, or an existing product dataset.
2. Extract normalized names, brands, prices, currencies, availability, images, and identifiers.
3. Match equivalent products across stores.
4. Run monitors on a schedule and preserve observations over time.
5. Send important changes to Slack, email, webhooks, files, or downstream APIs.
6. Review products, runs, failures, usage, and exports in the customer portal.

## Common use cases

### Competitor monitoring

Track price and stock movement for products that compete with your catalog.

### Catalog intelligence

Detect products that appeared, disappeared, or changed between catalog captures.

### Pricing and availability alerts

Notify a team when a product crosses a price threshold, changes availability, or returns
to stock.

### Cross store product comparison

Normalize product datasets and match equivalent products whose titles differ across stores.

## Quickstart

CommerceLens is not currently published as an official package. Install it from a repository
checkout:

```bash
git clone https://github.com/dipeshbabu/commerce-lens.git
cd commerce-lens
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Run a deterministic extraction against a checked in fixture:

```bash
commercelens html tests/fixtures/benchmarks/product_jsonld.html
```

Extract a public product page:

```bash
commercelens product https://store.example/products/sample
```

Monitor that page and store observations locally:

```bash
commercelens monitor https://store.example/products/sample --db prices.db
```

Some sites require browser rendering:

```bash
python -m pip install -e ".[browser]"
playwright install chromium
commercelens product https://store.example/products/sample --render
```

See the [quickstart guide](docs/quickstart.md) for monitoring rules, local portal setup, and
hosted deployment paths.

## Python

```python
from commercelens import monitor_product

result = monitor_product(
    "https://store.example/products/sample",
    db_path="prices.db",
)

if result.has_change:
    print(result.change)
```

The public Python API also supports product extraction, listing extraction, catalog crawling,
dataset import and export, product matching, alert rules, and storage backends.

## Interfaces

CommerceLens can be used through:

* A Python library for applications and data workflows
* A command line interface for local jobs and automation
* A FastAPI service for hosted integrations
* A background worker for persistent monitoring jobs
* A tenant scoped portal for monitoring and operational visibility

Run `commercelens --help` for the complete command list. Start the API with:

```bash
commercelens serve --host 127.0.0.1 --port 8000
```

Interactive API documentation is then available at `http://127.0.0.1:8000/docs`.

## Extraction strategy

CommerceLens prefers structured commerce signals and falls back when necessary:

1. Schema.org Product and JSON LD
2. Store specific adapters such as Shopify
3. OpenGraph metadata
4. DOM heuristics
5. Optional Playwright rendering for dynamic pages

Every extracted field can include confidence and provenance so consumers can distinguish
strong structured data from heuristic fallbacks.

## Documentation

Start with the [documentation index](docs/README.md).

* [Quickstart](docs/quickstart.md)
* [Python API](docs/python-sdk.md)
* [Command line interface](docs/cli.md)
* [REST API](docs/api.md)
* [Alerts](docs/alerts.md)
* [Browser rendering](docs/render.md)
* [Customer portal](docs/customer_portal.md)
* [Worker service](docs/worker-service.md)
* [Hosted data layer](docs/hosted_data_layer.md)
* [Production deployment](docs/production.md)
* [Extraction quality](docs/extraction_quality.md)

## Development

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a substantial change. Project
interactions follow the [Code of Conduct](CODE_OF_CONDUCT.md), support paths are documented in
[SUPPORT.md](SUPPORT.md), and vulnerabilities must follow [SECURITY.md](SECURITY.md).

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

Tests use local HTML fixtures and temporary databases. Live commerce pages should not be
required for the default test suite.

## Project status

CommerceLens is in beta. The extraction engine, monitoring jobs, alerts, matching, API,
worker, storage backends, and portal are implemented, but reliability varies across commerce
sites. Review confidence and failure information before using extracted data for automated
business decisions.

Operators are responsible for respecting website terms, access controls, crawl rates, privacy
requirements, and applicable law.

## License

See [LICENSE](LICENSE). The licensing and contributor governance work is tracked in
[issue #14](https://github.com/dipeshbabu/commerce-lens/issues/14).
