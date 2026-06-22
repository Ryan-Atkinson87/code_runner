from __future__ import annotations

from app.usage.models import Meter, MeterKind, UsageSnapshot
from app.usage.threshold import (
    _SDK_CREDIT_CUTOVER,
    evaluate_threshold,
    human_reserve_meter,
)


def _snapshot(meters: list[Meter]) -> UsageSnapshot:
    return UsageSnapshot(meters=meters, provider="claude", plan="pro", timestamp=1.0)


class TestEvaluateThreshold:
    def test_below_threshold(self) -> None:
        snap = _snapshot([Meter(kind=MeterKind.FIVE_HOUR, utilisation=50.0)])
        result = evaluate_threshold(snap)
        assert result.reached is False
        assert result.governing is not None
        assert result.governing.kind == MeterKind.FIVE_HOUR
        assert result.threshold_percent == 80

    def test_at_threshold(self) -> None:
        snap = _snapshot([Meter(kind=MeterKind.FIVE_HOUR, utilisation=80.0)])
        result = evaluate_threshold(snap)
        assert result.reached is True

    def test_above_threshold(self) -> None:
        snap = _snapshot([Meter(kind=MeterKind.FIVE_HOUR, utilisation=95.0)])
        result = evaluate_threshold(snap)
        assert result.reached is True

    def test_custom_threshold(self) -> None:
        snap = _snapshot([Meter(kind=MeterKind.FIVE_HOUR, utilisation=60.0)])
        result = evaluate_threshold(snap, threshold_percent=50)
        assert result.reached is True
        assert result.threshold_percent == 50

    def test_custom_threshold_not_reached(self) -> None:
        snap = _snapshot([Meter(kind=MeterKind.FIVE_HOUR, utilisation=40.0)])
        result = evaluate_threshold(snap, threshold_percent=50)
        assert result.reached is False

    def test_empty_snapshot(self) -> None:
        snap = _snapshot([])
        result = evaluate_threshold(snap)
        assert result.reached is False
        assert result.governing is None

    def test_most_restrictive_governs(self) -> None:
        snap = _snapshot(
            [
                Meter(kind=MeterKind.FIVE_HOUR, utilisation=50.0),
                Meter(kind=MeterKind.SEVEN_DAY, utilisation=85.0),
                Meter(kind=MeterKind.AGENT_SDK_CREDIT, utilisation=30.0),
            ]
        )
        result = evaluate_threshold(snap)
        assert result.reached is True
        assert result.governing is not None
        assert result.governing.kind == MeterKind.SEVEN_DAY

    def test_no_model_downgrade_just_reached(self) -> None:
        snap = _snapshot([Meter(kind=MeterKind.FIVE_HOUR, utilisation=90.0)])
        result = evaluate_threshold(snap)
        assert result.reached is True
        assert result.governing is not None


class TestHumanReserveMeter:
    def test_before_cutover_returns_chat_pool(self) -> None:
        snap = _snapshot(
            [
                Meter(kind=MeterKind.FIVE_HOUR, utilisation=50.0),
                Meter(kind=MeterKind.SEVEN_DAY, utilisation=30.0),
                Meter(kind=MeterKind.AGENT_SDK_CREDIT, utilisation=20.0),
            ]
        )
        before = _SDK_CREDIT_CUTOVER - 86400.0
        result = human_reserve_meter(snap, now=before)
        assert result in {
            MeterKind.FIVE_HOUR,
            MeterKind.SEVEN_DAY,
            MeterKind.SEVEN_DAY_OPUS,
            MeterKind.SEVEN_DAY_SONNET,
        }

    def test_after_cutover_returns_sdk_credit(self) -> None:
        snap = _snapshot(
            [
                Meter(kind=MeterKind.FIVE_HOUR, utilisation=50.0),
                Meter(kind=MeterKind.AGENT_SDK_CREDIT, utilisation=20.0),
            ]
        )
        after = _SDK_CREDIT_CUTOVER + 86400.0
        result = human_reserve_meter(snap, now=after)
        assert result == MeterKind.AGENT_SDK_CREDIT

    def test_exactly_at_cutover(self) -> None:
        snap = _snapshot(
            [Meter(kind=MeterKind.AGENT_SDK_CREDIT, utilisation=10.0)]
        )
        result = human_reserve_meter(snap, now=_SDK_CREDIT_CUTOVER)
        assert result == MeterKind.AGENT_SDK_CREDIT

    def test_before_cutover_no_chat_meters_defaults(self) -> None:
        snap = _snapshot([Meter(kind=MeterKind.AGENT_SDK_CREDIT, utilisation=10.0)])
        before = _SDK_CREDIT_CUTOVER - 86400.0
        result = human_reserve_meter(snap, now=before)
        assert result == MeterKind.FIVE_HOUR

    def test_before_cutover_picks_first_chat_meter(self) -> None:
        snap = _snapshot(
            [
                Meter(kind=MeterKind.SEVEN_DAY, utilisation=60.0),
                Meter(kind=MeterKind.FIVE_HOUR, utilisation=40.0),
            ]
        )
        before = _SDK_CREDIT_CUTOVER - 86400.0
        result = human_reserve_meter(snap, now=before)
        assert result == MeterKind.SEVEN_DAY
