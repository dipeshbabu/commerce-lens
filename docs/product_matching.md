# Product matching quality and corrections

CommerceLens uses product matching to connect equivalent products across stores. Matching is intentionally conservative because a false match can corrupt competitor comparisons even when extraction itself is correct.

## Labeled evaluation

The deterministic evaluation set lives at `tests/fixtures/matching/evaluation.json`. It contains 31 synthetic and distributable pairs:

- 12 matched pairs
- 19 unmatched pairs
- title reorderings and abbreviations
- brand conflicts
- size, color, storage, memory, capacity, gender, and case size variants
- single item versus multi-pack and body-only versus kit bundles
- currency and sale-price differences
- exact duplicates and closely related model generations

The fixtures contain no customer pages, secrets, or proprietary catalog data.

## Before and after

The original scorer relied on fuzzy title similarity, brand, price, currency, and domain signals. It had no hard safeguard for structured variant or bundle conflicts. On the checked-in labeled set its results were:

| Scorer | Threshold | Precision | Recall | F1 | False match rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Previous scorer | 0.72 | 0.393 | 0.917 | 0.550 | 0.895 |
| Variant-aware scorer | 0.65 | 1.000 | 1.000 | 1.000 | 0.000 |

The after result is evidence on this small deterministic suite, not a claim of perfect real-world matching. New customer failures should be converted into sanitized fixtures so this evaluation becomes harder over time.

## Threshold selection

The variant-aware scorer produced the following threshold sweep:

| Threshold | Precision | Recall | F1 | False match rate |
| ---: | ---: | ---: | ---: | ---: |
| 0.60 | 1.000 | 1.000 | 1.000 | 0.000 |
| 0.65 | 1.000 | 1.000 | 1.000 | 0.000 |
| 0.70 | 1.000 | 0.917 | 0.957 | 0.000 |
| 0.72 | 1.000 | 0.917 | 0.957 | 0.000 |
| 0.75 | 1.000 | 0.750 | 0.857 | 0.000 |
| 0.80 | 1.000 | 0.583 | 0.737 | 0.000 |
| 0.85 | 1.000 | 0.250 | 0.400 | 0.000 |

`0.65` is the default because it is the higher of the two thresholds with perfect precision and recall on the current set. That gives more margin than `0.60` without losing a labeled true match. The API schemas, CLI, dataset matcher, and identity graph use the same default.

## Variant and bundle safeguards

Structured product metadata is treated as stronger negative evidence than fuzzy title similarity. When both records specify a value and those values conflict, the score is capped below the default threshold. Covered attributes include model, storage, memory, capacity, size, color, gender, variant, bundle quantity, and bundle type. Brand conflicts are also capped below the default threshold.

This makes pairs such as `128GB` versus `256GB`, `1 pack` versus `3 pack`, or camera body versus lens kit explicit non-matches even when most title tokens are identical.

## Customer corrections

The customer portal exposes product match review at `/portal/matches` for signed-in users. A key with `match:write` can:

- confirm a proposed match
- reject an incorrect match
- replace an incorrect equivalent with a different product

Every correction is tenant-scoped and CSRF protected. Correction provenance is kept in the existing `ProductMatchRecord.metadata` history with the action, actor, timestamp, previous status, optional note, and replacement identifiers.

Corrections use the same product match records consumed by the comparison builder. A rejected match disappears from comparisons immediately, and a confirmed replacement becomes the new equivalent without a second correction store or synchronization step.

## Adding evaluation cases

When a matching problem is reported:

1. Reproduce the minimum attributes needed to demonstrate the failure.
2. Replace merchant names, URLs, identifiers, and proprietary values with synthetic equivalents unless the source is explicitly distributable.
3. Label the pair as matched or unmatched and assign the narrowest category.
4. Include the structured attributes that make the decision correct, especially for variants and bundles.
5. Run the full threshold evaluation and include before and after metrics with any scoring change.
6. Do not lower the default threshold merely to recover recall if it introduces labeled false matches.
