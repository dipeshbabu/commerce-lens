# CommerceLens documentation

CommerceLens supports a local Python and command line workflow as well as a hosted API,
worker, and customer portal. Choose the guide that matches what you are trying to do.

## Start here

* [Quickstart](quickstart.md): install the project, verify extraction, and run a local demo
* [Python API](python-sdk.md): call extraction, monitoring, crawling, and matching functions
* [Command line interface](cli.md): use CommerceLens from a terminal or scheduled task
* [REST API](api.md): integrate with the FastAPI service

## Monitoring and data

* [Alerts](alerts.md): define change rules and delivery destinations
* [Worker service](worker-service.md): run persistent monitoring jobs
* [Hosted data layer](hosted_data_layer.md): choose SQLite or Postgres and use dataset connectors
* [Customer portal](customer_portal.md): inspect tenant scoped jobs, runs, extractions, and usage

## Extraction and reliability

* [Browser rendering](render.md): extract JavaScript driven commerce pages
* [Extraction quality](extraction_quality.md): run deterministic fixture benchmarks
* [Production hardening](production_hardening.md): review operational safeguards

## Deployment and operations

* [Hosted backend](hosted_backend.md): configure accounts, API keys, jobs, and workers
* [Production deployment](production.md): configure and validate a hosted environment
* [Render deployment](render.md): deploy the included Render blueprint
* [Demo workspace](demo_workspace.md): seed a realistic local customer workspace

Commercial planning documents under `docs/sales` describe the current product hypothesis.
They are not API contracts or guarantees of service availability.
