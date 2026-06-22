from __future__ import annotations

from app.usage.models import (
    Meter,
    MeterKind,
    UsageSnapshot,
    applicable_meters,
    governing_meter,
)
from app.usage.reader import UsageReader


class TestMeter:
    def test_known_kind(self) -> None:
        m = Meter(kind=MeterKind.FIVE_HOUR, utilisation=42.0)
        assert m.kind == "five_hour"
        assert m.utilisation == 42.0
        assert m.resets_at is None
        assert m.limit is None
        assert m.used is None

    def test_with_limit_and_used(self) -> None:
        m = Meter(
            kind=MeterKind.API_BUDGET,
            utilisation=60.0,
            limit=100.0,
            used=60.0,
        )
        assert m.limit == 100.0
        assert m.used == 60.0

    def test_with_resets_at(self) -> None:
        m = Meter(kind=MeterKind.SEVEN_DAY, utilisation=80.0, resets_at=1750000000.0)
        assert m.resets_at == 1750000000.0


class TestUsageSnapshot:
    def test_empty_snapshot(self) -> None:
        snap = UsageSnapshot(meters=[], provider="claude", plan="pro")
        assert snap.meters == []
        assert snap.provider == "claude"
        assert snap.plan == "pro"
        assert snap.timestamp > 0

    def test_snapshot_with_meters(self) -> None:
        meters = [
            Meter(kind=MeterKind.FIVE_HOUR, utilisation=30.0),
            Meter(kind=MeterKind.SEVEN_DAY, utilisation=60.0),
        ]
        snap = UsageSnapshot(
            meters=meters, provider="claude", plan="pro", timestamp=1000.0
        )
        assert len(snap.meters) == 2
        assert snap.timestamp == 1000.0


class TestGoverningMeter:
    def test_returns_highest_utilisation(self) -> None:
        snap = UsageSnapshot(
            meters=[
                Meter(kind=MeterKind.FIVE_HOUR, utilisation=50.0),
                Meter(kind=MeterKind.SEVEN_DAY, utilisation=80.0),
            ],
            provider="claude",
            plan="pro",
        )
        result = governing_meter(snap)
        assert result is not None
        assert result.kind == MeterKind.SEVEN_DAY
        assert result.utilisation == 80.0

    def test_returns_none_for_empty(self) -> None:
        snap = UsageSnapshot(meters=[], provider="claude", plan="pro")
        assert governing_meter(snap) is None

    def test_tie_broken_deterministically(self) -> None:
        m1 = Meter(kind="alpha", utilisation=80.0)
        m2 = Meter(kind="beta", utilisation=80.0)
        snap = UsageSnapshot(
            meters=[m1, m2], provider="claude", plan="pro", timestamp=1.0
        )
        result = governing_meter(snap)
        assert result is not None
        assert result.kind == "beta"

        snap_reversed = UsageSnapshot(
            meters=[m2, m1], provider="claude", plan="pro", timestamp=1.0
        )
        result2 = governing_meter(snap_reversed)
        assert result2 is not None
        assert result2.kind == "beta"

    def test_single_meter(self) -> None:
        snap = UsageSnapshot(
            meters=[Meter(kind=MeterKind.API_BUDGET, utilisation=10.0)],
            provider="claude",
            plan="api",
        )
        result = governing_meter(snap)
        assert result is not None
        assert result.kind == MeterKind.API_BUDGET

    def test_all_known_meter_kinds(self) -> None:
        meters = [
            Meter(kind=MeterKind.FIVE_HOUR, utilisation=40.0),
            Meter(kind=MeterKind.SEVEN_DAY, utilisation=30.0),
            Meter(kind=MeterKind.SEVEN_DAY_OPUS, utilisation=70.0),
            Meter(kind=MeterKind.SEVEN_DAY_SONNET, utilisation=20.0),
            Meter(kind=MeterKind.AGENT_SDK_CREDIT, utilisation=90.0),
        ]
        snap = UsageSnapshot(
            meters=meters, provider="claude", plan="max", timestamp=1.0
        )
        result = governing_meter(snap)
        assert result is not None
        assert result.kind == MeterKind.AGENT_SDK_CREDIT
        assert result.utilisation == 90.0


class TestApplicableMeters:
    def test_claude_pro(self) -> None:
        meters = applicable_meters("claude", "pro")
        assert MeterKind.FIVE_HOUR in meters
        assert MeterKind.SEVEN_DAY in meters
        assert MeterKind.SEVEN_DAY_OPUS in meters
        assert MeterKind.SEVEN_DAY_SONNET in meters
        assert MeterKind.AGENT_SDK_CREDIT in meters
        assert MeterKind.API_BUDGET not in meters

    def test_claude_max(self) -> None:
        meters = applicable_meters("claude", "max")
        assert meters == applicable_meters("claude", "pro")

    def test_claude_api(self) -> None:
        meters = applicable_meters("claude", "api")
        assert MeterKind.API_BUDGET in meters
        assert len(meters) == 1

    def test_unknown_combo_returns_empty(self) -> None:
        meters = applicable_meters("codex", "unknown")
        assert meters == frozenset()

    def test_subscription_and_api_disjoint(self) -> None:
        sub = applicable_meters("claude", "pro")
        api = applicable_meters("claude", "api")
        assert sub.isdisjoint(api)


class TestUnknownMeterPassThrough:
    def test_unknown_kind_accepted(self) -> None:
        m = Meter(kind="brand_new_meter", utilisation=90.0)
        assert m.kind == "brand_new_meter"
        assert m.utilisation == 90.0

    def test_unknown_meter_in_snapshot(self) -> None:
        snap = UsageSnapshot(
            meters=[
                Meter(kind=MeterKind.FIVE_HOUR, utilisation=50.0),
                Meter(kind="unknown_future_meter", utilisation=10.0),
            ],
            provider="claude",
            plan="pro",
        )
        assert len(snap.meters) == 2
        kinds = {m.kind for m in snap.meters}
        assert "unknown_future_meter" in kinds

    def test_unknown_meter_participates_in_governing(self) -> None:
        snap = UsageSnapshot(
            meters=[
                Meter(kind=MeterKind.FIVE_HOUR, utilisation=50.0),
                Meter(kind="unknown_future_meter", utilisation=95.0),
            ],
            provider="claude",
            plan="pro",
        )
        result = governing_meter(snap)
        assert result is not None
        assert result.kind == "unknown_future_meter"
        assert result.utilisation == 95.0

    def test_unknown_meter_can_be_governing_with_resets_at(self) -> None:
        snap = UsageSnapshot(
            meters=[
                Meter(kind=MeterKind.SEVEN_DAY, utilisation=40.0),
                Meter(
                    kind="new_opus_weekly_v2",
                    utilisation=85.0,
                    resets_at=1750000000.0,
                ),
            ],
            provider="claude",
            plan="pro",
        )
        result = governing_meter(snap)
        assert result is not None
        assert result.kind == "new_opus_weekly_v2"
        assert result.resets_at == 1750000000.0


class TestUsageReaderInterface:
    def test_is_abstract(self) -> None:
        import pytest

        with pytest.raises(TypeError, match="abstract"):
            UsageReader()  # type: ignore[abstract]
