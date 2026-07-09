from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import AppConfig
from app.core.types import Candle, Pivot, Side, StrongZone, TrendDirection
from app.indicators.ema import ema
from app.strategy.candidates import TriangleCandidate
from app.strategy.risk import RiskPlan
from app.strategy.trend import structure_trend
from app.strategy.triangle import triangle_lower_band_at, triangle_upper_band_at
from app.strategy.zones import nearest_resistance, nearest_support


@dataclass(frozen=True)
class ScoreBreakdown:
    total_score: float
    triangle_quality: float
    breakout_quality: float
    trend_quality: float
    zone_quality: float
    risk_quality: float
    reasons: list[str]
    penalties: list[str]


def score_candidate(
    candidate: TriangleCandidate,
    candles: list[Candle],
    pivots: list[Pivot],
    zones: list[StrongZone],
    breakout_side: Side,
    risk_plan: RiskPlan,
    config: AppConfig,
) -> ScoreBreakdown:
    triangle_quality, triangle_reasons, triangle_penalties = _triangle_quality(candidate, candles)
    breakout_quality, breakout_reasons, breakout_penalties = _breakout_quality(candidate, candles[-1], breakout_side, config.strategy.triangle.breakout_buffer_percent)
    trend_quality, trend_reasons, trend_penalties = _trend_quality(candles, pivots, breakout_side, config)
    zone_quality, zone_reasons, zone_penalties = _zone_quality(zones, breakout_side, risk_plan)
    risk_quality, risk_reasons, risk_penalties = _risk_quality(risk_plan, config)

    total = triangle_quality + breakout_quality + trend_quality + zone_quality + risk_quality
    return ScoreBreakdown(
        total_score=max(0.0, min(100.0, total)),
        triangle_quality=triangle_quality,
        breakout_quality=breakout_quality,
        trend_quality=trend_quality,
        zone_quality=zone_quality,
        risk_quality=risk_quality,
        reasons=triangle_reasons + breakout_reasons + trend_reasons + zone_reasons + risk_reasons,
        penalties=triangle_penalties + breakout_penalties + trend_penalties + zone_penalties + risk_penalties,
    )


def risk_percent_for_score(score: float, config: AppConfig) -> float | None:
    tiers = sorted(config.risk.score_risk_tiers, key=lambda item: item["min_score"], reverse=True)
    for tier in tiers:
        if score >= tier["min_score"]:
            return tier["risk_percent"]
    return None


def _triangle_quality(candidate: TriangleCandidate, candles: list[Candle]) -> tuple[float, list[str], list[str]]:
    score = 6.0
    reasons = ["valid triangle candidate"]
    penalties: list[str] = []
    score += min(4.0, (candidate.high_touch_count + candidate.low_touch_count - 4) * 1.5 + 4.0)
    score += candidate.convergence_percent * 4.0
    score += min(6.0, candidate.cleanliness_score * 0.3)
    if candidate.wick_violation_count:
        penalties.append("minor wick violations inside triangle")
    if candidate.close_violation_count:
        penalties.append("close violations inside triangle")
    return max(0.0, min(20.0, score)), reasons, penalties


def _breakout_quality(candidate: TriangleCandidate, candle: Candle, side: Side, buffer_percent: float) -> tuple[float, list[str], list[str]]:
    full_range = candle.high - candle.low
    body = abs(candle.close - candle.open)
    body_percent = body / full_range if full_range > 0 else 0.0
    if side == Side.LONG:
        boundary = triangle_upper_band_at(candidate.triangle, candidate.age + candidate.start_index, candidate.line_tolerance_used)
        close_distance = max(0.0, (candle.close - boundary.upper) / boundary.center)
        close_extreme = (candle.close - candle.low) / full_range if full_range > 0 else 0.0
        directional = candle.close > candle.open
    else:
        boundary = triangle_lower_band_at(candidate.triangle, candidate.age + candidate.start_index, candidate.line_tolerance_used)
        close_distance = max(0.0, (boundary.lower - candle.close) / boundary.center)
        close_extreme = (candle.high - candle.close) / full_range if full_range > 0 else 0.0
        directional = candle.close < candle.open
    score = 4.0 + min(6.0, close_distance / max(buffer_percent, 0.000001) * 3.0) + min(5.0, body_percent * 8.0) + min(5.0, close_extreme * 5.0)
    reasons = ["confirmed breakout"]
    penalties: list[str] = []
    if not directional:
        score -= 4.0
        penalties.append("breakout candle direction weak")
    return max(0.0, min(20.0, score)), reasons, penalties


