# Security Overview

CommerceLens is designed for hosted, tenant-scoped commerce intelligence
workflows.

## Access Control

- Hosted deployments require API keys when `COMMERCELENS_REQUIRE_API_KEY=true`.
- API keys are stored as SHA-256 hashes.
- API keys carry account, project, owner, scopes, plan, quota, and domain-quota
  context.
- Operator-only routes use `COMMERCELENS_ADMIN_TOKEN` and should be placed
  behind VPN, SSO, or an authenticated edge in production.

## Data Isolation

- Jobs, runs, usage, API keys, and extraction records are scoped by account and
  project.
- Customer APIs filter tenant data using the authenticated API key context.
- The customer portal requires a valid tenant API key.

## Operational Controls

- Monthly quotas protect hosted capacity.
- Per-domain quotas reduce the risk of one target domain consuming the month.
- Production preflight checks validate core security settings before release.
- PostgreSQL should be deployed with backups and point-in-time recovery.

## Secrets

Store these only in a platform secret manager:

- `COMMERCELENS_DATABASE_URL`
- `COMMERCELENS_ADMIN_TOKEN`
- `STRIPE_WEBHOOK_SECRET`
- SMTP credentials
- webhook credentials

## Recommended Production Boundary

- TLS at the ingress or load balancer
- authenticated edge for `/dashboard`
- rate limits for anonymous and authenticated traffic
- centralized logs and error reporting for API and worker services
