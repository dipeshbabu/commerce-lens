from pathlib import Path

replacements = {
    "commercelens/api/customer_insights.py": [
        ("/portal/export/changes", "/portal/insights/export/changes"),
    ],
    "tests/test_customer_insights.py": [
        ("/portal/export/changes", "/portal/insights/export/changes"),
    ],
    "docs/customer_portal.md": [
        ("/portal/export/changes", "/portal/insights/export/changes"),
    ],
}

for filename, pairs in replacements.items():
    path = Path(filename)
    text = path.read_text()
    for old, new in pairs:
        if old in text:
            text = text.replace(old, new)
        elif new not in text:
            raise RuntimeError(f"Export route anchor not found in {filename}")
    path.write_text(text)
