from commercelens.extractors.listing import extract_listing_from_html


HTML = """
<html>
  <body>
    <article class="product_pod">
      <div class="image_container"><a href="catalogue/a-light/index.html"><img src="media/book.jpg" /></a></div>
      <h3><a href="catalogue/a-light/index.html" title="A Light in the Attic">A Light in the Attic</a></h3>
      <p class="price_color">£51.77</p>
      <p class="instock availability">In stock</p>
    </article>
    <article class="product_pod">
      <h3><a href="catalogue/tipping/index.html" title="Tipping the Velvet">Tipping the Velvet</a></h3>
      <p class="price_color">£53.74</p>
      <p class="instock availability">In stock</p>
    </article>
    <li class="next"><a href="page-2.html">next</a></li>
  </body>
</html>
"""


def test_extract_listing_products() -> None:
    result = extract_listing_from_html(HTML, url="https://books.toscrape.com/catalogue/page-1.html")

    assert result.product_count == 2
    assert result.products[0].name == "A Light in the Attic"
    assert result.products[0].url == "https://books.toscrape.com/catalogue/a-light/index.html"
    assert result.products[0].price is not None
    assert result.products[0].price.amount == 51.77
    assert result.products[0].price.currency == "GBP"
    assert result.products[0].availability == "in_stock"
    assert result.products[0].image_url == "https://books.toscrape.com/catalogue/media/book.jpg"
    assert result.next_page_url == "https://books.toscrape.com/catalogue/page-2.html"
    assert result.confidence > 0.7
