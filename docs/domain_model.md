# Commerce Domain Model

CommerceLens keeps the existing URL, monitor configuration, and `ProductSnapshot` interfaces available while adding a tenant scoped commerce domain for hosted workloads.

## Resources

Each domain record belongs to one account and one project.

| Resource | Purpose |
| --- | --- |
| Source | A store or commerce source, keyed by domain inside a project. |
| Product | The customer level product identity. |
| Offer | One store specific offer for a product. A product can have many offers. |
| Monitor | Persisted monitoring intent and configuration. Jobs reference this record through `monitor_id`. |
| Observation | An immutable capture of one offer at a point in time, including price, currency, availability, confidence, and provenance. |
| Change event | A deterministic transition between two observations for the same offer. |
| Product match | An explicit relationship between two product records with confidence, method, and review status. |

## Identity Rules

Sources use a normalized store domain inside the account and project boundary.

Offers use the normalized source URL inside a source. This keeps a store listing stable across repeated observations.

Products prefer strong identifiers found in extraction metadata, including GTIN, EAN, UPC, ISBN, and MPN. When no strong identifier exists, CommerceLens uses the existing `product_key_for` identity as a conservative fallback. The fallback intentionally avoids aggressive cross store matching. Product matching can then be reviewed and improved independently without silently merging unrelated products.

Observations use deterministic IDs derived from the tenant, offer, capture time, and normalized extraction payload. Replaying the same capture does not create another observation.

Change events are derived from the previous and current observation IDs plus the detected change type. The storage layer also enforces a tenant scoped `dedupe_key`, so retrying the same transition does not create duplicate events.

## Compatibility

Existing monitor payloads continue to deserialize because `MonitoringJob.config` remains present. New tenant scoped jobs also store `monitor_id` and create or bind a persisted monitor. Workers resolve the persisted monitor when available and fall back to the embedded job configuration for older jobs.

The existing `ProductSnapshot` store is unchanged. Hosted worker results and successful tenant scoped product extraction API calls are mirrored into the new domain repository. This lets existing CLI, API, and serialized configuration clients continue to operate while products, offers, observations, and change events become available for new customer workflows.

The `commercelens.jobs` package continues to expose `MonitoringWorker` and `run_job_now`. Those worker exports are loaded lazily so the domain service can use job models without introducing an import cycle.

## Storage

SQLite creates the commerce domain tables additively in the same jobs database. Existing tables and snapshot files are not rewritten.

Postgres migration `0003_commerce_domain` adds `monitor_id` to `monitoring_jobs` and creates the domain tables and indexes. The migration is additive and idempotent.

Both repositories enforce `account_id` and `project_id` on reads, lists, updates, and deletes. Cross tenant lookups return no record rather than exposing whether another tenant owns the requested ID.

## APIs

The domain router adds tenant scoped endpoints for:

* `/v1/sources`
* `/v1/products`
* `/v1/offers`
* `/v1/monitors`
* `/v1/observations`
* `/v1/change-events`
* `/v1/product-matches`

Sources, products, offers, monitors, and product matches support management operations. Observations and change events are append oriented and exposed as read APIs because they represent execution history.

The routes reuse the existing API key scopes. Domain resources require an API key with both an account and project context.

## Extraction and Worker Flow

A successful product extraction is converted into the domain in this order:

1. Upsert the source for the store domain.
2. Resolve or create the product identity.
3. Resolve or create the store offer.
4. Append the observation with extraction provenance.
5. Compare it with the prior offer observation.
6. Persist a change event only when a deterministic transition is detected.

Scheduled and manual hosted job runs use the same ingestion path through a result callback in the monitor runner. Existing monitor result and alert behavior remains unchanged.
