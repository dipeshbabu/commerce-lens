# Quickstart

This guide verifies CommerceLens locally without depending on a live commerce site.

## Install from a checkout

```bash
git clone https://github.com/dipeshbabu/commerce-lens.git
cd commerce-lens
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

## Verify extraction

Extract a normalized product from a checked in HTML fixture:

```bash
commercelens html tests/fixtures/benchmarks/product_jsonld.html
```

Run the complete deterministic quality report:

```bash
commercelens quality-report --out quality_report.json
```

## Monitor a public product

```bash
commercelens monitor https://store.example/products/sample --db prices.db
```

Run the command again after the page changes, then inspect observations:

```bash
commercelens changes --db prices.db
```

Replace the example URL with a public commerce page that you are permitted to access.

## Configure alerts

```bash
commercelens init-config commercelens.monitor.json
commercelens run commercelens.monitor.json --dry-run
```

Edit the generated configuration to add real targets, rules, and destinations. Keep the first
run in dry run mode so you can inspect events without delivering notifications.

## Explore the portal

Seed a local workspace:

```bash
commercelens seed-demo --jobs-db commercelens_demo.db --out demo_workspace.json
```

Start the API with the same database:

```bash
export COMMERCELENS_JOBS_DB=commercelens_demo.db
export COMMERCELENS_REQUIRE_API_KEY=true
commercelens serve --host 127.0.0.1 --port 8000
```

The seed command returns a local portal path and a one time demo token. Do not reuse demo
tokens in production.

## Next steps

* Use the [Python API](python-sdk.md) inside an application.
* Use the [CLI](cli.md) for local automation.
* Use the [REST API](api.md) for a hosted integration.
* Read the [production guide](production.md) before exposing the service to customers.
