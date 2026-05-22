# Extraction Quality Reports

CommerceLens treats extraction reliability as a product surface. The benchmark
fixtures under `tests/fixtures/benchmarks` can be promoted into a quality report
that tracks case pass rate, field accuracy, failure concentration, and next
actions.

## Run the Report

```bash
commercelens quality-report --out quality_report.json
```

The report includes:

- suite score and pass/fail state
- per-kind scores for product and listing fixtures
- field-level accuracy for expected paths such as `product.name`
- failing field counts
- recommendations for fixture coverage and extractor priorities

## Release Gate

For paid hosted deployments, use this as a release gate:

```bash
commercelens quality-report
pytest
```

Recommended policy:

- block releases when fixture score drops below the previous release
- add one fixture for every customer extraction escalation
- keep separate fixtures for static, rendered, listing, and malformed JSON-LD
  pages
- review low-confidence fields even when the exact expected value passes

## Near-Term Coverage Target

Before selling to larger customers, expand the benchmark suite to at least 25
fixtures:

- 10 product pages with strong JSON-LD
- 5 product pages with incomplete or malformed JSON-LD
- 5 listing/category pages
- 3 JavaScript-heavy pages captured from rendered snapshots
- 2 blocked or degraded pages that verify failure classification
