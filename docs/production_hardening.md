# Production Hardening

Use the production preflight command before promoting a hosted API or worker
release:

```bash
commercelens production-check
```

The check fails on missing deployment blockers:

- `COMMERCELENS_ENV=production`
- `COMMERCELENS_STORE_BACKEND=postgres`
- `COMMERCELENS_DATABASE_URL`
- `COMMERCELENS_REQUIRE_API_KEY=true`
- a strong `COMMERCELENS_ADMIN_TOKEN`

It also warns when operational settings are incomplete:

- `COMMERCELENS_USER_AGENT`
- `STRIPE_WEBHOOK_SECRET`

## Release Checklist

Run these before customer traffic is shifted to a new release:

```bash
commercelens production-check
commercelens migrate-postgres
commercelens quality-report
pytest
```

Confirm externally:

- TLS is active at the load balancer or ingress.
- API and worker services point at the same Postgres database.
- Postgres backups and point-in-time recovery are enabled.
- Logs include request IDs, job IDs, run IDs, and target domains.
- Error reporting is enabled for API and worker processes.
- Edge rate limits are configured for anonymous and authenticated traffic.
- High-volume keys have monthly domain quotas.
- `/ready` reports `status=ready`.

## Incident Triage

For failed monitoring jobs:

1. Check `/v1/runs?job_id=...` for the failing run.
2. Inspect `error`, `warning_count`, `event_count`, and `duration_ms`.
3. Check extraction records for the same account/project.
4. Re-run the job with `deliver=false` if alert noise is a risk.
5. Add or update a benchmark fixture when the failure is extractor-related.

For runaway domain usage:

1. Inspect `/v1/usage/events` filtered by the customer API key.
2. Tighten the key's `monthly_domain_quotas`.
3. Pause the offending job if quota pressure continues.
4. Add a domain-specific concurrency rule before re-enabling high-volume runs.
