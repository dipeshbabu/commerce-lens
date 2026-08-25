# Security Policy

CommerceLens is open-source software distributed under the Apache License 2.0. The license
applies to the software, not to credentials, customer URLs, extracted product data, run logs,
or alert payloads. Treat that operational data as confidential.

## Supported Version

Only the current production branch is supported for security fixes.

## Reporting

Report suspected security issues with GitHub's
[private vulnerability reporting](https://github.com/dipeshbabu/commerce-lens/security/advisories/new)
flow. Do not open public issues with secrets, customer data, exploit details, or production
URLs. If private reporting is unavailable, contact the repository owner through the contact
method published on their GitHub profile before sharing details.

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
- Send API keys to JSON routes in the `X-API-Key` header. Never place API keys in
  portal links, query strings, browser history, screenshots, or exports.
- Serve `/portal` over HTTPS so its `Secure`, `HttpOnly`, and `SameSite=Strict`
  session cookies retain their protections.
- Keep portal absolute and inactivity timeouts bounded, and preserve CSRF checks
  on every state changing portal request.
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
