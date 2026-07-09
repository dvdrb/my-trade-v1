from __future__ import annotations

from app.config.settings import AppConfig
from app.core.types import Candle, Pivot, Side, StrongZone
from app.strategy.candidates import TriangleCandidate, find_triangle_candidates
from app.strategy.breakout import detect_breakout
from app.strategy.risk import RiskPlan
from app.strategy.scoring import risk_percent_for_score, score_candidate
from app.strategy.triangle import detect_triangle


def c(time: int, high: float, low: float, close: float | None = None, open_: float | None = None) -> Candle:
    price = close if close is not None else (high + low) / 2
    return Candle("BTC", "15m", time, open_ if open_ is not None else price, high, low, price)


def p(index: int, price: float, kind: str) -> Pivot:
    return Pivot("BTC", "15m", index, index, price, kind)


def candidate(kind: str = "ascending") -> TriangleCandidate:
    triangle = detect_triangle([p(0, 100, "high"), p(2, 90, "low"), p(6, 100.1, "high"), p(8, 95, "low")], 20, 10, 80, 0.003)
    assert triangle is not None
    return TriangleCandidate(triangle, kind, triangle.start_index, triangle.end_index, 20, 2, 2, 0.4, 20.0)


def test_candidate_scanner_returns_multiple_and_deduplicates() -> None:
    pivots = [
        p(0, 110, "high"),
        p(2, 90, "low"),
        p(4, 108, "high"),
        p(6, 92, "low"),
        p(8, 106, "high"),
        p(10, 94, "low"),
        p(12, 104, "high"),
        p(14, 96, "low"),
    ]
    candidates = find_triangle_candidates(pivots + pivots[-2:], 24, 8, 80, 0.003, 20)
    keys = {(item.triangle_type, item.start_index, item.end_index) for item in candidates}
    assert len(candidates) >= 2
    assert len(keys) == len(candidates)


def test_scoring_model_returns_all_components() -> None:
    config = AppConfig()
    candles = [c(i, 100 + i * 0.1, 90 + i * 0.2, close=95 + i * 0.2) for i in range(25)]
    plan = RiskPlan(102, 96, 114, 2.0, 1)
    score = score_candidate(candidate(), candles, [p(1, 100, "high"), p(2, 90, "low"), p(4, 101, "high"), p(6, 95, "low")], [], Side.LONG, plan, config)
    assert 0 <= score.total_score <= 100
    assert score.triangle_quality >= 0
    assert score.breakout_quality >= 0
    assert score.trend_quality >= 0
    assert score.zone_quality >= 0
    assert score.risk_quality == 20


def test_trend_and_zone_mismatch_lower_score_without_hard_reject() -> None:
    config = AppConfig()
    config.strategy.scoring.trend_as_hard_filter = False
    config.strategy.scoring.zone_as_hard_filter = False
    candles = [c(i, 120 - i, 110 - i, close=115 - i, open_=116 - i) for i in range(25)]
    plan = RiskPlan(102, 96, 114, 2.0, 1)
    clean = score_candidate(candidate(), candles, [], [], Side.LONG, plan, config)
    blocked = score_candidate(candidate(), candles, [], [StrongZone("resistance", 103, 104, 3, 3)], Side.LONG, plan, config)
    assert blocked.total_score < clean.total_score
    assert any("opposite zone" in penalty for penalty in blocked.penalties)


def test_risk_quality_below_absolute_and_below_target() -> None:
    config = AppConfig()
    config.risk.absolute_min_reward_risk = 1.2
    config.risk.target_reward_risk = 2.0
    candles = [c(i, 100 + i, 90 + i, close=95 + i) for i in range(25)]
    low = score_candidate(candidate(), candles, [], [], Side.LONG, RiskPlan(100, 95, 105, 1.0, 1), config)
    mid = score_candidate(candidate(), candles, [], [], Side.LONG, RiskPlan(100, 95, 108, 1.6, 1), config)
    assert low.risk_quality == 0
    assert mid.risk_quality == 13


