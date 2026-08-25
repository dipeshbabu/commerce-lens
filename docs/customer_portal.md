# Customer Portal

CommerceLens includes a tenant scoped browser portal for hosted customers and
demo workspaces. Customers use it to review monitored products, job health,
recent changes, extraction results, usage, quotas, and exports without operating
the worker or querying the API directly.

## Sign In

Run the API against the jobs database that contains the customer account:

```bash
set COMMERCELENS_JOBS_DB=commercelens_demo.db
set COMMERCELENS_REQUIRE_API_KEY=true
commercelens serve --host 127.0.0.1 --port 8000
```

Open `/portal/login` and enter the one time API key supplied by the workspace
administrator:

```text
https://api.example.com/portal/login
```

The sign in form exchanges the API key for an opaque, expiring browser session.
The API key is sent in the form body and is never added to portal links, browser
history, or export URLs. Continue sending `X-API-Key` when using JSON API routes;
that client authentication flow is unchanged.

The key must have these scopes:

- `usage:read`
- `jobs:read`
- `runs:read`
- `extractions:read`

Keys with `*` also work. Suspended accounts and disabled keys cannot start or
continue a portal session.

## Session Security

Portal sessions use server stored token hashes and `Secure`, `HttpOnly`, and
`SameSite=Strict` cookies. State changing portal forms also require a session
bound CSRF token. Sessions have both an absolute lifetime and an inactivity
timeout, and users can rotate the current session or sign out from every portal
page.

Configure the limits in seconds:

```bash
COMMERCELENS_PORTAL_SESSION_TIMEOUT_SECONDS=28800
COMMERCELENS_PORTAL_IDLE_TIMEOUT_SECONDS=1800
```

Both values accept 60 seconds through 7 days. Always serve the portal over HTTPS.
For local browser testing, use `localhost` or a local TLS proxy so the secure
cookies are accepted.

## Portal Views

The overview page shows:

- monitored product URLs
- active jobs and schedule state
- recent job runs and alert activity
- recent failure classes and recommended actions
- recent product and listing extractions
- usage totals and quota remaining
- JSON exports for jobs, runs, extractions, and usage events

Detail pages are available at:

- `/portal/jobs/{job_id}`
- `/portal/runs/{run_id}`
- `/portal/extractions/{extraction_id}`

Every view revalidates the session and tenant scope. A record from another
account or project returns `404` without revealing that the record exists.

## Failure Triage

The portal groups failed runs and extractions into stable classes such as
`timeout`, `blocked`, `render_required`, `parser_low_confidence`, `network_error`,
`invalid_url`, `rate_limited`, `quota_exceeded`, and `queue_deferred`.

Use `/v1/issues` with `X-API-Key` to fetch the same triage data as JSON for a
customer UI or support workflow.

## Exports

Authenticated portal users can download tenant scoped JSON from clean paths:

```text
/portal/export/jobs
/portal/export/runs
/portal/export/extractions
/portal/export/usage
```

Export responses are marked `no-store`. They use the browser session cookie and
never carry an API key in the URL.
