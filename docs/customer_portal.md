# Customer Portal

CommerceLens includes a tenant scoped browser portal for hosted customers and
demo workspaces. Customers can review monitoring results and, when their key has
write scopes, create and manage monitors without using the CLI or JSON API.

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

Every portal key must have these read scopes:

- `usage:read`
- `jobs:read`
- `runs:read`
- `extractions:read`

Monitor management additionally requires `jobs:write`. Extraction previews
require `extract:write`. Keys with `*` have all of these permissions. Suspended
accounts and disabled keys cannot start or continue a portal session.

A read only key can still use the operational portal. The management page
explains which additional scopes are required instead of silently widening that
key's permissions.

## Session Security

Portal sessions use server stored token hashes and `Secure`, `HttpOnly`, and
`SameSite=Strict` cookies. State changing portal forms require the session bound
CSRF token. Sessions have both an absolute lifetime and an inactivity timeout,
and users can rotate the current session or sign out from every portal page.

Configure the limits in seconds:

```bash
COMMERCELENS_PORTAL_SESSION_TIMEOUT_SECONDS=28800
COMMERCELENS_PORTAL_IDLE_TIMEOUT_SECONDS=1800
```

Both values accept 60 seconds through 7 days. Always serve the portal over HTTPS.
For local browser testing, use `localhost` or a local TLS proxy so the secure
cookies are accepted.

## Projects

Open `/portal/manage` to create or select a project before adding monitors.

An account level portal key, where the key has an account ID but no project ID,
can create projects and switch between projects belonging to that account. A
project scoped key remains locked to its project. This prevents a browser
session from moving outside the project boundary encoded by the key.

## Create a Monitor

The monitor onboarding form supports:

- direct product URLs, one per line
- category or listing URLs
- CSV imports containing a `url`, `product_url`, or `product url` column
- interval or manual schedules
- standard HTML extraction or browser rendered extraction
- alert rules for price, availability, and general changes
- Slack, webhook, email, or portal/stdout destinations

Category URLs are onboarding sources rather than persistent monitor targets.
CommerceLens previews the category extraction, resolves discovered product URLs,
validates them, and stores the resolved product URLs in the monitor. This keeps
scheduled jobs compatible with the product monitor runner.

Before activation, CommerceLens checks malformed URLs and duplicates within the
submission and against monitors already in the selected project. It then runs
the first product extraction preview. Activation is shown only after validation
and the preview succeed.

For CSV uploads, the first column is used when no supported URL header is found,
and the preview shows that warning before activation.

## Manage Monitors

The management page lists the selected project's monitors. A signed in user with
`jobs:write` can:

- edit monitor name, schedule, interval, extraction mode, and product URLs
- run a monitor immediately
- pause and resume a monitor
- delete a monitor

All state changing forms are CSRF protected and re-fetch the monitor through the
session's account and project scope. Cross tenant IDs return `404`.

Lifecycle actions are also appended to the selected project's
`metadata.portal_audit_events` trail with an operation such as
`portal_monitor_pause`, `portal_monitor_resume`, `portal_monitor_edited`, or
`portal_monitor_delete`. Each entry carries the acting API key, owner, job ID,
timestamp, and action metadata. Audit records are capped to the latest 500
entries per project and do not consume customer API quota.

## Alert Destinations

The hosted portal exposes Slack, webhook, email, and stdout destinations.

Slack and webhook URLs use the same outbound URL policy as the rest of
CommerceLens. Email delivery uses the configured CommerceLens SMTP settings.
The filesystem destination remains available to local configuration files but
is intentionally not exposed through the hosted customer portal.

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

## Change Feed and Product Comparisons

The signed in portal exposes business changes directly instead of requiring customers to inspect raw run payloads.

Use `/portal/changes` for a chronological feed with project, source, event type, severity, and time filters. Each row summarizes the change and links to the responsible observation and monitor run when available. Stale and partial evidence is surfaced explicitly rather than silently hidden.

Use `/portal/products` to browse monitored product identities and `/portal/products/{product_id}` to compare current offers across stores. The comparison includes current price, availability, latest observation, extraction confidence, explicit product-match confidence and provenance, recent changes, and price history data. Confirmed and proposed matches are shown separately from the direct offers owned by the product; rejected matches are excluded.

Machine readable insight endpoints are available at:

```text
/v1/change-feed
/v1/products/{product_id}/comparison
/v1/products/{product_id}/history
```

Portal JSON exports use the same aggregation and tenant filters as the visible pages:

```text
/portal/export/changes
/portal/export/products/{product_id}/comparison
```

The change export accepts the visible filters and optional repeated `change_id` parameters for selected rows. Export responses remain `no-store` and use the browser session rather than putting API keys in URLs.

Staleness defaults to 24 hours for manual or unbound observations. Interval monitors use twice their configured interval with a one-hour minimum. Set `COMMERCELENS_STALE_AFTER_MINUTES` to change the fallback threshold.

