# REST API

CommerceLens exposes the extraction and monitoring workflows through FastAPI.

## Start locally

```bash
commercelens serve --host 127.0.0.1 --port 8000
```

OpenAPI documentation is available at:

```text
http://127.0.0.1:8000/docs
```

Health and readiness endpoints are available at `/health` and `/ready`.

## Extract a product

```bash
curl -X POST http://127.0.0.1:8000/v1/extract/product \
  -H "Content-Type: application/json" \
  -d '{"url":"https://store.example/products/sample"}'
```

## Monitor a product

```bash
curl -X POST http://127.0.0.1:8000/v1/monitor/product \
  -H "Content-Type: application/json" \
  -d '{"url":"https://store.example/products/sample","db_path":"prices.db"}'
```

## Authentication

Hosted deployments can require a tenant scoped API key:

```bash
curl http://127.0.0.1:8000/v1/usage/summary \
  -H "X-API-Key: cl_REPLACE_WITH_TOKEN"
```

Set `COMMERCELENS_REQUIRE_API_KEY=true` to require keys on protected routes. Administrative
routes use `COMMERCELENS_ADMIN_TOKEN`. Do not expose development defaults publicly.

## Compatibility

Routes under `/v1` are the current public API surface. Consumers should rely on the generated
OpenAPI schema rather than internal Python modules. See the [hosted backend guide](hosted_backend.md)
for accounts, projects, usage, jobs, and worker configuration.
