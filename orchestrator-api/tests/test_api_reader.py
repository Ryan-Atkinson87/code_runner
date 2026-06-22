from __future__ import annotations

import pytest

from app.usage.api_reader import ApiUsageReader, _build_meters
from app.usage.models import MeterKind


def _full_headers() -> dict[str, str]:
    return {
        "anthropic-ratelimit-tokens-remaining": "40000",
        "anthropic-ratelimit-tokens-limit": "100000",
        "anthropic-ratelimit-tokens-reset": "1750000000",
        "anthropic-ratelimit-requests-remaining": "80",
        "anthropic-ratelimit-requests-limit": "100",
        "anthropic-ratelimit-requests-reset": "1750001000",
    }


class TestBuildMeters:
    def test_full_headers(self) -> None:
        parsed = {
            "tokens_remaining": 40000.0,
            "tokens_limit": 100000.0,
            "tokens_reset": 1750000000.0,
            "requests_remaining": 80.0,
            "requests_limit": 100.0,
            "requests_reset": 1750001000.0,
        }
        meters = _build_meters(parsed)
        by_kind = {m.kind: m for m in meters}

        assert MeterKind.API_BUDGET in by_kind
        budget = by_kind[MeterKind.API_BUDGET]
        assert budget.utilisation == 60.0
        assert budget.limit == 100000.0
        assert budget.used == 60000.0
        assert budget.resets_at == 1750000000.0

        assert "api_requests" in by_kind
        requests = by_kind["api_requests"]
        assert requests.utilisation == 20.0
        assert requests.limit == 100.0
        assert requests.used == 20.0

    def test_tokens_only(self) -> None:
        parsed = {"tokens_remaining": 50000.0, "tokens_limit": 100000.0}
        meters = _build_meters(parsed)
        assert len(meters) == 1
        assert meters[0].kind == MeterKind.API_BUDGET
        assert meters[0].utilisation == 50.0

    def test_requests_only(self) -> None:
        parsed = {"requests_remaining": 10.0, "requests_limit": 100.0}
        meters = _build_meters(parsed)
        assert len(meters) == 1
        assert meters[0].kind == "api_requests"

    def test_empty_parsed(self) -> None:
        meters = _build_meters({})
        assert meters == []

    def test_zero_limit_skipped(self) -> None:
        parsed = {"tokens_remaining": 0.0, "tokens_limit": 0.0}
        meters = _build_meters(parsed)
        assert meters == []

    def test_fully_exhausted(self) -> None:
        parsed = {"tokens_remaining": 0.0, "tokens_limit": 100000.0}
        meters = _build_meters(parsed)
        assert meters[0].utilisation == 100.0
        assert meters[0].used == 100000.0


class TestApiUsageReader:
    @pytest.mark.anyio
    async def test_read_before_update_returns_empty(self) -> None:
        reader = ApiUsageReader("claude", "api")
        snapshot = await reader.read()
        assert snapshot.meters == []
        assert snapshot.provider == "claude"
        assert snapshot.plan == "api"

    @pytest.mark.anyio
    async def test_update_then_read(self) -> None:
        reader = ApiUsageReader("claude", "api")
        reader.update_from_headers(_full_headers())

        snapshot = await reader.read()
        assert len(snapshot.meters) == 2
        by_kind = {m.kind: m for m in snapshot.meters}
        assert MeterKind.API_BUDGET in by_kind
        assert by_kind[MeterKind.API_BUDGET].utilisation == 60.0

    @pytest.mark.anyio
    async def test_update_overwrites_previous(self) -> None:
        reader = ApiUsageReader("claude", "api")
        reader.update_from_headers(_full_headers())

        new_headers = {
            "anthropic-ratelimit-tokens-remaining": "10000",
            "anthropic-ratelimit-tokens-limit": "100000",
        }
        reader.update_from_headers(new_headers)

        snapshot = await reader.read()
        by_kind = {m.kind: m for m in snapshot.meters}
        assert by_kind[MeterKind.API_BUDGET].utilisation == 90.0

    @pytest.mark.anyio
    async def test_missing_headers_degrade_gracefully(self) -> None:
        reader = ApiUsageReader("claude", "api")
        reader.update_from_headers({})

        snapshot = await reader.read()
        assert snapshot.meters == []

    @pytest.mark.anyio
    async def test_unparseable_header_skipped(self) -> None:
        reader = ApiUsageReader("claude", "api")
        headers = {
            "anthropic-ratelimit-tokens-remaining": "not-a-number",
            "anthropic-ratelimit-tokens-limit": "100000",
        }
        reader.update_from_headers(headers)

        snapshot = await reader.read()
        assert snapshot.meters == []

    @pytest.mark.anyio
    async def test_partial_headers(self) -> None:
        reader = ApiUsageReader("claude", "api")
        headers = {
            "anthropic-ratelimit-tokens-remaining": "30000",
            "anthropic-ratelimit-tokens-limit": "100000",
        }
        reader.update_from_headers(headers)

        snapshot = await reader.read()
        assert len(snapshot.meters) == 1
        assert snapshot.meters[0].kind == MeterKind.API_BUDGET
        assert snapshot.meters[0].utilisation == 70.0
