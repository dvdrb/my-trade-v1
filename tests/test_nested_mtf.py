from __future__ import annotations

from app.backtest.metrics import calculate_metrics
from app.backtest.runner import closed_candles_as_of
from app.config.settings import load_config
from app.core.types import Candle, Side, Trade, Triangle
from app.strategy.candidates import TriangleCandidate
from app.strategy.nesting import is_child_inside_parent, score_nested_relationship
from app.strategy.nested import _mtf_zone_score
from app.strategy.risk import RiskPlan
from app.core.types import StrongZone


def _candidate(start: int, end: int, start_time: int, end_time: int, upper_start: float = 110, upper_end: float = 105, lower_start: float = 90, lower_end: float = 95) -> TriangleCandidate:
    triangle = Triangle("symmetrical", start, end, start_time, end_time, upper_start, upper_end, lower_start, lower_end)
    return TriangleCandidate(triangle, "symmetrical", start, end, end - start, 2, 2, 0.5, 20.0)


def _candle(time: int, high: float = 105, low: float = 95, close_time: int | None = None) -> Candle:
    return Candle("BTC", "15m", time, 100, high, low, 100, close_time=close_time)


def test_nested_mtf_config_loads() -> None:
    config = load_config("app/config/strategy_nested_mtf.yaml")
    assert (config.market.timeframe, config.market.entry_timeframe, config.market.local_timeframe, config.market.regime_timeframe) == ("15m", "15m", "1h", "4h")
    assert config.strategy.scoring.use_nested_mtf is True
    assert config.strategy.scoring.nested_regime_tolerance_percent == 0.01


def test_closed_candles_as_of_excludes_unfinished_parent_candles() -> None:
    hourly = [_candle(0, close_time=3_600_000), _candle(3_600_000, close_time=7_200_000)]
    four_hour = [_candle(0, close_time=14_400_000), _candle(14_400_000, close_time=28_800_000)]
    assert closed_candles_as_of(hourly, 5_400_000, "1h") == [hourly[0]]
    assert closed_candles_as_of(four_hour, 14_399_999, "4h") == []
    assert closed_candles_as_of(four_hour, 14_400_000, "4h") == [four_hour[0]]


def test_child_can_finish_within_the_latest_closed_parent_candle() -> None:
    parent = _candidate(0, 10, 0, 10_000)
    child = _candidate(2, 6, 8_000, 9_000)
    parent_candles = [_candle(0, close_time=4_000), _candle(4_000, close_time=10_000)]
    child_candles = [_candle(8_000, 105, 95), _candle(9_000, 105, 95)]
    assert is_child_inside_parent(parent, child, parent_candles, child_candles, 0.01)


def test_child_inside_parent_allows_small_band_overrun_but_rejects_far_outside() -> None:
    parent = _candidate(0, 10, 0, 10_000)
    child = _candidate(2, 6, 2_000, 6_000)
    parent_candles = [_candle(0), _candle(10_000)]
    inside = [_candle(2_000, 105.2, 95), _candle(4_000, 103, 97), _candle(6_000, 102, 98)]
    outside = [_candle(2_000, 120, 80), _candle(4_000, 120, 80), _candle(6_000, 120, 80)]
    assert is_child_inside_parent(parent, child, parent_candles, inside, 0.01)
    assert not is_child_inside_parent(parent, child, parent_candles, outside, 0.01)
    score, context = score_nested_relationship(parent, child, parent_candles, inside, Side.LONG, 0.01)
    assert score > 0 and "nested child" in context


def test_nested_report_sections_exist() -> None:
    trade = Trade("BTC", "15m", Side.LONG, 1, 100, 1, 95, 110, 2, 110, 10, 2, "closed", nested_metadata={"nested_context": "aligned", "parent_timeframe_alignment": "both", "parent_4h_triangle_type": "ascending", "parent_1h_triangle_type": "symmetrical", "child_triangle_type": "ascending", "regime_trend_direction": "bullish", "local_trend_direction": "bullish", "mtf_zone_context": "4h favorable zone"})
    summary = calculate_metrics([trade], [])
    for key in ("performance_by_nested_context", "performance_by_parent_timeframe_alignment", "performance_by_4h_triangle_type", "performance_by_1h_triangle_type", "performance_by_child_triangle_type", "performance_by_4h_trend", "performance_by_1h_trend", "performance_by_mtf_zone_context"):
        assert key in summary
    assert summary["performance_by_4h_triangle_type"]["ascending"]["trades"] == 1


def test_higher_timeframe_zones_have_larger_effect() -> None:
    risk = RiskPlan(100, 95, 110, 2, 1)
    score_without, _ = _mtf_zone_score([], [], [], Side.LONG, risk)
    score_with_4h, _ = _mtf_zone_score([StrongZone("support", 90, 99, 2, 2)], [], [], Side.LONG, risk)
    score_with_15m, _ = _mtf_zone_score([], [], [StrongZone("support", 90, 99, 2, 2)], Side.LONG, risk)
    assert score_with_4h > score_with_15m > score_without
