# Hosted backend guide

CommerceLens can run as either a local developer tool or a hosted commerce intelligence API. The hosted backend mode adds API-key authentication, tenant context, PostgreSQL-backed jobs/runs/API keys/usage events, a long-running worker, and usage summaries.

## Architecture

```text
Client / SDK / curl
      |
      v
FastAPI service
      |
      |-- product extraction
      |-- listing extraction
      |-- catalog crawling
      |-- product matching
      |-- alert config execution
      |-- persistent jobs
      |-- usage endpoints
      |
      v
Job store abstraction
      |
      |-- SQLite for local development
      |-- PostgreSQL for hosted deployments
      |
      v
Worker process
      |
      |-- polls due jobs
      |-- runs monitor configs
      |-- records run history
      |-- records alert/event/delivery usage
```

## Environment variables

Local SQLite mode is the default:

```bash
export COMMERCELENS_STORE_BACKEND=sqlite
export COMMERCELENS_JOBS_DB=commercelens_jobs.db
```

Hosted PostgreSQL mode:

```bash
export COMMERCELENS_STORE_BACKEND=postgres
export COMMERCELENS_DATABASE_URL="postgresql://user:password@host:5432/commercelens"
export COMMERCELENS_REQUIRE_API_KEY=true
```

`DATABASE_URL` is also accepted when `COMMERCELENS_DATABASE_URL` is not set.

## Install Postgres support

```bash
pip install -e ".[postgres]"
```

## Start the API

```bash
commercelens serve --host 0.0.0.0 --port 8000
```

## Create a tenant API key

```bash
commercelens create-api-key \
  --name "customer demo" \
  --account-id acct_demo \
  --project-id proj_default \
  --owner demo@example.com
```

The command returns the API token once. Store it securely. CommerceLens only stores a SHA-256 token hash.

## Use authenticated extraction

```bash
curl -X POST http://127.0.0.1:8000/v1/extract/product \
  -H "Content-Type: application/json" \
  -H "X-API-Key: cl_REPLACE_WITH_TOKEN" \
  -d '{"url":"https://example.com/products/sample"}'
```

When authentication is enabled, the API key adds tenant context to usage records:

```text
account_id
project_id
owner
api_key_id
```

## Usage metering

CommerceLens records usage for high-value hosted routes:

```text
product_extract
listing_extract
catalog_crawl
monitor_run
match_request
job_run
alert_event
alert_delivery
api_request
```

Check usage through the API:

```bash
curl http://127.0.0.1:8000/v1/usage/summary \
  -H "X-API-Key: cl_REPLACE_WITH_TOKEN"

curl "http://127.0.0.1:8000/v1/usage/events?limit=20" \
  -H "X-API-Key: cl_REPLACE_WITH_TOKEN"
```

Check usage through the CLI:

```bash
commercelens usage-summary --account-id acct_demo --project-id proj_default
commercelens usage-events --account-id acct_demo --project-id proj_default --limit 20
```

## Create persistent monitoring jobs

```bash
commercelens create-job examples/monitor_config.json \
  --name "Competitor price watch" \
  --interval-minutes 360 \
  --account-id acct_demo \
  --project-id proj_default \
  --owner demo@example.com
```

List jobs:

```bash
commercelens list-jobs --account-id acct_demo --project-id proj_default
```

Run a job immediately:

```bash
commercelens run-job job_xxxxxxxxxxxxxxxx --dry-run
```

## Run the worker

One tick:

```bash
commercelens worker-tick --dry-run
```

Long-running loop:

```bash
commercelens worker --poll-seconds 60
```

The worker uses the same store selector as the API. In hosted mode, run both the API and worker with the same PostgreSQL connection string.

## Recommended deployment shape

For a small hosted beta, use three managed services:

```text
1. Web service: commercelens serve --host 0.0.0.0 --port $PORT
2. Worker service: commercelens worker --poll-seconds 60
3. PostgreSQL database
```

Set the same environment variables on both web and worker services:

```bash
COMMERCELENS_STORE_BACKEND=postgres
COMMERCELENS_DATABASE_URL=postgresql://...
COMMERCELENS_REQUIRE_API_KEY=true
```

## Product implications

This milestone makes CommerceLens viable as a hosted developer API because it now has:

- authenticated access
- tenant context
- persistent jobs
- run history
- usage events
- usage summaries
- PostgreSQL storage
- a worker process
- local SQLite fallback

The next production gap is quota enforcement and billing integration. Usage metering is now in place, so quota checks can be added before each metered route without changing the API shape.
