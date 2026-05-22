# Demo Script

Use this flow for a 15-minute customer walkthrough.

## Setup

```bash
commercelens seed-demo --jobs-db commercelens_demo.db --out demo_workspace.json
set COMMERCELENS_JOBS_DB=commercelens_demo.db
set COMMERCELENS_REQUIRE_API_KEY=true
commercelens serve --host 127.0.0.1 --port 8000
```

Open the `portal_path` from `demo_workspace.json`.

## Talk Track

1. Start with the monitored products table. Explain that CommerceLens watches
   normalized commerce objects, not raw pages.
2. Show active jobs, next run time, alert rules, and recent failures.
3. Open recent extractions and explain confidence, status, and product count.
4. Show usage and quota to position the hosted product as controllable
   infrastructure.
5. Explain alerts: price drop, price increase, back in stock, and availability
   changes.
6. Run `commercelens quality-report` to show how extraction quality is measured.

## Buyer Questions To Ask

- Which competitor or vendor domains matter most?
- How often do price or availability changes need to be detected?
- Which alert destinations are required?
- Do you need exports, webhooks, or both?
- Are there retention, security, or private deployment requirements?
