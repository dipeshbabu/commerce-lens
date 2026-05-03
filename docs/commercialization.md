# Commercialization Plan

CommerceLens should be sold as commerce intelligence infrastructure, not as a
generic scraper.

## Positioning

Recommended positioning:

```text
CommerceLens monitors product, price, availability, and catalog changes across
commerce sites and turns them into structured data, alerts, and exports.
```

Avoid leading with scraping. Companies buy reliability, monitoring, alerts,
structured product data, and operational visibility.

## Target Customers

- DTC brands monitoring competitor price and stock movement
- Retailers monitoring MAP or pricing compliance
- Marketplaces monitoring seller/catalog changes
- Ecommerce agencies running recurring competitor reports
- Procurement teams watching vendor catalogs
- Pricing and revenue teams needing alertable market signals

## Initial Paid Product

Ship the first paid version as a hosted API plus operator dashboard:

- Projects
- Accounts and members
- API keys
- Monitored products and URLs
- Persisted product and listing extraction records
- Latest product snapshot
- Price and availability history
- Alert rules
- Job run history
- Failed-job triage
- CSV/JSON export
- Usage and quota page

## Pricing Model

Use usage-based plans with clear limits:

```text
Starter      $99/mo     5,000 extraction credits, basic alerts
Growth       $499/mo    50,000 extraction credits, jobs, exports, webhooks
Business     $1,500+/mo custom domains, higher limits, priority support
Enterprise   Custom     SLA, SSO, private deployment, data retention terms
```

Charge higher credit cost for rendered pages because Playwright work is more
expensive than static extraction.

Suggested credit weights:

```text
Static product extraction       1 credit
Listing extraction              2 credits
Rendered product extraction     5 credits
Rendered listing extraction     10 credits
Catalog crawl page              3 credits
Monitor job target              1-5 credits per run
```

## Sales Readiness

Prepare these before talking to larger companies:

- One-page product brief
- Security overview
- Data retention policy
- Terms of service
- Privacy policy
- Sample DPA
- Pricing sheet
- API docs
- Uptime/status page
- Demo workspace with realistic product history

## Product Moat

The defensible part is extraction reliability, not API routing. Invest in:

- HTML fixture benchmark suite
- Domain-level extraction quality reports
- Per-site adapters for high-value retailers
- Confidence explanations for extracted fields
- Rendered/static fallback strategy
- Failure classification and retry analytics
- Alert precision: fewer noisy alerts, better summaries

## Near-Term Roadmap

1. Customer-facing dashboard for jobs, products, alerts, and usage.
2. Stripe checkout, subscription, and webhook integration.
3. Queue-backed worker execution.
4. PostgreSQL migrations.
5. Domain budgets and concurrency controls.
6. Extraction benchmark fixtures.
7. Customer-facing API docs and examples.
8. Admin tools for accounts, plans, API keys, and failed jobs.
