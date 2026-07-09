from __future__ import annotations

from app.config.settings import AppConfig
from app.core.types import Candle, Decision, Pivot, Side, Signal, StrongZone, TrendDirection
from app.strategy.candidates import TriangleCandidate
from app.strategy.risk import RiskPlan
from app.strategy.scoring import ScoreBreakdown
from app.indicators.ema import ema
from app.strategy.breakout import detect_breakout
from app.strategy.evaluator import evaluate
from app.strategy.pivots import detect_pivots
from app.strategy.risk import calculate_risk_plan
from app.strategy.trend import ema_trend, structure_trend
from app.strategy.triangle import detect_triangle
from app.strategy.zones import blocked_by_opposite_zone, build_zones, nearest_resistance, nearest_support


def c(time: int, high: float, low: float, close: float | None = None, open_: float | None = None) -> Candle:
    price = close if close is not None else (high + low) / 2
    return Candle("BTC", "1h", time, open_ if open_ is not None else price, high, low, price)


def p(index: int, price: float, kind: str) -> Pivot:
    return Pivot("BTC", "1h", index, index, price, kind)


def test_ema_calculation() -> None:
    assert ema([1, 2, 3, 4], 3) == [None, None, 2.0, 3.0]


def test_pivot_detection_and_no_lookahead() -> None:
    candles = [c(0, 2, 1), c(1, 5, 1), c(2, 3, 0.5), c(3, 2, 1)]
    assert [pivot.kind for pivot in detect_pivots(candles, 1, 1)] == ["high", "low"]
    assert detect_pivots(candles[:2], 1, 1) == []


def test_trend_detection() -> None:
    candles = [c(i, i + 2, i, close=float(i + 1)) for i in range(1, 8)]
    assert ema_trend(candles, 2, 3) == TrendDirection.BULLISH
    assert structure_trend([p(1, 10, "high"), p(2, 8, "low"), p(3, 11, "high"), p(4, 9, "low")]) == TrendDirection.BULLISH


def test_zone_grouping_nearest_and_blocking() -> None:
    zones = build_zones([p(1, 100, "low"), p(2, 100.2, "low"), p(3, 110, "high"), p(4, 110.1, "high")], 0.003, 2)
    assert nearest_support(zones, 105).low == 100
    assert nearest_resistance(zones, 105).high == 110.1
    assert blocked_by_opposite_zone(zones, Side.LONG, 105, 100, 1.5) is True


def test_triangle_detection_variants_and_invalid() -> None:
    asc = detect_triangle([p(0, 100, "high"), p(2, 90, "low"), p(6, 100.1, "high"), p(8, 95, "low")], 12, 10, 80, 0.003)
    desc = detect_triangle([p(0, 110, "high"), p(2, 100, "low"), p(6, 105, "high"), p(8, 100.1, "low")], 12, 10, 80, 0.003)
    sym = detect_triangle([p(0, 110, "high"), p(2, 90, "low"), p(6, 105, "high"), p(8, 95, "low")], 12, 10, 80, 0.003)
    invalid = detect_triangle([p(0, 100, "high"), p(2, 90, "low"), p(6, 105, "high"), p(8, 85, "low")], 12, 10, 80, 0.003)
    assert asc and asc.kind == "ascending"
    assert desc and desc.kind == "descending"
    assert sym and sym.kind == "symmetrical"
    assert invalid is None


def test_breakout_confirmation_and_wick_rejection() -> None:
    triangle = detect_triangle([p(0, 100, "high"), p(2, 90, "low"), p(6, 100.1, "high"), p(8, 95, "low")], 12, 10, 80, 0.003)
    assert triangle is not None
    assert detect_breakout(c(12, 103, 99, close=102, open_=100), triangle, 12, 0.001) == Side.LONG
    assert detect_breakout(c(12, 105, 99, close=100.05, open_=100), triangle, 12, 0.001) is None


