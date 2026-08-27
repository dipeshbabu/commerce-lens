from pathlib import Path

path = Path("commercelens/api/customer_insights.py")
text = path.read_text()

old_import = '''    ChangeFeedEntry,
    ChangeFeedFilters,
    ProductComparison,
'''
new_import = '''    ChangeFeedEntry,
    ChangeFeedFilters,
    EquivalentProduct,
    OfferComparison,
    ProductComparison,
'''
if old_import in text:
    text = text.replace(old_import, new_import, 1)
elif new_import not in text:
    raise RuntimeError("Insight type import anchor not found")

old_block = '''    all_offers = [(None, item) for item in comparison.offers]
    for equivalent in comparison.equivalent_products:
        all_offers.extend((equivalent, item) for item in equivalent.offers)
    offer_rows: list[list[object]] = []
    for equivalent, view in all_offers:
        observation = view.latest_observation
        match = equivalent.match if equivalent else None
        relation = "direct"
        if equivalent and match:
'''
new_block = '''    all_offers: list[tuple[EquivalentProduct | None, OfferComparison]] = [
        (None, item) for item in comparison.offers
    ]
    for equivalent_product in comparison.equivalent_products:
        all_offers.extend(
            (equivalent_product, item) for item in equivalent_product.offers
        )
    offer_rows: list[list[object]] = []
    for related_product, view in all_offers:
        observation = view.latest_observation
        match = related_product.match if related_product else None
        relation = "direct"
        if related_product and match:
'''
if old_block in text:
    text = text.replace(old_block, new_block, 1)
elif new_block not in text:
    raise RuntimeError("Offer comparison typing anchor not found")

path.write_text(text)
