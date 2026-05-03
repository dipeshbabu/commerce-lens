# Security Policy

CommerceLens is a private commercial codebase. Treat all credentials, customer
URLs, extracted product data, run logs, and alert payloads as confidential.

## Supported Version

Only the current production branch is supported for security fixes.

## Reporting

Report suspected security issues directly to the product owner. Do not open
public issues with secrets, customer data, exploit details, or production URLs.

Include:

- Affected environment or commit
- Steps to reproduce
- Impacted account, project, API key prefix, or job ID
- Relevant timestamps
- Any known customer impact

## Production Requirements

- Set `COMMERCELENS_REQUIRE_API_KEY=true` in every hosted environment.
- Set `COMMERCELENS_ADMIN_TOKEN` to a long random secret before exposing
  `/v1/api-keys`.
- Store API tokens only once at creation time. CommerceLens stores token hashes.
- Use PostgreSQL for hosted deployments.
- Put the API behind TLS.
- Keep worker and API processes on private infrastructure.
- Rotate SMTP, webhook, database, and admin credentials after personnel or
  infrastructure changes.
- Do not commit `.env`, databases, screenshots, HTML snapshots, alert files, or
  customer exports.

## Customer Data

Customer URLs, product snapshots, usage events, job runs, and alert payloads can
contain commercially sensitive information. Apply tenant scoping, retention
limits, and access controls before selling to external companies.
