from __future__ import annotations

import pytest

from app.providers.pricing import calculate_cost


class TestKnownModels:
    def test_sonnet_4_6_cost(self) -> None:
        cost = calculate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.00)

    def test_opus_4_8_cost(self) -> None:
        cost = calculate_cost("claude-opus-4-8", 1_000_000, 1_000_000)
        assert cost == pytest.approx(30.00)

    def test_haiku_4_5_cost(self) -> None:
        cost = calculate_cost("claude-haiku-4-5", 1_000_000, 1_000_000)
        assert cost == pytest.approx(6.00)

    def test_zero_tokens(self) -> None:
        assert calculate_cost("claude-sonnet-4-6", 0, 0) == 0.0

    def test_only_input_tokens(self) -> None:
        cost = calculate_cost("claude-sonnet-4-6", 1_000_000, 0)
        assert cost == pytest.approx(3.00)

    def test_only_output_tokens(self) -> None:
        cost = calculate_cost("claude-sonnet-4-6", 0, 1_000_000)
        assert cost == pytest.approx(15.00)

    def test_small_session_typical_tokens(self) -> None:
        cost = calculate_cost("claude-sonnet-4-6", 10_000, 2_000)
        expected = (10_000 * 3.00 + 2_000 * 15.00) / 1_000_000
        assert cost == pytest.approx(expected)


class TestUnknownModel:
    def test_unknown_model_returns_zero(self) -> None:
        assert calculate_cost("gpt-4o", 100_000, 50_000) == 0.0

    def test_empty_model_returns_zero(self) -> None:
        assert calculate_cost("", 100_000, 50_000) == 0.0


class TestPrefixMatching:
    def test_dated_snapshot_suffix_resolves(self) -> None:
        cost_base = calculate_cost("claude-opus-4-8", 1_000_000, 0)
        cost_dated = calculate_cost("claude-opus-4-8-20260101", 1_000_000, 0)
        assert cost_dated == pytest.approx(cost_base)

    def test_all_opus_4_variants_match_same_rate(self) -> None:
        for variant in ("claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6"):
            cost = calculate_cost(variant, 1_000_000, 0)
            assert cost == pytest.approx(5.00), f"{variant} should cost $5/MTok in"
