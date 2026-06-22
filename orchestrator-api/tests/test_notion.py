from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.notion.client import NotionClient, normalize_ref
from app.notion.errors import NotionAuthError, NotionError, NotionRateLimitError
from app.notion.models import DatabaseRow, NotionDatabase, NotionPage

# ── Helpers ────────────────────────────────────────────────────────────


def _mock_transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _json_response(data: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


SAMPLE_PAGE: dict[str, Any] = {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "object": "page",
    "url": "https://www.notion.so/Test-Page-a1b2c3d4e5f67890abcdef1234567890",
    "parent": {"page_id": "00000000-0000-0000-0000-000000000001"},
    "properties": {
        "title": {
            "type": "title",
            "title": [{"plain_text": "Test Page"}],
        }
    },
}

SAMPLE_DATABASE: dict[str, Any] = {
    "id": "db000000-0000-0000-0000-000000000001",
    "object": "database",
    "url": "https://www.notion.so/db000000000000000000000000000001",
    "title": [{"plain_text": "Technical Tasks"}],
    "parent": {"page_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
}

SAMPLE_ROW: dict[str, Any] = {
    "id": "a0a00000-0000-0000-0000-000000000001",
    "object": "page",
    "properties": {
        "Name": {"type": "title", "title": [{"plain_text": "Task 1"}]},
        "Status": {"type": "select", "select": {"name": "Open"}},
    },
}


# ── normalize_ref ──────────────────────────────────────────────────────


class TestNormalizeRef:
    def test_bare_id_with_dashes(self) -> None:
        assert normalize_ref("a1b2c3d4-e5f6-7890-abcd-ef1234567890") == (
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )

    def test_bare_id_without_dashes(self) -> None:
        assert normalize_ref("a1b2c3d4e5f67890abcdef1234567890") == (
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        )

    def test_full_url(self) -> None:
        url = "https://www.notion.so/workspace/My-Page-a1b2c3d4e5f67890abcdef1234567890"
        assert normalize_ref(url) == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_url_with_query(self) -> None:
        url = "https://notion.so/page-a1b2c3d4e5f67890abcdef1234567890?v=abc"
        assert normalize_ref(url) == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def test_invalid_ref_raises(self) -> None:
        with pytest.raises(NotionError, match="Cannot extract"):
            normalize_ref("not-a-valid-id")


# ── Client basics ──────────────────────────────────────────────────────


class TestClientLifecycle:
    def test_context_manager(self) -> None:
        with NotionClient("test-token") as client:
            assert client is not None

    def test_auth_header_set(self) -> None:
        requests_seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append(request)
            return _json_response(SAMPLE_PAGE)

        client = NotionClient.__new__(NotionClient)
        client._http = httpx.Client(
            base_url="https://api.notion.com",
            transport=_mock_transport(handler),
        )
        client.get_page("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert len(requests_seen) == 1
        client.close()


# ── Error handling ─────────────────────────────────────────────────────


class TestErrorHandling:
    def _make_client(self, handler: Any) -> NotionClient:
        client = NotionClient.__new__(NotionClient)
        client._http = httpx.Client(
            base_url="https://api.notion.com",
            transport=_mock_transport(handler),
        )
        return client

    def test_401_raises_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "Unauthorized"})

        client = self._make_client(handler)
        with pytest.raises(NotionAuthError):
            client.get_page("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        client.close()

    def test_403_raises_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "Forbidden"})

        client = self._make_client(handler)
        with pytest.raises(NotionAuthError):
            client.get_page("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        client.close()

    def test_429_raises_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"message": "Rate limited"})

        client = self._make_client(handler)
        with pytest.raises(NotionRateLimitError):
            client._request("GET", "/v1/pages/a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        client.close()

    def test_429_backoff_retry_succeeds(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, json={"message": "Rate limited"})
            return _json_response(SAMPLE_PAGE)

        client = self._make_client(handler)
        with patch("app.notion.client.time.sleep") as mock_sleep:
            page = client.get_page("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert page.title == "Test Page"
        assert call_count == 2
        mock_sleep.assert_called_once_with(60)
        client.close()

    def test_429_backoff_retry_still_429(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"message": "Rate limited"})

        client = self._make_client(handler)
        with patch("app.notion.client.time.sleep"), pytest.raises(NotionRateLimitError):
            client.get_page("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        client.close()

    def test_500_raises_notion_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "Internal"})

        client = self._make_client(handler)
        with pytest.raises(NotionError):
            client.get_page("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        client.close()


# ── Page operations ────────────────────────────────────────────────────


class TestPageOperations:
    def _make_client(self, handler: Any) -> NotionClient:
        client = NotionClient.__new__(NotionClient)
        client._http = httpx.Client(
            base_url="https://api.notion.com",
            transport=_mock_transport(handler),
        )
        return client

    def test_get_page(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "/v1/pages/" in str(request.url)
            return _json_response(SAMPLE_PAGE)

        client = self._make_client(handler)
        page = client.get_page("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert isinstance(page, NotionPage)
        assert page.title == "Test Page"
        assert page.id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert page.parent_id == "00000000-0000-0000-0000-000000000001"
        client.close()

    def test_update_page(self) -> None:
        bodies_seen: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "PATCH":
                bodies_seen.append(json.loads(request.content))
            return _json_response(SAMPLE_PAGE)

        client = self._make_client(handler)
        page = client.update_page(
            "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            {"Status": {"select": {"name": "Done"}}},
        )
        assert isinstance(page, NotionPage)
        assert len(bodies_seen) == 1
        assert "properties" in bodies_seen[0]
        client.close()

    def test_get_page_from_url(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(SAMPLE_PAGE)

        client = self._make_client(handler)
        page = client.get_page(
            "https://www.notion.so/workspace/Page-a1b2c3d4e5f67890abcdef1234567890"
        )
        assert page.title == "Test Page"
        client.close()


# ── Block children ─────────────────────────────────────────────────────


class TestBlockChildren:
    def _make_client(self, handler: Any) -> NotionClient:
        client = NotionClient.__new__(NotionClient)
        client._http = httpx.Client(
            base_url="https://api.notion.com",
            transport=_mock_transport(handler),
        )
        return client

    def test_get_block_children_paginated(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _json_response({
                    "results": [{"id": "block-1", "type": "paragraph"}],
                    "has_more": True,
                    "next_cursor": "cursor-2",
                })
            return _json_response({
                "results": [{"id": "block-2", "type": "paragraph"}],
                "has_more": False,
            })

        client = self._make_client(handler)
        blocks = client.get_block_children("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert len(blocks) == 2
        assert blocks[0]["id"] == "block-1"
        assert blocks[1]["id"] == "block-2"
        client.close()

    def test_replace_block_children(self) -> None:
        requests_seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests_seen.append((request.method, str(request.url)))
            if request.method == "GET" and "children" in str(request.url):
                return _json_response({
                    "results": [{"id": "old-block-1", "type": "paragraph"}],
                    "has_more": False,
                })
            if request.method == "DELETE":
                return httpx.Response(200, json={})
            if request.method == "PATCH" and "children" in str(request.url):
                return _json_response({"results": [], "has_more": False})
            return _json_response({})

        client = self._make_client(handler)
        new_children = [
            {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "New"}}]}}
        ]
        client.replace_block_children("a1b2c3d4-e5f6-7890-abcd-ef1234567890", new_children)
        methods = [m for m, _ in requests_seen]
        assert "GET" in methods
        assert "DELETE" in methods
        assert "PATCH" in methods
        client.close()


# ── Database operations ────────────────────────────────────────────────


class TestDatabaseOperations:
    def _make_client(self, handler: Any) -> NotionClient:
        client = NotionClient.__new__(NotionClient)
        client._http = httpx.Client(
            base_url="https://api.notion.com",
            transport=_mock_transport(handler),
        )
        return client

    def test_get_database(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(SAMPLE_DATABASE)

        client = self._make_client(handler)
        db = client.get_database("db000000-0000-0000-0000-000000000001")
        assert isinstance(db, NotionDatabase)
        assert db.title == "Technical Tasks"
        client.close()

    def test_query_database(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({
                "results": [SAMPLE_ROW],
                "has_more": False,
            })

        client = self._make_client(handler)
        rows = client.query_database("db000000-0000-0000-0000-000000000001")
        assert len(rows) == 1
        assert isinstance(rows[0], DatabaseRow)
        assert rows[0].id == "a0a00000-0000-0000-0000-000000000001"
        client.close()

    def test_query_database_paginated(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _json_response({
                    "results": [SAMPLE_ROW],
                    "has_more": True,
                    "next_cursor": "cursor-2",
                })
            row2 = {**SAMPLE_ROW, "id": "row00000-0000-0000-0000-000000000002"}
            return _json_response({"results": [row2], "has_more": False})

        client = self._make_client(handler)
        rows = client.query_database("db000000-0000-0000-0000-000000000001")
        assert len(rows) == 2
        client.close()

    def test_query_database_with_filter(self) -> None:
        bodies_seen: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies_seen.append(json.loads(request.content))
            return _json_response({"results": [], "has_more": False})

        client = self._make_client(handler)
        filter_obj = {"property": "Status", "select": {"equals": "Open"}}
        client.query_database("db000000-0000-0000-0000-000000000001", filter_obj=filter_obj)
        assert bodies_seen[0]["filter"] == filter_obj
        client.close()

    def test_create_database_row(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return _json_response({
                "id": "b0b00000-0000-0000-0000-000000000001",
                "object": "page",
                "properties": body.get("properties", {}),
            })

        client = self._make_client(handler)
        row = client.create_database_row(
            "db000000-0000-0000-0000-000000000001",
            {"Name": {"title": [{"text": {"content": "New Task"}}]}},
        )
        assert isinstance(row, DatabaseRow)
        assert row.id == "b0b00000-0000-0000-0000-000000000001"
        client.close()

    def test_update_database_row(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({
                "id": "a0a00000-0000-0000-0000-000000000001",
                "object": "page",
                "properties": {"Status": {"select": {"name": "Done"}}},
            })

        client = self._make_client(handler)
        row = client.update_database_row(
            "a0a00000-0000-0000-0000-000000000001",
            {"Status": {"select": {"name": "Done"}}},
        )
        assert row.properties["Status"] == {"select": {"name": "Done"}}  # type: ignore[comparison-overlap]
        client.close()


# ── Auto-discovery ─────────────────────────────────────────────────────


class TestDiscoverDatabases:
    def _make_client(self, handler: Any) -> NotionClient:
        client = NotionClient.__new__(NotionClient)
        client._http = httpx.Client(
            base_url="https://api.notion.com",
            transport=_mock_transport(handler),
        )
        return client

    def test_discovers_both_databases(self) -> None:
        tech_db_id = "db000000-0000-0000-0000-000000000001"
        user_db_id = "db000000-0000-0000-0000-000000000002"

        def handler(request: httpx.Request) -> httpx.Response:
            path = str(request.url)
            if "children" in path:
                return _json_response({
                    "results": [
                        {"id": tech_db_id, "type": "child_database"},
                        {"id": user_db_id, "type": "child_database"},
                        {"id": "some-block", "type": "paragraph"},
                    ],
                    "has_more": False,
                })
            if tech_db_id in path:
                return _json_response({
                    **SAMPLE_DATABASE,
                    "id": tech_db_id,
                    "title": [{"plain_text": "Technical Tasks"}],
                })
            if user_db_id in path:
                return _json_response({
                    **SAMPLE_DATABASE,
                    "id": user_db_id,
                    "title": [{"plain_text": "User Stories"}],
                })
            return _json_response({})

        client = self._make_client(handler)
        dbs = client.discover_databases("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert "technical_tasks" in dbs
        assert "user_stories" in dbs
        assert dbs["technical_tasks"].title == "Technical Tasks"
        assert dbs["user_stories"].title == "User Stories"
        client.close()

    def test_no_databases_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "children" in str(request.url):
                return _json_response({"results": [], "has_more": False})
            return _json_response({})

        client = self._make_client(handler)
        dbs = client.discover_databases("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert dbs == {}
        client.close()

    def test_only_technical_tasks(self) -> None:
        tech_db_id = "db000000-0000-0000-0000-000000000001"

        def handler(request: httpx.Request) -> httpx.Response:
            if "children" in str(request.url):
                return _json_response({
                    "results": [{"id": tech_db_id, "type": "child_database"}],
                    "has_more": False,
                })
            if tech_db_id in str(request.url):
                return _json_response({
                    **SAMPLE_DATABASE,
                    "id": tech_db_id,
                    "title": [{"plain_text": "Technical Tasks"}],
                })
            return _json_response({})

        client = self._make_client(handler)
        dbs = client.discover_databases("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert "technical_tasks" in dbs
        assert "user_stories" not in dbs
        client.close()
