from __future__ import annotations

from pydantic import BaseModel, Field

from commercelens.connectors.datasets import ProductRecord


class MatchProductsRequest(BaseModel):
    left: list[ProductRecord] = Field(default_factory=list)
    right: list[ProductRecord] = Field(default_factory=list)
    threshold: float = 0.72
    top_k: int = 1


class ProductIdentityGraphRequest(BaseModel):
    records: list[ProductRecord] = Field(default_factory=list)
    threshold: float = 0.72


class CatalogDiffRequest(BaseModel):
    before: list[ProductRecord] = Field(default_factory=list)
    after: list[ProductRecord] = Field(default_factory=list)


class PriceSummaryRequest(BaseModel):
    records: list[ProductRecord] = Field(default_factory=list)


class NormalizeRecordsRequest(BaseModel):
    records: list[ProductRecord] = Field(default_factory=list)
