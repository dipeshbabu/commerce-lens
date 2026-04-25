# CommerceLens Alerts and Scheduled Monitoring

CommerceLens v0.5 adds local-first alerting for price and availability monitoring.

You can now define products, rules, and destinations in a config file, run the monitor once from the CLI, expose it through the FastAPI API, or schedule it with GitHub Actions or cron.

## Quick start

Create an example config:

```bash
commercelens init-config commercelens.monitor.json
```

Run it without sending alerts:

```bash
commercelens run commercelens.monitor.json --dry-run
```

Run it and deliver alerts:

```bash
commercelens run commercelens.monitor.json
```

## Config format

```json
{
  "db_path": "prices.db",
  "render": false,
  "targets": [
    {"url": "https://example.com/products/sample", "tags": ["demo"]}
  ],
  "rules": [
    {
      "name": "major-price-drop",
      "condition": "percent_drop_at_least",
      "threshold": 10,
      "destinations": [
        {"type": "stdout"},
        {"type": "file", "file_path": "alerts.jsonl"}
      ]
    }
  ]
}
```

## Conditions

Supported rule conditions:

- `any_change`
- `price_drop`
- `price_increase`
- `back_in_stock`
- `availability_change`
- `price_below`
- `price_above`
- `percent_drop_at_least`
- `percent_increase_at_least`

## Destinations

Supported destination types:

- `stdout`
- `file`
- `webhook`
- `slack`
- `email`

Generic webhooks receive this shape:

```json
{
  "title": "CommerceLens alert: Sample Product",
  "text": "Rule: major-price-drop\nCondition: percent_drop_at_least\nCurrent price: 85 USD",
  "event": {
    "rule_name": "major-price-drop",
    "condition": "percent_drop_at_least",
    "product_key": "sample-key"
  }
}
```

Slack destinations use Slack incoming webhook formatting.

Email destinations use SMTP environment variables:

```bash
export COMMERCELENS_SMTP_HOST=smtp.example.com
export COMMERCELENS_SMTP_PORT=587
export COMMERCELENS_SMTP_USERNAME=your-user
export COMMERCELENS_SMTP_PASSWORD=your-password
export COMMERCELENS_SMTP_FROM=alerts@example.com
```

## API usage

Run with inline config:

```bash
curl -X POST http://localhost:8000/v1/alerts/run \
  -H 'Content-Type: application/json' \
  -d '{
    "dry_run": true,
    "deliver": true,
    "config": {
      "db_path": "prices.db",
      "targets": [{"url": "https://example.com/products/sample"}],
      "rules": [{"name": "any", "condition": "any_change", "destinations": [{"type": "stdout"}]}]
    }
  }'
```

Run with a config file path:

```bash
curl -X POST http://localhost:8000/v1/alerts/run-file \
  -H 'Content-Type: application/json' \
  -d '{"path": "examples/monitor_config.json", "dry_run": true}'
```

## Scheduling

The repo includes `.github/workflows/monitor.yml`, which runs every 6 hours and can also be triggered manually from GitHub Actions.

For local cron:

```cron
0 */6 * * * cd /path/to/commerce-lens && commercelens run examples/monitor_config.json >> monitor.log 2>&1
```

## Product direction

This phase turns CommerceLens from a one-shot extractor into a small monitoring system. It is still local-first, which keeps it developer-friendly, but the same config and event model can later power a hosted dashboard, persistent queues, team alert routing, and competitor intelligence workflows.