def test_risk_reward_and_position_sizing() -> None:
    triangle = detect_triangle([p(0, 100, "high"), p(2, 90, "low"), p(6, 100.1, "high"), p(8, 95, "low")], 12, 10, 80, 0.003)
    assert triangle is not None
    plan = calculate_risk_plan(Side.LONG, 102, [p(8, 95, "low")], triangle, 12, 1000, 0.01, 2.0)
    assert plan is not None
    assert plan.reward_risk == 2.0
    assert plan.position_size > 0


def test_signal_accepted_and_rejected_reasons(monkeypatch) -> None:
    candles = [c(i, 100 + i, 90 + i, close=95 + i) for i in range(20)]
    config = AppConfig()
    triangle = detect_triangle([p(0, 100, "high"), p(2, 90, "low"), p(6, 100.1, "high"), p(8, 95, "low")], 19, 10, 80, 0.003)
    assert triangle is not None
    monkeypatch.setattr("app.strategy.evaluator.detect_pivots", lambda *_: [p(1, 100, "high"), p(2, 90, "low"), p(4, 101, "high"), p(6, 95, "low")])
    monkeypatch.setattr("app.strategy.evaluator.detect_triangle", lambda *_: triangle)
    monkeypatch.setattr("app.strategy.evaluator.detect_breakout", lambda *_: Side.LONG)
    monkeypatch.setattr("app.strategy.evaluator.ema_trend", lambda *_: TrendDirection.BULLISH)
    monkeypatch.setattr("app.strategy.evaluator.build_zones", lambda *_: [])
    accepted = evaluate(candles, config)
    assert accepted.decision == Decision.ACCEPTED
    assert accepted.risk_amount == 5
    assert accepted.position_size is not None
    monkeypatch.setattr("app.strategy.evaluator.ema_trend", lambda *_: TrendDirection.BEARISH)
    rejected = evaluate(candles, config)
    assert rejected.decision == Decision.REJECTED
    assert "trend is not bullish for long" in rejected.reasons


def test_configurable_breakout_body_filter_is_passed(monkeypatch) -> None:
    candles = [c(i, 100 + i, 90 + i, close=95 + i) for i in range(20)]
    config = AppConfig()
    config.strategy.breakout.min_body_percent = 0.55
    triangle = detect_triangle([p(0, 100, "high"), p(2, 90, "low"), p(6, 100.1, "high"), p(8, 95, "low")], 19, 10, 80, 0.003)
    assert triangle is not None
    seen: dict[str, float] = {}

    def fake_breakout(candle, triangle, index, buffer_percent, min_body_percent, line_tolerance_percent=0.0):
        seen["min_body_percent"] = min_body_percent
        return None

    monkeypatch.setattr("app.strategy.evaluator.detect_pivots", lambda *_: [p(1, 100, "high"), p(2, 90, "low"), p(4, 101, "high"), p(6, 95, "low")])
    monkeypatch.setattr("app.strategy.evaluator.detect_triangle", lambda *_: triangle)
    monkeypatch.setattr("app.strategy.evaluator.detect_breakout", fake_breakout)
    evaluate(candles, config)
    assert seen["min_body_percent"] == 0.55


