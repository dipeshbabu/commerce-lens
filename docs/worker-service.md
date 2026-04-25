# CommerceLens Worker Service

CommerceLens v0.7 adds a persistent monitoring service layer on top of the extractor, crawler, price store, and alert runner.

This turns CommerceLens from a local scraping library into a developer tool that can run scheduled commerce intelligence jobs for users, teams, or hosted deployments.

## What this phase adds

- Persistent monitoring jobs stored in SQLite.
- Job schedules using interval based polling.
- Manual jobs for one off monitors.
- Job run history with status, error, duration, events, deliveries, and warnings.
- Worker loop for executing due jobs.
- FastAPI routes for jobs, runs, worker ticks, and API key creation.
- Optional API key authentication for hosted deployments.
- CLI commands for local operation.

## Local workflow

Create a monitor config:

```bash
commercelens init-config commercelens.monitor.json
```

Create a persistent job:

```bash
commercelens create-job commercelens.monitor.json \
  --name "Watch competitor prices" \
  --interval-minutes 360
```

List jobs:

```bash
commercelens list-jobs
```

Run a job immediately:

```bash
commercelens run-job job_xxxxxxxxxxxxxxxx --dry-run
```

Run one worker tick:

```bash
commercelens worker-tick --dry-run
```

Run continuously:

```bash
commercelens worker --poll-seconds 60
```

## Hosted API workflow

Start the API:

```bash
commercelens serve --host 0.0.0.0 --port 8000
```

Create an API key:

```bash
curl -X POST http://localhost:8000/v1/api-keys \
  -H "Content-Type: application/json" \
  -d '{"name":"local dev"}'
```

Enable auth:

```bash
export COMMERCELENS_REQUIRE_API_KEY=true
export COMMERCELENS_JOBS_DB=commercelens_jobs.db
```

Create a job:

```bash
curl -X POST http://localhost:8000/v1/jobs \
  -H "X-API-Key: $COMMERCELENS_API_KEY" \
  -H "Content-Type: application/json" \
  -d @job.json
```

Run due jobs:

```bash
curl -X POST "http://localhost:8000/v1/worker/tick?dry_run=true" \
  -H "X-API-Key: $COMMERCELENS_API_KEY"
```

## API routes

| Method | Route | Purpose |
|---|---|---|
| POST | `/v1/jobs` | Create a persistent monitoring job |
| GET | `/v1/jobs` | List jobs |
| GET | `/v1/jobs/{job_id}` | Fetch one job |
| PATCH | `/v1/jobs/{job_id}` | Update or pause/resume a job |
| DELETE | `/v1/jobs/{job_id}` | Delete a job |
| POST | `/v1/jobs/{job_id}/run` | Run a job immediately |
| GET | `/v1/runs` | List job runs |
| GET | `/v1/runs/{run_id}` | Fetch one run |
| POST | `/v1/worker/tick` | Execute currently due jobs |
| POST | `/v1/api-keys` | Create an API key |

## Deployment notes

For a single instance deployment, SQLite is enough. Mount a persistent volume for:

- `commercelens.db`, price snapshots
- `commercelens_jobs.db`, job definitions and run history

For a larger hosted product, the next backend step is replacing SQLite with Postgres and running the worker as a separate process from the API.

Recommended process split:

```text
api:    uvicorn commercelens.api.main:app --host 0.0.0.0 --port 8000
worker: commercelens worker --poll-seconds 60
```

## Product direction

This phase creates the base for a serious hosted developer product:

- Users create extraction and monitoring jobs through API or CLI.
- CommerceLens executes jobs on schedule.
- Runs become auditable logs.
- Alerts can be routed through webhook, Slack, or email channels.
- API keys make it usable for external customers.

The next product phase should add Postgres, a queue backend, multi tenant accounts, usage metering, and a small dashboard.
