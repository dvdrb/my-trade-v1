from __future__ import annotations

from dataclasses import replace

from app.backtest.metrics import calculate_metrics
from app.backtest.runner import _build_trade
from app.backtest.runner import closed_candles_as_of
from app.config.settings import load_config
from app.core.types import Candle, Side, Trade, Triangle
from app.core.types import Decision, Signal
from app.strategy.candidates import TriangleCandidate
from app.strategy.nesting import is_child_inside_parent, score_nested_relationship
from app.strategy.nested import _mtf_zone_score, _record_parent_diagnostics, _should_hard_reject_zone
from app.strategy.risk import RiskPlan
from app.strategy.structural_features import structural_features
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


def test_strict_and_penalty_configs_toggle_mtf_zone_hard_filter() -> None:
    strict = load_config("app/config/strategy_nested_mtf_strict_zones.yaml")
    penalty = load_config("app/config/strategy_nested_mtf_zone_penalty.yaml")
    metadata = {"mtf_opposite_zone_before_target": True, "would_be_blocked_timeframes": ["1h"]}
    assert _should_hard_reject_zone(metadata, strict)
    assert not _should_hard_reject_zone(metadata, penalty)
    strict.strategy.scoring.mtf_zone_hard_filter_timeframes = ["4h"]
    assert not _should_hard_reject_zone(metadata, strict)


def test_missing_zone_ablation_configs_load_and_filter_only_configured_timeframes() -> None:
    hard_15m = load_config("app/config/strategy_nested_mtf_hard_15m_penalty_4h_1h.yaml")
    hard_1h_15m = load_config("app/config/strategy_nested_mtf_hard_1h_15m_penalty_4h.yaml")
    assert hard_15m.strategy.scoring.mtf_zone_hard_filter_timeframes == ["15m"]
    assert hard_1h_15m.strategy.scoring.mtf_zone_hard_filter_timeframes == ["1h", "15m"]
    assert _should_hard_reject_zone({"would_be_blocked_timeframes": ["15m"]}, hard_15m)
    assert not _should_hard_reject_zone({"would_be_blocked_timeframes": ["4h"]}, hard_15m)
    assert _should_hard_reject_zone({"would_be_blocked_timeframes": ["1h"]}, hard_1h_15m)
    assert not _should_hard_reject_zone({"would_be_blocked_timeframes": ["4h"]}, hard_1h_15m)


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
    score_without, _, _ = _mtf_zone_score([], [], [], Side.LONG, risk)
    score_with_4h, _, _ = _mtf_zone_score([StrongZone("support", 90, 99, 2, 2)], [], [], Side.LONG, risk)
    score_with_15m, _, _ = _mtf_zone_score([], [], [StrongZone("support", 90, 99, 2, 2)], Side.LONG, risk)
    assert score_with_4h > score_with_15m > score_without


def test_nested_funnel_and_zone_diagnostics_do_not_use_legacy_zero_fields() -> None:
    signal = Signal("BTC", "15m", Decision.REJECTED, metadata={
        "regime_triangles_found": 1, "local_triangles_found": 2, "entry_triangles_found": 3,
        "nested_setups_found": 2, "entry_breakouts_found": 1, "scored_nested_setups": 1,
        "rejected_by_mtf_zone": 1, "blocked_mtf_zone_setups": 1,
        "blocked_mtf_zone_by_side": {"long": 1}, "blocked_mtf_zone_by_timeframe": {"4h": 1},
        "blocked_mtf_zone_by_parent_alignment": {"both": 1},
        "blocked_mtf_zone_by_child_triangle_type": {"ascending": 1},
        "blocked_mtf_zone_by_score_bucket": {"60_69": 1},
    })
    summary = calculate_metrics([], [signal], run_metadata={"use_nested_mtf": True})
    assert "triangle_candidates_found" not in summary["candidate_funnel"]
    assert summary["nested_candidate_funnel"]["entry_triangles_found"] == 3
    assert summary["mtf_zone_diagnostics"]["blocked_mtf_zone_by_timeframe"] == {"4h": 1}


def test_blocked_zone_details_include_timeframe_and_distances() -> None:
    risk = RiskPlan(100, 95, 110, 2, 1)
    _, _, blocks = _mtf_zone_score([StrongZone("resistance", 103, 104, 2, 2)], [], [], Side.LONG, risk)
    assert blocks == [{"timeframe": "4h", "zone_kind": "resistance", "distance_to_entry_r": 0.6, "distance_to_target_r": 1.4}]