def test_zone_block_diagnostics_are_present(monkeypatch) -> None:
    candles = [c(i, 100 + i, 90 + i, close=95 + i) for i in range(20)]
    config = AppConfig()
    triangle = detect_triangle([p(0, 100, "high"), p(2, 90, "low"), p(6, 100.1, "high"), p(8, 95, "low")], 19, 10, 80, 0.003)
    assert triangle is not None
    monkeypatch.setattr("app.strategy.evaluator.detect_pivots", lambda *_: [p(1, 100, "high"), p(2, 90, "low"), p(4, 101, "high"), p(6, 95, "low")])
    monkeypatch.setattr("app.strategy.evaluator.detect_triangle", lambda *_: triangle)
    monkeypatch.setattr("app.strategy.evaluator.detect_breakout", lambda *_: Side.LONG)
    monkeypatch.setattr("app.strategy.evaluator.ema_trend", lambda *_: TrendDirection.BULLISH)
    monkeypatch.setattr("app.strategy.evaluator.build_zones", lambda *_: [StrongZone("resistance", 116, 117, 3, 3.0)])

    signal = evaluate(candles, config)
    assert signal.decision == Decision.REJECTED
    assert "blocked by nearby opposite zone" in signal.reasons
    diagnostics = signal.metadata["zone_block"]
    assert diagnostics["zone_kind"] == "resistance"
    assert diagnostics["zone_low"] == 116
    assert diagnostics["zone_high"] == 117
    assert diagnostics["zone_touches"] == 3
    assert diagnostics["zone_strength"] == 3.0
    assert "distance_to_zone" in diagnostics
    assert "distance_to_zone_r" in diagnostics


def test_scoring_evaluator_selects_highest_scoring_candidate(monkeypatch) -> None:
    candles = [c(i, 100 + i, 90 + i, close=95 + i, open_=94 + i) for i in range(25)]
    config = AppConfig()
    config.strategy.scoring.use_scoring_model = True
    config.strategy.scoring.min_trade_score = 50
    config.strategy.scoring.trend_as_hard_filter = False
    config.strategy.scoring.zone_as_hard_filter = False
    config.risk.absolute_min_reward_risk = 1.2
    config.risk.target_reward_risk = 2.0
    config.risk.score_risk_tiers = [{"min_score": 50, "risk_percent": 0.0015}]
    t1 = detect_triangle([p(0, 100, "high"), p(2, 90, "low"), p(6, 100.1, "high"), p(8, 95, "low")], 24, 10, 80, 0.003)
    t2 = detect_triangle([p(0, 110, "high"), p(2, 90, "low"), p(6, 105, "high"), p(8, 95, "low")], 24, 10, 80, 0.003)
    assert t1 and t2
    c1 = TriangleCandidate(t1, "ascending", t1.start_index, t1.end_index, 24, 2, 2, 0.2, 0.7)
    c2 = TriangleCandidate(t2, "symmetrical", t2.start_index, t2.end_index, 24, 2, 2, 0.5, 0.9)

    monkeypatch.setattr("app.strategy.evaluator.detect_pivots", lambda *_: [p(1, 100, "high"), p(2, 90, "low"), p(4, 101, "high"), p(6, 95, "low")])
    monkeypatch.setattr("app.strategy.evaluator.find_triangle_candidates", lambda *_: [c1, c2])
    monkeypatch.setattr("app.strategy.evaluator.detect_breakout", lambda *_: Side.LONG)
    monkeypatch.setattr("app.strategy.evaluator.calculate_risk_plan", lambda *args: RiskPlan(args[2][-1].price + 10, args[2][-1].price, args[2][-1].price + 30, 2.0, 1))

    def fake_score(candidate, *_):
        return ScoreBreakdown(55 if candidate is c1 else 80, 10, 10, 10, 10, 15, ["ok"], [])

    monkeypatch.setattr("app.strategy.evaluator.score_candidate", fake_score)
    signal = evaluate(candles, config)
    assert signal.decision == Decision.ACCEPTED
    assert signal.triangle_type == "symmetrical"
    assert signal.metadata["score_total"] == 80
    assert signal.metadata["candidate_count"] == 2
    assert signal.metadata["candidate_rank"] == 1
    assert "triangle_cleanliness_score" in signal.metadata
    assert "triangle_wick_violation_count" in signal.metadata
    assert "triangle_close_violation_count" in signal.metadata
    assert "triangle_max_wick_violation" in signal.metadata
    assert "triangle_max_close_violation" in signal.metadata
    assert "triangle_line_tolerance_used" in signal.metadata
