"""CommerceLens public SDK."""

from commercelens.version import __version__
from commercelens.alerts.config import MonitorConfig, MonitorTarget, load_monitor_config, save_example_config
from commercelens.alerts.delivery import AlertDeliveryReport, DeliveryResult, deliver_alert
from commercelens.alerts.rules import AlertCondition, AlertDestination, AlertDestinationType, AlertEvent, AlertRule
from commercelens.alerts.runner import MonitorRunResult, run_monitor_config, run_monitor_config_file
from commercelens.connectors.datasets import (
    DatasetLoadResult,
    DatasetWriteResult,
    ProductRecord,
    load_product_records,
    records_from_snapshots,
    write_product_records,
)
from commercelens.connectors.webhooks import WebhookEnvelope, WebhookSubscription, alert_event_to_webhook
from commercelens.core.crawler import CatalogCrawlResult, crawl_catalog
from commercelens.core.monitor import BatchMonitorResult, MonitorResult, monitor_product, monitor_products
from commercelens.extractors.listing import extract_listing, extract_listing_from_html
from commercelens.extractors.product import extract_product, extract_product_from_html
from commercelens.matching.products import ProductMatch, ProductMatchResult, match_products, product_similarity
from commercelens.schemas.listing import ListingExtractionResult, ListingProduct
from commercelens.schemas.product import Product, ProductExtractionResult
from commercelens.storage.backends import (
    PostgresSnapshotBackend,
    ProductSnapshotBackend,
    SQLiteSnapshotBackend,
    StorageConfig,
    make_snapshot_backend,
)
from commercelens.storage.price_store import PriceChange, PriceSnapshotStore, ProductSnapshot

__all__ = [
    "AlertCondition",
    "AlertDeliveryReport",
    "AlertDestination",
    "AlertDestinationType",
    "AlertEvent",
    "AlertRule",
    "BatchMonitorResult",
    "CatalogCrawlResult",
    "DatasetLoadResult",
    "DatasetWriteResult",
    "DeliveryResult",
    "ListingExtractionResult",
    "ListingProduct",
    "MonitorConfig",
    "MonitorResult",
    "MonitorRunResult",
    "MonitorTarget",
    "PostgresSnapshotBackend",
    "PriceChange",
    "PriceSnapshotBackend",
    "PriceSnapshotStore",
    "Product",
    "ProductExtractionResult",
    "ProductMatch",
    "ProductMatchResult",
    "ProductRecord",
    "ProductSnapshot",
    "ProductSnapshotBackend",
    "SQLiteSnapshotBackend",
    "StorageConfig",
    "WebhookEnvelope",
    "WebhookSubscription",
    "__version__",
    "alert_event_to_webhook",
    "crawl_catalog",
    "deliver_alert",
    "extract_listing",
    "extract_listing_from_html",
    "extract_product",
    "extract_product_from_html",
    "load_monitor_config",
    "load_product_records",
    "make_snapshot_backend",
    "match_products",
    "monitor_product",
    "monitor_products",
    "product_similarity",
    "records_from_snapshots",
    "run_monitor_config",
    "run_monitor_config_file",
    "save_example_config",
    "write_product_records",
]
