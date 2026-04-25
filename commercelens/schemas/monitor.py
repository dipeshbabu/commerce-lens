from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class MonitorProductRequest(BaseModel):
    url: HttpUrl
    db_path: str = "commercelens.db"
    render: bool = False


class MonitorBatchRequest(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=100)
    db_path: str = "commercelens.db"
    render: bool = False


class PriceHistoryRequest(BaseModel):
    product_key: str | None = None
    url: HttpUrl | None = None
    db_path: str = "commercelens.db"
    limit: int = Field(default=100, ge=1, le=1000)
