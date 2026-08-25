# Customer API Quickstart

## Authenticate

Use the API token created for your account/project:

```bash
export COMMERCELENS_API_KEY=cl_REPLACE_WITH_TOKEN
```

## Extract a Product

```bash
curl -X POST https://api.example.com/v1/extract/product \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $COMMERCELENS_API_KEY" \
  -d '{"url":"https://example.com/products/sample"}'
```

## Create a Monitoring Job

```bash
curl -X POST https://api.example.com/v1/jobs \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $COMMERCELENS_API_KEY" \
  -d '{
    "name": "Competitor watch",
    "interval_minutes": 1440,
    "config": {
      "targets": [
        {"url": "https://example.com/products/sample", "tags": ["demo"]}
      ],
      "rules": [
        {"name": "price-drop", "condition": "price_drop"}
      ]
    }
  }'
```

## Review Usage and Quota

```bash
curl https://api.example.com/v1/billing/usage \
  -H "X-API-Key: $COMMERCELENS_API_KEY"
```

## Open the Portal

```text
https://api.example.com/portal/login
```

Enter the account API key in the sign in form. It is exchanged for an expiring
browser session and is not placed in portal or export URLs.