def _trend_quality(candles: list[Candle], pivots: list[Pivot], side: Side, config: AppConfig) -> tuple[float, list[str], list[str]]:
    closes = [candle.close for candle in candles]
    fast = ema(closes, config.strategy.trend.ema_fast)
    slow = ema(closes, config.strategy.trend.ema_slow)
    ema_direction = TrendDirection.NEUTRAL
    if fast[-1] is not None and slow[-1] is not None:
        if fast[-1] > slow[-1]:
            ema_direction = TrendDirection.BULLISH
        elif fast[-1] < slow[-1]:
            ema_direction = TrendDirection.BEARISH
    struct = structure_trend(pivots)
    desired = TrendDirection.BULLISH if side == Side.LONG else TrendDirection.BEARISH
    score = 8.0
    reasons: list[str] = []
    penalties: list[str] = []
    if ema_direction == desired:
        score += 7.0
        reasons.append("EMA trend aligned")
    elif ema_direction == TrendDirection.NEUTRAL:
        score += 3.0
        reasons.append("EMA trend neutral")
    else:
        penalties.append("EMA trend mismatch")
    if struct == desired:
        score += 5.0
        reasons.append("market structure aligned")
    elif struct == TrendDirection.NEUTRAL:
        score += 2.0
    else:
        penalties.append("market structure mismatch")
    return max(0.0, min(20.0, score)), reasons, penalties


def _zone_quality(zones: list[StrongZone], side: Side, risk_plan: RiskPlan) -> tuple[float, list[str], list[str]]:
    risk = abs(risk_plan.entry_price - risk_plan.stop_loss)
    score = 12.0
    reasons: list[str] = []
    penalties: list[str] = []
    if risk <= 0:
        return 0.0, reasons, ["invalid risk distance"]
    if side == Side.LONG:
        support = nearest_support(zones, risk_plan.entry_price)
        opposite = nearest_resistance(zones, risk_plan.entry_price)
        if support:
            score += 4.0
            reasons.append("support below entry")
        distance = (opposite.low - risk_plan.entry_price) / risk if opposite else None
    else:
        resistance = nearest_resistance(zones, risk_plan.entry_price)
        opposite = nearest_support(zones, risk_plan.entry_price)
        if resistance:
            score += 4.0
            reasons.append("resistance above entry")
        distance = (risk_plan.entry_price - opposite.high) / risk if opposite else None
    if distance is None or distance >= risk_plan.reward_risk:
        score += 4.0
        reasons.append("no opposite zone before target")
    elif distance <= 0.5:
        score -= 10.0
        penalties.append("opposite zone within 0.5R")
    elif distance <= 1.0:
        score -= 6.0
        penalties.append("opposite zone within 1.0R")
    elif distance <= 1.5:
        score -= 3.0
        penalties.append("opposite zone within 1.5R")
    return max(0.0, min(20.0, score)), reasons, penalties


def _risk_quality(risk_plan: RiskPlan, config: AppConfig) -> tuple[float, list[str], list[str]]:
    rr = risk_plan.reward_risk
    if rr < config.risk.absolute_min_reward_risk:
        return 0.0, [], ["reward/risk below absolute minimum"]
    if rr < 1.5:
        return 6.0, ["reward/risk above absolute minimum"], ["reward/risk below 1.5"]
    if rr < config.risk.target_reward_risk:
        return 13.0, ["reward/risk below target but tradable"], ["reward/risk below target"]
    return 20.0, ["reward/risk target met"], []
