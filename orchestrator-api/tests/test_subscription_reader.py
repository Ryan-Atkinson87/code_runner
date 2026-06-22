from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.usage.models import MeterKind
from app.usage.subscription import (
    FallbackLevel,
    SubscriptionUsageReader,
    _parse_oauth_response,
)


def _oauth_response() -> dict[str, object]:
    return {
        "five_hour": {
            "utilization": 35.0,
            "resets_at": 1750000000.0,
        },
        "seven_day": {
            "utilization": 60.0,
            "resets_at": 1750100000.0,
        },
        "seven_day_opus": {
            "utilization": 70.0,
            "resets_at": 1750100000.0,
        },
        "seven_day_sonnet": {
            "utilization": 20.0,
            "resets_at": 1750100000.0,
        },
        "extra_usage": {
            "is_enabled": True,
            "monthly_limit": 100.0,
            "used_credits": 45.0,
            "utilization": 45.0,
        },
    }


class TestParseOAuthResponse:
    def test_normal_parse(self) -> None:
        data = _oauth_response()
        meters = _parse_oauth_response(data)
        by_kind = {m.kind: m for m in meters}

        assert MeterKind.FIVE_HOUR in by_kind
        assert by_kind[MeterKind.FIVE_HOUR].utilisation == 35.0
        assert by_kind[MeterKind.FIVE_HOUR].resets_at == 1750000000.0

        assert MeterKind.SEVEN_DAY in by_kind
        assert by_kind[MeterKind.SEVEN_DAY].utilisation == 60.0

        assert MeterKind.SEVEN_DAY_OPUS in by_kind
        assert by_kind[MeterKind.SEVEN_DAY_OPUS].utilisation == 70.0

        assert MeterKind.SEVEN_DAY_SONNET in by_kind
        assert by_kind[MeterKind.SEVEN_DAY_SONNET].utilisation == 20.0

        assert MeterKind.AGENT_SDK_CREDIT in by_kind
        assert by_kind[MeterKind.AGENT_SDK_CREDIT].utilisation == 45.0
        assert by_kind[MeterKind.AGENT_SDK_CREDIT].limit == 100.0
        assert by_kind[MeterKind.AGENT_SDK_CREDIT].used == 45.0

    def test_missing_windows(self) -> None:
        data: dict[str, object] = {"five_hour": {"utilization": 50.0}}
        meters = _parse_oauth_response(data)
        assert len(meters) == 1
        assert meters[0].kind == MeterKind.FIVE_HOUR

    def test_extra_usage_disabled(self) -> None:
        data: dict[str, object] = {
            "five_hour": {"utilization": 30.0},
            "extra_usage": {"is_enabled": False},
        }
        meters = _parse_oauth_response(data)
        kinds = {m.kind for m in meters}
        assert MeterKind.AGENT_SDK_CREDIT not in kinds

    def test_unknown_meter_carried_through(self) -> None:
        data: dict[str, object] = {
            "five_hour": {"utilization": 30.0},
            "brand_new_meter": {"utilization": 88.0, "resets_at": 999.0},
        }
        meters = _parse_oauth_response(data)
        by_kind = {m.kind: m for m in meters}
        assert "brand_new_meter" in by_kind
        assert by_kind["brand_new_meter"].utilisation == 88.0
        assert by_kind["brand_new_meter"].resets_at == 999.0

    def test_endpoint_shape_change_non_dict_window(self) -> None:
        data: dict[str, object] = {
            "five_hour": "not_a_dict",
            "seven_day": {"utilization": 50.0},
        }
        meters = _parse_oauth_response(data)
        assert len(meters) == 1
        assert meters[0].kind == MeterKind.SEVEN_DAY

    def test_empty_response(self) -> None:
        meters = _parse_oauth_response({})
        assert meters == []

    def test_utilisation_british_spelling_fallback(self) -> None:
        data: dict[str, object] = {
            "five_hour": {"utilisation": 42.0},
        }
        meters = _parse_oauth_response(data)
        assert meters[0].utilisation == 42.0

    def test_limit_and_used_optional(self) -> None:
        data: dict[str, object] = {
            "five_hour": {"utilization": 30.0},
        }
        meters = _parse_oauth_response(data)
        assert meters[0].limit is None
        assert meters[0].used is None


