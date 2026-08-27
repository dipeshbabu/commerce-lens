# Extraction Quality Reports

CommerceLens treats extraction reliability as a release criterion, not a best effort metric. The deterministic benchmark suite under `tests/fixtures/benchmarks` contains legacy HTML fixtures plus a synthetic manifest of representative commerce page snapshots.

The benchmark data is created for this repository. It does not contain customer pages, credentials, cookies, API keys, or proprietary storefront data.

## Run the Report

```bash
commercelens quality-report --out quality_report.json
```

The machine readable report includes:

- overall case and field score
- product and listing scores
- static and rendered snapshot scores
- adapter level scores
- product field accuracy
- normalized price accuracy
- availability accuracy
- listing recall
- average and p95 extraction latency by mode
- failure class distribution
- confidence bucket pass rates
- field level failures and recommendations
- release gate thresholds and any gate failures

## Release Gate

The default gate requires:

- at least 25 representative benchmark cases
- overall score of at least 0.98
- product field accuracy of at least 0.98
- price accuracy of at least 0.98
- availability accuracy of at least 0.98
- listing recall of at least 0.98

`commercelens quality-report` exits with a failure status when the report does not pass. The benchmark tests run in the normal CI test matrix, so a regression in the agreed metrics blocks a pull request through the existing CI gate.

The latency measurements are reported but intentionally are not a hard gate because shared CI runner timing is noisy. Large or sustained latency changes should still be investigated before release.

## Coverage

The suite covers 25 deterministic cases across:

- JSON LD product pages
- malformed structured data with DOM recovery
- Open Graph extraction
- Shopify style product markup
- static HTML and post render HTML snapshots
- listings and pagination
- variants and bundles
- sale prices
- USD, EUR, GBP, JPY, CAD, and AUD currencies
- availability states
- degraded pages with partial fields
- canonical URLs, ratings, and images

Rendered cases are saved post render HTML snapshots. They test extraction behavior after JavaScript rendering without adding browser timing or network nondeterminism to the quality metrics. The separate browser integration test remains responsible for validating the renderer itself.

## Adding a Fixture From a Customer Escalation

Never commit a customer page directly. Instead:

1. Reproduce the extraction failure locally.
2. Create the smallest synthetic HTML snapshot that preserves the failing structure.
3. Replace store names, product names, URLs, identifiers, images, and prices with invented values.
4. Remove scripts, analytics identifiers, cookies, account data, tokens, comments, and unrelated markup.
5. Add the expected fields and a descriptive tag to `quality_cases.json`, or add a legacy `.html` plus `.expected.json` pair when a standalone file is easier to review.
6. Run `commercelens quality-report --out quality_report.json` and the benchmark tests.
7. Include before and after quality results in the extractor change pull request.

A fixture should be distributable under the repository license and understandable without access to the original customer page.
