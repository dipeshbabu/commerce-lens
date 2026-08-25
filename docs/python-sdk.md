# Python API

CommerceLens exposes typed models and functions from the top level `commercelens` package.

## Extract a product

```python
from commercelens import extract_product

result = extract_product("https://store.example/products/sample")
print(result.product.name)
print(result.product.price)
print(result.confidence)
```

## Monitor price and availability

```python
from commercelens import monitor_product

result = monitor_product(
    "https://store.example/products/sample",
    db_path="prices.db",
)

print(result.product_key)
print(result.has_change)
print(result.change)
```

## Extract a listing and crawl a catalog

```python
from commercelens import crawl_catalog, extract_listing

listing = extract_listing("https://store.example/collections/shoes")
for product in listing.products:
    print(product.name, product.price, product.url)

catalog = crawl_catalog(
    "https://store.example/collections/shoes",
    max_pages=5,
)
print(catalog.product_count)
```

## Match product datasets

```python
from commercelens import ProductRecord, match_products

left = [ProductRecord(name="Air Max 90", brand="Nike", amount=120, currency="USD")]
right = [
    ProductRecord(
        name="Nike Air Max 90 Shoes",
        brand="Nike",
        amount=125,
        currency="USD",
    )
]

result = match_products(left, right, threshold=0.72)
print(result.matches)
```

## Choose a storage backend

SQLite is the default for local development. Hosted deployments can use Postgres:

```python
from commercelens import StorageConfig, monitor_product

result = monitor_product(
    "https://store.example/products/sample",
    storage_config=StorageConfig(
        backend="postgres",
        postgres_dsn="postgresql://user:password@localhost:5432/commercelens",
    ),
)
```

Public symbols are listed in `commercelens/__init__.py`. Returned values are Pydantic models
and can be serialized with `model_dump(mode="json", exclude_none=True)`.