class TestSubscriptionReaderOAuth:
    @pytest.mark.anyio
    async def test_successful_read(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(json.dumps({"accessToken": "test-token"}))

        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=_oauth_response(),
            )
        )
        client = httpx.AsyncClient(transport=transport)
        reader = SubscriptionUsageReader(
            creds, "claude", "pro", http_client=client
        )

        snapshot = await reader.read()
        assert snapshot.provider == "claude"
        assert snapshot.plan == "pro"
        assert len(snapshot.meters) == 5
        assert reader.fallback_level == FallbackLevel.OAUTH

    @pytest.mark.anyio
    async def test_caches_within_ttl(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(json.dumps({"accessToken": "test-token"}))

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=_oauth_response())

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        reader = SubscriptionUsageReader(
            creds, "claude", "pro", http_client=client
        )

        await reader.read()
        await reader.read()
        assert call_count == 1

    @pytest.mark.anyio
    async def test_oauth_token_access_token_key(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(json.dumps({"access_token": "test-token"}))

        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=_oauth_response())
        )
        client = httpx.AsyncClient(transport=transport)
        reader = SubscriptionUsageReader(
            creds, "claude", "pro", http_client=client
        )

        snapshot = await reader.read()
        assert len(snapshot.meters) == 5

    @pytest.mark.anyio
    async def test_sends_correct_headers(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(json.dumps({"accessToken": "my-token"}))

        captured_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json=_oauth_response())

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        reader = SubscriptionUsageReader(
            creds, "claude", "pro", http_client=client
        )
        await reader.read()

        assert captured_headers["authorization"] == "Bearer my-token"
        assert captured_headers["anthropic-beta"] == "oauth-2025-04-20"


class TestSubscriptionReaderFallbackToStatusLine:
    @pytest.mark.anyio
    async def test_falls_back_on_oauth_failure(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(json.dumps({"accessToken": "test-token"}))

        status_line = tmp_path / "status_line.json"
        status_line.write_text(
            json.dumps({"rate_limits": {"five_hour": 55.0, "seven_day": 40.0}})
        )

        transport = httpx.MockTransport(
            lambda request: httpx.Response(500, text="Internal Server Error")
        )
        client = httpx.AsyncClient(transport=transport)
        reader = SubscriptionUsageReader(
            creds,
            "claude",
            "pro",
            http_client=client,
            status_line_path=status_line,
        )

        snapshot = await reader.read()
        assert reader.fallback_level == FallbackLevel.STATUS_LINE
        assert len(snapshot.meters) == 2
        by_kind = {m.kind: m for m in snapshot.meters}
        assert by_kind[MeterKind.FIVE_HOUR].utilisation == 55.0
        assert by_kind[MeterKind.SEVEN_DAY].utilisation == 40.0

    @pytest.mark.anyio
    async def test_falls_back_when_no_credentials(self, tmp_path: Path) -> None:
        missing_creds = tmp_path / "nonexistent.json"
        status_line = tmp_path / "status_line.json"
        status_line.write_text(
            json.dumps({"rate_limits": {"five_hour": 10.0}})
        )

        reader = SubscriptionUsageReader(
            missing_creds,
            "claude",
            "pro",
            status_line_path=status_line,
        )

        snapshot = await reader.read()
        assert reader.fallback_level == FallbackLevel.STATUS_LINE
        assert len(snapshot.meters) == 1


class TestSubscriptionReaderTokenEstimationFallback:
    @pytest.mark.anyio
    async def test_falls_back_to_token_estimation(self, tmp_path: Path) -> None:
        missing_creds = tmp_path / "nonexistent.json"
        reader = SubscriptionUsageReader(
            missing_creds, "claude", "pro"
        )

        snapshot = await reader.read()
        assert reader.fallback_level == FallbackLevel.TOKEN_ESTIMATION
        assert snapshot.meters == []
        assert snapshot.provider == "claude"

    @pytest.mark.anyio
    async def test_all_levels_fail_gracefully(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(json.dumps({"accessToken": "test-token"}))

        transport = httpx.MockTransport(
            lambda request: httpx.Response(429, text="Rate limited")
        )
        client = httpx.AsyncClient(transport=transport)

        bad_status = tmp_path / "status_line.json"
        bad_status.write_text("not valid json{{{")

        reader = SubscriptionUsageReader(
            creds,
            "claude",
            "pro",
            http_client=client,
            status_line_path=bad_status,
        )

        snapshot = await reader.read()
        assert reader.fallback_level == FallbackLevel.TOKEN_ESTIMATION
        assert snapshot.meters == []


class TestSubscriptionReaderEdgeCases:
    @pytest.mark.anyio
    async def test_malformed_credentials_file(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text("not json at all")

        reader = SubscriptionUsageReader(creds, "claude", "pro")
        await reader.read()
        assert reader.fallback_level == FallbackLevel.TOKEN_ESTIMATION

    @pytest.mark.anyio
    async def test_credentials_missing_token_key(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(json.dumps({"refreshToken": "refresh-only"}))

        reader = SubscriptionUsageReader(creds, "claude", "pro")
        await reader.read()
        assert reader.fallback_level == FallbackLevel.TOKEN_ESTIMATION

    @pytest.mark.anyio
    async def test_oauth_returns_unexpected_json(self, tmp_path: Path) -> None:
        creds = tmp_path / "credentials.json"
        creds.write_text(json.dumps({"accessToken": "test-token"}))

        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"completely": "different"})
        )
        client = httpx.AsyncClient(transport=transport)
        reader = SubscriptionUsageReader(
            creds, "claude", "pro", http_client=client
        )

        snapshot = await reader.read()
        assert reader.fallback_level == FallbackLevel.OAUTH
        assert snapshot.meters == []
