# Production Hardening

## Outbound URL policy

CommerceLens treats product, listing, redirect, browser subresource, and alert webhook URLs
as untrusted input. The default policy permits only HTTP and HTTPS destinations that resolve
entirely to public address space.

The policy rejects embedded credentials, loopback, private, link local, multicast, reserved,
unspecified, and known cloud metadata destinations. Static fetches also limit redirects,
decoded response bytes, URL length, and accepted HTML content types.

```text
COMMERCELENS_MAX_REDIRECTS=5
COMMERCELENS_MAX_RESPONSE_BYTES=5242880
COMMERCELENS_MAX_URL_LENGTH=4096
```

Private deployments that intentionally fetch a private commerce host can allow exact
hostnames:

```text
COMMERCELENS_ALLOWED_PRIVATE_HOSTS=catalog.internal.example
```

Do not set this option from customer input and do not allow broad suffixes. Network egress
controls should still deny cloud metadata and internal management networks. Application
validation is one layer, not a replacement for an outbound firewall or proxy policy.

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