def test_4h_parent_diagnostics_are_counted() -> None:
    parent = _candidate(0, 10, 0, 10_000)
    funnel: dict[str, object] = {key: 0 for key in ("entry_breakouts_with_4h_parent", "entry_breakouts_with_1h_parent", "entry_breakouts_with_both_parents", "entry_breakouts_with_1h_only", "entry_breakouts_with_4h_only", "entry_breakouts_without_parent", "4h_parent_found_but_not_nested", "no_4h_parent_found")}
    _record_parent_diagnostics(funnel, parent, None, True)
    _record_parent_diagnostics(funnel, None, None, False)
    assert funnel["entry_breakouts_with_4h_only"] == 1
    assert funnel["entry_breakouts_without_parent"] == 1
    assert funnel["no_4h_parent_found"] == 1


def test_nested_score_components_are_exported_to_trade() -> None:
    signal = Signal("BTC", "15m", Decision.ACCEPTED, Side.LONG, entry_price=100, stop_loss=95, take_profit=110, position_size=1, risk_amount=5, metadata={
        "score_parent_4h_structure": 20, "score_parent_1h_structure": 15,
        "score_nested_triangle": 20, "score_entry_breakout": 10, "score_mtf_zones": 18,
        "score_risk_quality": 10, "parent_4h_triangle_type": "ascending",
        "parent_1h_triangle_type": "symmetrical", "child_triangle_type": "ascending",
        "parent_timeframe_alignment": "both", "nested_context": "nested child aligned with parent",
        "entry_trend_direction": "bullish", "local_trend_direction": "bullish",
        "regime_trend_direction": "bullish", "mtf_zone_context": "4h favorable zone",
    })
    trade, reason = _build_trade(signal, _candle(1), 0, None)
    assert reason is None and trade is not None
    assert trade.score_parent_4h_structure == 20
    assert trade.parent_timeframe_alignment == "both"
    summary = calculate_metrics([replace(trade, status="closed")], [], run_metadata={"use_nested_mtf": True})
    assert summary["performance_by_parent_4h_score_bucket"]["15_20"]["trades"] == 1


def test_counterfactual_blocked_performance_is_populated() -> None:
    trade = Trade("BTC", "15m", Side.LONG, 1, 100, 1, 95, 110, 2, 110, 10, 2, "closed", nested_metadata={"would_be_blocked_by_strict_mtf_zone": True, "would_be_blocked_timeframes": ["4h", "1h"], "child_triangle_type": "ascending"})
    summary = calculate_metrics([trade], [], run_metadata={"use_nested_mtf": True})
    assert summary["performance_by_would_be_strict_zone_blocked"]["True"]["trades"] == 1
    assert summary["performance_by_would_be_blocked_timeframe"]["4h"]["trades"] == 1


def test_period_performance_reports_are_populated() -> None:
    timestamp = 1767225600000  # 2026-01-01 UTC
    trade = Trade("BTC", "15m", Side.LONG, timestamp, 100, 1, 95, 110, timestamp, 110, 10, 2, "closed")
    summary = calculate_metrics([trade], [])
    assert summary["performance_by_month"]["2026-01"]["trades"] == 1
    assert summary["performance_by_quarter"]["2026-Q1"]["max_losing_streak"] == 0
    assert summary["performance_by_year"]["2026"]["profit_factor"] == 10


def test_structural_features_describe_parent_child_breakout_without_changing_signal_logic() -> None:
    config = load_config("app/config/strategy_nested_mtf_zone_penalty.yaml")
    parent, child = _candidate(0, 10, 0, 10_000), _candidate(2, 6, 2_000, 6_000)
    candles = [_candle(index * 1_000, 105, 95, (index + 1) * 1_000) for index in range(220)]
    features = structural_features(child, parent, parent, candles, candles, candles, Side.LONG, RiskPlan(100, 95, 110, 2, 1), [], [], [], config)
    assert features["triangle_type"] == "symmetrical"
    assert features["parent_1h_exists"] is True
    assert features["breakout_body_percent"] == 0.0
    assert "distance_to_nearest_4h_opposite_zone_r" in features
