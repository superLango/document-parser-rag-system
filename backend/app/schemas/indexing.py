"""S6 检索 Schema。"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class SearchFiltersIn(BaseModel):
    document_id: uuid.UUID | None = None
    has_table: bool | None = None
    level: int | None = Field(default=None, ge=1, le=9)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    filters: SearchFiltersIn | None = None


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    parent_text: str | None = None
    hierarchy_path: str = ""
    title: str = ""
    source_pages: list = []
    has_table: bool = False
    score: float = 0.0


class SearchResponse(BaseModel):
    query: str
    total: int
    items: list[SearchHit]
