from __future__ import annotations

from pydantic import BaseModel, Field


class NotionPage(BaseModel):
    id: str
    title: str = ""
    url: str = ""
    parent_id: str = ""
    object_type: str = "page"
    properties: dict[str, object] = Field(default_factory=dict)


class NotionDatabase(BaseModel):
    id: str
    title: str = ""
    url: str = ""
    parent_id: str = ""


class DatabaseRow(BaseModel):
    id: str
    properties: dict[str, object] = Field(default_factory=dict)