def test_dynamic_risk_tier_selects_percent() -> None:
    config = AppConfig()
    config.risk.score_risk_tiers = [
        {"min_score": 75, "risk_percent": 0.005},
        {"min_score": 60, "risk_percent": 0.003},
        {"min_score": 50, "risk_percent": 0.0015},
    ]
    assert risk_percent_for_score(80, config) == 0.005
    assert risk_percent_for_score(65, config) == 0.003
    assert risk_percent_for_score(55, config) == 0.0015
    assert risk_percent_for_score(49, config) is None


def _band_pivots() -> list[Pivot]:
    return [p(0, 100, "high"), p(0, 90, "low"), p(10, 100.1, "high"), p(10, 95, "low")]


def _band_candles() -> list[Candle]:
    return [c(i, 99, 96, close=97) for i in range(21)]


def test_wick_and_close_slightly_above_line_inside_band_do_not_invalidate() -> None:
    candles = _band_candles()
    candles[5] = c(5, 100.1, 96, close=97)
    candles[6] = c(6, 100.1, 96, close=100.1)
    candidates = find_triangle_candidates(
        _band_pivots(),
        20,
        10,
        80,
        0.003,
        candles=candles,
        line_tolerance_percent=0.002,
        max_wick_violation_percent=0.004,
        max_close_violation_percent=0.002,
        max_allowed_close_violations=2,
        max_allowed_wick_violations=4,
    )
    assert candidates
    assert candidates[0].wick_violation_count == 0
    assert candidates[0].close_violation_count == 0


def test_repeated_and_large_close_violations_invalidate_candidate() -> None:
    repeated = _band_candles()
    for index in [4, 5, 6]:
        repeated[index] = c(index, 100.4, 92, close=100.3)
    assert not find_triangle_candidates(
        _band_pivots(),
        20,
        10,
        80,
        0.003,
        candles=repeated,
        line_tolerance_percent=0.002,
        max_wick_violation_percent=0.004,
        max_close_violation_percent=0.002,
        max_allowed_close_violations=2,
        max_allowed_wick_violations=4,
    )

    large = _band_candles()
    large[5] = c(5, 100.8, 92, close=100.7)
    assert not find_triangle_candidates(
        _band_pivots(),
        20,
        10,
        80,
        0.003,
        candles=large,
        line_tolerance_percent=0.002,
        max_wick_violation_percent=0.004,
        max_close_violation_percent=0.002,
        max_allowed_close_violations=2,
        max_allowed_wick_violations=4,
    )


def test_breakout_requires_close_beyond_band_plus_buffer() -> None:
    candidate_item = find_triangle_candidates(_band_pivots(), 20, 10, 80, 0.003, candles=_band_candles(), line_tolerance_percent=0.002)[0]
    assert detect_breakout(c(20, 101, 99, close=100.25, open_=99), candidate_item.triangle, 20, 0.0015, 0.25, 0.002) is None
    assert detect_breakout(c(20, 101, 99, close=100.5, open_=99), candidate_item.triangle, 20, 0.0015, 0.25, 0.002) == Side.LONG


def test_triangle_cleanliness_score_decreases_with_violations() -> None:
    clean = candidate()
    messy = TriangleCandidate(clean.triangle, clean.triangle_type, clean.start_index, clean.end_index, clean.age, 2, 2, 0.4, 10, 3, 1, 0.001, 0.0005, 0.002)
    candles = [c(i, 100 + i, 90 + i, close=95 + i) for i in range(25)]
    config = AppConfig()
    plan = RiskPlan(102, 96, 114, 2.0, 1)
    clean_score = score_candidate(clean, candles, [], [], Side.LONG, plan, config)
    messy_score = score_candidate(messy, candles, [], [], Side.LONG, plan, config)
    assert messy_score.triangle_quality < clean_score.triangle_quality
