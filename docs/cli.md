# Command line interface

The `commercelens` command supports local extraction, monitoring, matching, quality checks,
hosted administration, and worker execution.

Use built in help as the source of truth:

```bash
commercelens --help
commercelens product --help
commercelens create-job --help
```

## Core workflows

```bash
# Extract a product
commercelens product https://store.example/products/sample

# Extract product cards from a category page
commercelens listing https://store.example/collections/shoes

# Crawl a paginated catalog
commercelens crawl https://store.example/collections/shoes --max-pages 5

# Capture an observation and detect a change
commercelens monitor https://store.example/products/sample --db prices.db

# Inspect stored changes
commercelens changes --db prices.db
```

## Monitoring jobs

```bash
commercelens init-config commercelens.monitor.json
commercelens create-job commercelens.monitor.json --name "Competitor watch" --interval-minutes 360
commercelens list-jobs
commercelens worker-tick --dry-run
```

## Data workflows

```bash
commercelens load-records examples/products_a.csv --out normalized.json
commercelens match-records examples/products_a.csv examples/products_b.csv --out matches.json
commercelens catalog-diff before.csv after.csv --out catalog_changes.json
commercelens price-summary examples/products_a.csv --out price_summary.json
```

Commands write JSON to standard output unless an `--out` option is provided. Use secrets and
environment variables for credentials instead of committing them to configuration files.
