# Customer Portal

CommerceLens includes a customer-facing portal for early hosted customers and
demo workspaces. It is scoped by a tenant API key and shows only that key's
account and project data.

## Open the Portal

Run the API against the jobs database that contains the customer account:

```bash
set COMMERCELENS_JOBS_DB=commercelens_demo.db
set COMMERCELENS_REQUIRE_API_KEY=true
commercelens serve --host 127.0.0.1 --port 8000
```

Open the portal with a tenant API key:

```text
http://127.0.0.1:8000/portal?api_key=cl_REPLACE_WITH_TOKEN
```

The same key must have these scopes:

- `usage:read`
- `jobs:read`
- `runs:read`
- `extractions:read`

Keys with `*` also work.

## Portal Views

The overview page shows:

- monitored product URLs
- active jobs and schedule state
- recent job runs and alert activity
- recent failure classes and recommended next actions
- recent product/listing extractions
- usage totals
- quota usage and remaining budget
- JSON export links for jobs, runs, extractions, and usage events

Detail pages are available for:

- `/portal/jobs/{job_id}`
- `/portal/runs/{run_id}`
- `/portal/extractions/{extraction_id}`

All detail pages re-check the API key and tenant scope before loading records.
Records from another account or project return `404`.

## Failure Triage

The portal classifies failed runs and extractions into stable classes:

- `timeout`
- `blocked`
- `render_required`
- `parser_low_confidence`
- `network_error`
- `invalid_url`
- `rate_limited`
- `quota_exceeded`
- `queue_deferred`
- `unknown`

Use `/v1/issues` with the same tenant API key to fetch the same triage data as
JSON for customer-facing UI or support workflows.

## Exports

The portal exposes tenant-scoped JSON downloads:

```text
/portal/export/jobs?api_key=cl_REPLACE_WITH_TOKEN
/portal/export/runs?api_key=cl_REPLACE_WITH_TOKEN
/portal/export/extractions?api_key=cl_REPLACE_WITH_TOKEN
/portal/export/usage?api_key=cl_REPLACE_WITH_TOKEN
```

These are intended for early customer handoff and demos. For production
customer access, put the portal behind an authenticated edge and avoid sharing
raw API-key URLs broadly.
