# Production Deployment

CommerceLens production is a two-process hosted system:

```text
API service      FastAPI routes, API keys, quotas, usage, jobs
Worker service   Scheduled extraction, monitoring, alerts, run history
PostgreSQL       Jobs, runs, API keys, usage events, product snapshots
```

## Required Environment

```bash
COMMERCELENS_ENV=production
COMMERCELENS_STORE_BACKEND=postgres
COMMERCELENS_DATABASE_URL=postgresql://user:password@host:5432/commercelens
COMMERCELENS_REQUIRE_API_KEY=true
COMMERCELENS_ADMIN_TOKEN=replace-with-long-random-secret
COMMERCELENS_USER_AGENT="CommerceLens/0.9 (+mailto:ops@yourcompany.com)"
COMMERCELENS_DEFAULT_TIMEOUT_SECONDS=20
```

Copy `.env.example` when creating a new environment.

## Health Checks

Use `/health` for liveness:

```bash
curl https://api.example.com/health
```

Use `/ready` for readiness. It checks that the configured store can be opened and
reports whether hosted security controls are configured:

```bash
curl https://api.example.com/ready
```

## Operator Dashboard

CommerceLens includes a private operator dashboard for early customer operations:

```bash
curl -H "X-Admin-Token: $COMMERCELENS_ADMIN_TOKEN" https://api.example.com/v1/accounts
```

Open the browser dashboard with the admin token:

```text
https://api.example.com/dashboard?admin_token=replace-with-admin-token
```

The dashboard shows accounts, projects, members, API keys, jobs, runs, and usage.
It also shows persisted product and listing extraction results from
`/v1/extract/product` and `/v1/extract/listing`, including success/failure state,
confidence, source URL, payload, and error details. It is intended for internal
operators, not customer self-service. Put it behind VPN, SSO, or an
authenticated edge before using it in production.

## API Service

```bash
uvicorn commercelens.api.main:app --host 0.0.0.0 --port "$PORT"
```

Run at least two API instances behind a load balancer for paid customers.

## Database Migrations

Production Postgres schema changes are tracked in
`commercelens_schema_migrations`. Apply migrations before starting a new API or
worker release:

```bash
commercelens migrate-postgres
```

The command reads `COMMERCELENS_DATABASE_URL` first, then `DATABASE_URL`. The
hosted store also runs unapplied migrations at startup for small deployments,
but release pipelines should run the migration command explicitly so schema
changes are visible and auditable.

## Render Blueprint

For the first hosted deployment, use the checked-in `render.yaml` Blueprint. It
creates:

- a Docker-based FastAPI web service
- a Docker-based worker service
- a managed Postgres database

See `docs/render.md` for the full deploy and smoke-test flow.

## Worker Service

```bash
commercelens worker --poll-seconds 60 --limit 25
```

Workers claim due jobs and create run records in one store transaction before
executing them. In Postgres deployments, the claim query uses row locks with
`FOR UPDATE SKIP LOCKED`, so multiple workers can poll without executing the
same due job. Start with one worker, then scale horizontally after domain
concurrency controls and queue-depth alerts are configured.

## Deployment Checklist

- TLS is enabled at the load balancer or ingress.
- `COMMERCELENS_REQUIRE_API_KEY=true`.
- `COMMERCELENS_ADMIN_TOKEN` is set.
- PostgreSQL has daily backups and point-in-time recovery.
- API and worker use the same database URL.
- Logs include request IDs and job IDs.
- Error reporting is enabled for API and worker.
- Rate limits exist at the edge for anonymous and authenticated traffic.
- Outbound fetch volume is monitored by domain.
- SMTP/webhook secrets are stored in the platform secret manager.
- Customer exports and debug snapshots are stored outside the repo.

## Sellable Product Baseline

Before selling to companies, the hosted service should support:

- Account/project-scoped API keys
- First-class accounts, projects, and members
- Persisted extraction records and dashboard drill-downs
- Scoped permissions
- Monthly quota checks
- Usage summary and usage event APIs
- Durable job/run history
- Retry and backoff for failed monitor jobs
- Customer-facing status and incident process
- Data retention policy
- Terms of service and privacy policy

## Next Infrastructure Step

The current worker still uses polling with distributed claiming. For
higher-volume customers, add a queue layer:

- Redis + RQ/Celery/Arq for self-managed deployments
- SQS, Cloud Tasks, or a managed queue for cloud deployments
- Per-domain concurrency controls
- Dead-letter jobs
- Idempotent job-run claim records
