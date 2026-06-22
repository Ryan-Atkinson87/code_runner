from __future__ import annotations

import re
import time
from typing import Any

import httpx

from app.notion.errors import NotionAuthError, NotionError, NotionRateLimitError
from app.notion.models import DatabaseRow, NotionDatabase, NotionPage

_NOTION_VERSION = "2022-06-28"
_RATE_LIMIT_BACKOFF_SECONDS = 60

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}",
    re.IGNORECASE,
)


def normalize_ref(ref: str) -> str:
    """Extract a bare page/database id from a full Notion URL or bare id."""
    match = _UUID_RE.search(ref)
    if not match:
        raise NotionError(f"Cannot extract a Notion id from ref: {ref!r}")
    raw = match.group(0)
    return raw if "-" in raw else f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


class NotionClient:
    def __init__(self, token: str, api_base: str = "https://api.notion.com") -> None:
        self._http = httpx.Client(
            base_url=api_base,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": _NOTION_VERSION,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> NotionClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._http.request(method, path, **kwargs)
        if response.status_code in (401, 403):
            raise NotionAuthError(
                f"Notion authentication failed: {response.status_code} {response.text}",
                status_code=response.status_code,
            )
        if response.status_code == 429:
            raise NotionRateLimitError(
                "Notion rate limit hit (429). Back off before retrying.",
                status_code=429,
            )
        if response.status_code >= 400:
            raise NotionError(
                f"Notion API error: {response.status_code} {response.text}",
                status_code=response.status_code,
            )
        return response

    def _request_with_backoff(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._request(method, path, **kwargs)
        except NotionRateLimitError:
            time.sleep(_RATE_LIMIT_BACKOFF_SECONDS)
            return self._request(method, path, **kwargs)

    # ── Pages ──────────────────────────────────────────────────────────

    def get_page(self, page_ref: str) -> NotionPage:
        page_id = normalize_ref(page_ref)
        resp = self._request_with_backoff("GET", f"/v1/pages/{page_id}")
        return self._parse_page(resp.json())

    def update_page(self, page_ref: str, properties: dict[str, Any]) -> NotionPage:
        page_id = normalize_ref(page_ref)
        resp = self._request_with_backoff(
            "PATCH", f"/v1/pages/{page_id}", json={"properties": properties}
        )
        return self._parse_page(resp.json())

    def get_block_children(self, block_ref: str) -> list[dict[str, Any]]:
        block_id = normalize_ref(block_ref)
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, str] = {"page_size": "100"}
            if cursor:
                params["start_cursor"] = cursor
            resp = self._request_with_backoff(
                "GET", f"/v1/blocks/{block_id}/children", params=params
            )
            data = resp.json()
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return results

    def replace_block_children(
        self, block_ref: str, children: list[dict[str, Any]]
    ) -> None:
        block_id = normalize_ref(block_ref)
        existing = self.get_block_children(block_ref)
        for block in existing:
            self._request_with_backoff("DELETE", f"/v1/blocks/{block['id']}")
        if children:
            for batch_start in range(0, len(children), 100):
                batch = children[batch_start : batch_start + 100]
                self._request_with_backoff(
                    "PATCH",
                    f"/v1/blocks/{block_id}/children",
                    json={"children": batch},
                )

    # ── Databases ──────────────────────────────────────────────────────

    def get_database(self, db_ref: str) -> NotionDatabase:
        db_id = normalize_ref(db_ref)
        resp = self._request_with_backoff("GET", f"/v1/databases/{db_id}")
        return self._parse_database(resp.json())

    def query_database(
        self,
        db_ref: str,
        filter_obj: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
    ) -> list[DatabaseRow]:
        db_id = normalize_ref(db_ref)
        results: list[DatabaseRow] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if filter_obj:
                body["filter"] = filter_obj
            if sorts:
                body["sorts"] = sorts
            if cursor:
                body["start_cursor"] = cursor
            resp = self._request_with_backoff("POST", f"/v1/databases/{db_id}/query", json=body)
            data = resp.json()
            for row in data.get("results", []):
                results.append(DatabaseRow(id=row["id"], properties=row.get("properties", {})))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return results

    def create_database_row(
        self, db_ref: str, properties: dict[str, Any]
    ) -> DatabaseRow:
        db_id = normalize_ref(db_ref)
        resp = self._request_with_backoff(
            "POST",
            "/v1/pages",
            json={"parent": {"database_id": db_id}, "properties": properties},
        )
        data = resp.json()
        return DatabaseRow(id=data["id"], properties=data.get("properties", {}))

    def update_database_row(
        self, row_ref: str, properties: dict[str, Any]
    ) -> DatabaseRow:
        row_id = normalize_ref(row_ref)
        resp = self._request_with_backoff(
            "PATCH", f"/v1/pages/{row_id}", json={"properties": properties}
        )
        data = resp.json()
        return DatabaseRow(id=data["id"], properties=data.get("properties", {}))

    # ── Auto-discovery ─────────────────────────────────────────────────

    def discover_databases(self, dashboard_page_ref: str) -> dict[str, NotionDatabase]:
        children = self.get_block_children(dashboard_page_ref)
        found: dict[str, NotionDatabase] = {}
        for block in children:
            if block.get("type") == "child_database":
                db = self.get_database(block["id"])
                title_lower = db.title.lower()
                if "technical" in title_lower and "task" in title_lower:
                    found["technical_tasks"] = db
                elif "user" in title_lower and ("story" in title_lower or "stories" in title_lower):
                    found["user_stories"] = db
        return found

    # ── Parsing ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_page(data: dict[str, Any]) -> NotionPage:
        title = ""
        for prop in data.get("properties", {}).values():
            if prop.get("type") == "title":
                title_parts = prop.get("title", [])
                title = "".join(part.get("plain_text", "") for part in title_parts)
                break
        parent = data.get("parent", {})
        parent_id = parent.get("page_id") or parent.get("database_id") or ""
        return NotionPage(
            id=data["id"],
            title=title,
            url=data.get("url", ""),
            parent_id=parent_id,
            object_type=data.get("object", "page"),
            properties=data.get("properties", {}),
        )

    @staticmethod
    def _parse_database(data: dict[str, Any]) -> NotionDatabase:
        title_parts = data.get("title", [])
        title = "".join(part.get("plain_text", "") for part in title_parts)
        parent = data.get("parent", {})
        parent_id = parent.get("page_id") or parent.get("database_id") or ""
        return NotionDatabase(
            id=data["id"],
            title=title,
            url=data.get("url", ""),
            parent_id=parent_id,
        )
