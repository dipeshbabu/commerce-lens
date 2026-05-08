from __future__ import annotations

from pydantic import BaseModel, Field

from commercelens.connectors.datasets import ProductRecord
from commercelens.matching.products import normalize_text


class CatalogChange(BaseModel):
    key: str
    kind: str
    before: ProductRecord | None = None
    after: ProductRecord | None = None
    fields: dict[str, dict[str, object | None]] = Field(default_factory=dict)


class CatalogDiffResult(BaseModel):
    added: list[CatalogChange] = Field(default_factory=list)
    removed: list[CatalogChange] = Field(default_factory=list)
    changed: list[CatalogChange] = Field(default_factory=list)
    total_changes: int = 0


def diff_catalogs(before: list[ProductRecord], after: list[ProductRecord]) -> CatalogDiffResult:
    before_map = {_identity_key(record): record for record in before}
    after_map = {_identity_key(record): record for record in after}

    result = CatalogDiffResult()
    for key in sorted(after_map.keys() - before_map.keys()):
        result.added.append(CatalogChange(key=key, kind="added", after=after_map[key]))
    for key in sorted(before_map.keys() - after_map.keys()):
        result.removed.append(CatalogChange(key=key, kind="removed", before=before_map[key]))
    for key in sorted(before_map.keys() & after_map.keys()):
        fields = _changed_fields(before_map[key], after_map[key])
        if fields:
            result.changed.append(
                CatalogChange(
                    key=key,
                    kind="changed",
                    before=before_map[key],
                    after=after_map[key],
                    fields=fields,
                )
            )
    result.total_changes = len(result.added) + len(result.removed) + len(result.changed)
    return result


def _identity_key(record: ProductRecord) -> str:
    if record.product_key:
        return f"product_key:{record.product_key}"
    if record.url:
        return f"url:{record.url.lower().rstrip('/')}"
    return f"name:{normalize_text(record.brand)}:{normalize_text(record.name)}"


def _changed_fields(before: ProductRecord, after: ProductRecord) -> dict[str, dict[str, object | None]]:
    fields: dict[str, dict[str, object | None]] = {}
    for name in ("amount", "currency", "availability", "name", "brand", "image_url"):
        before_value = getattr(before, name)
        after_value = getattr(after, name)
        if before_value != after_value:
            fields[name] = {"before": before_value, "after": after_value}
    return fields
