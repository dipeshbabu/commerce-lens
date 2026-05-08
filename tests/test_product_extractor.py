from commercelens.extractors.product import extract_product_from_html


HTML = """
<html>
  <head>
    <link rel="canonical" href="https://example.com/products/sample" />
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Sample Sneaker",
      "brand": {"@type": "Brand", "name": "Acme"},
      "description": "A comfortable running sneaker.",
      "sku": "SNK-001",
      "image": ["/images/sneaker.jpg"],
      "offers": {
        "@type": "Offer",
        "price": "89.99",
        "priceCurrency": "USD",
        "availability": "https://schema.org/InStock"
      },
      "aggregateRating": {
        "@type": "AggregateRating",
        "ratingValue": "4.6",
        "reviewCount": "128"
      }
    }
    </script>
  </head>
  <body></body>
</html>
"""


def test_extract_product_from_jsonld() -> None:
    result = extract_product_from_html(HTML, url="https://example.com/products/sample")

    assert result.product.name == "Sample Sneaker"
    assert result.product.brand == "Acme"
    assert result.product.price is not None
    assert result.product.price.amount == 89.99
    assert result.product.price.currency == "USD"
    assert result.product.availability.value == "in_stock"
    assert result.product.sku == "SNK-001"
    assert result.product.rating == 4.6
    assert result.product.review_count == 128
    assert result.product.image_urls == ["https://example.com/images/sneaker.jpg"]
    assert result.confidence > 0.8


def test_extract_product_from_dom_fallback() -> None:
    html = """
    <html>
      <body>
        <h1 class="product-title">Fallback Product</h1>
        <span class="price">$42.50</span>
        <p class="availability">In stock</p>
        <img src="/fallback.jpg" />
      </body>
    </html>
    """
    result = extract_product_from_html(html, url="https://example.com/fallback")

    assert result.product.name == "Fallback Product"
    assert result.product.price is not None
    assert result.product.price.amount == 42.5
    assert result.product.availability.value == "in_stock"
    assert result.product.image_urls == ["https://example.com/fallback.jpg"]


def test_extract_product_from_shopify_adapter() -> None:
    html = """
    <html>
      <head>
        <script>
          ShopifyAnalytics = {meta: {}};
          ShopifyAnalytics.meta.product = {
            "id": 123,
            "title": "Shopify Jacket",
            "vendor": "Northwind",
            "currency": "USD",
            "featured_image": "//cdn.shopify.com/jacket.jpg",
            "variants": [
              {"id": 456, "sku": "JKT-001", "price": 12999, "available": true}
            ]
          };
        </script>
      </head>
      <body></body>
    </html>
    """

    result = extract_product_from_html(html, url="https://store.example.com/products/jacket")

    assert result.product.name == "Shopify Jacket"
    assert result.product.brand == "Northwind"
    assert result.product.sku == "JKT-001"
    assert result.product.price is not None
    assert result.product.price.amount == 129.99
    assert result.product.price.currency == "USD"
    assert result.product.availability.value == "in_stock"
    assert result.product.metadata["adapter"] == "shopify"
    assert result.fields["price"].source == "shopify_adapter"
