from __future__ import annotations

import hashlib
from collections import defaultdict
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from commercelens.connectors.datasets import ProductRecord
from commercelens.matching.products import normalize_text, product_similarity


class ProductIdentityEdge(BaseModel):
    left_index: int
    right_index: int
    score: float
    reasons: list[str] = Field(default_factory=list)


class ProductIdentityCluster(BaseModel):
    id: str
    record_indexes: list[int] = Field(default_factory=list)
    records: list[ProductRecord] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    representative_name: str | None = None
    representative_brand: str | None = None
    currency: str | None = None
    min_amount: float | None = None
    max_amount: float | None = None


class ProductIdentityGraph(BaseModel):
    clusters: list[ProductIdentityCluster] = Field(default_factory=list)
    edges: list[ProductIdentityEdge] = Field(default_factory=list)


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def build_identity_graph(
    records: list[ProductRecord],
    threshold: float = 0.72,
) -> ProductIdentityGraph:
    union_find = _UnionFind(len(records))
    edges: list[ProductIdentityEdge] = []

    for left_index, left in enumerate(records):
        for right_index in range(left_index + 1, len(records)):
            right = records[right_index]
            score, reasons = product_similarity(left, right)
            if score >= threshold:
                union_find.union(left_index, right_index)
                edges.append(
                    ProductIdentityEdge(
                        left_index=left_index,
                        right_index=right_index,
                        score=score,
                        reasons=reasons,
                    )
                )

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        groups[union_find.find(index)].append(index)

    clusters = [
        _cluster_from_indexes(indexes, records)
        for indexes in groups.values()
    ]
    clusters.sort(key=lambda cluster: (-len(cluster.records), cluster.id))
    return ProductIdentityGraph(clusters=clusters, edges=edges)


def _cluster_from_indexes(indexes: list[int], records: list[ProductRecord]) -> ProductIdentityCluster:
    cluster_records = [records[index] for index in indexes]
    domains = sorted({_domain(record.url) for record in cluster_records if _domain(record.url)})
    amounts = [record.amount for record in cluster_records if record.amount is not None]
    currencies = [record.currency for record in cluster_records if record.currency]
    representative = max(cluster_records, key=lambda record: len(record.name or ""))
    return ProductIdentityCluster(
        id=_cluster_id(cluster_records),
        record_indexes=indexes,
        records=cluster_records,
        domains=domains,
        representative_name=representative.name,
        representative_brand=representative.brand,
        currency=currencies[0].upper() if currencies else None,
        min_amount=min(amounts) if amounts else None,
        max_amount=max(amounts) if amounts else None,
    )


def _cluster_id(records: list[ProductRecord]) -> str:
    parts = sorted(
        f"{normalize_text(record.brand)}:{normalize_text(record.name)}:{record.product_key or ''}"
        for record in records
    )
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"pid_{digest}"


def _domain(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower().removeprefix("www.")
