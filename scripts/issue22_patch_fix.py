from pathlib import Path

path = Path("commercelens/api/customer_insights.py")
text = path.read_text()
old = 'export_url = f"/portal/export/products/{esc(product.id)}/comparison?project_id={esc(selected.id)}"'
new = 'export_url = f"/portal/export/products/{esc(comparison.product.id)}/comparison?project_id={esc(selected.id)}"'
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise RuntimeError("Comparison export URL anchor not found")
path.write_text(text)
