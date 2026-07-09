from __future__ import annotations

from app.config.settings import AppConfig
from app.core.types import Candle, Decision, Signal, Side, TrendDirection
from app.strategy.breakout import detect_breakout
from app.strategy.candidates import TriangleCandidate, find_triangle_candidates
from app.strategy.pivots import detect_pivots
from app.strategy.risk import RiskPlan, calculate_risk_plan
from app.strategy.scoring import ScoreBreakdown, risk_percent_for_score, score_candidate
from app.strategy.trend import ema_trend, structure_trend
from app.strategy.triangle import detect_triangle
from app.strategy.zones import blocking_opposite_zone, build_zones


def evaluate(candles: list[Candle], config: AppConfig, symbol: str | None = None, timeframe: str | None = None, equity: float | None = None) -> Signal:
    actual_symbol = symbol or (candles[-1].symbol if candles else config.market.symbols[0])
    actual_timeframe = timeframe or (candles[-1].timeframe if candles else config.market.timeframe)
    if len(candles) < config.strategy.triangle.min_candles + config.strategy.pivots.right + 2:
        return Signal(actual_symbol, actual_timeframe, Decision.NO_SETUP, reasons=["not enough candles"], strategy_version=config.strategy.version)

    current_index = len(candles) - 1
    pivots = detect_pivots(candles, config.strategy.pivots.left, config.strategy.pivots.right)
    if config.strategy.scoring.use_scoring_model:
        return _evaluate_scoring(candles, config, actual_symbol, actual_timeframe, equity, pivots, current_index)

    triangle = detect_triangle(
        pivots,
        current_index,
        config.strategy.triangle.min_candles,
        config.strategy.triangle.max_candles,
        config.strategy.triangle.flat_tolerance_percent,
    )
    if triangle is None:
        return Signal(actual_symbol, actual_timeframe, Decision.NO_SETUP, reasons=["no valid triangle"], strategy_version=config.strategy.version, open_time=candles[-1].open_time)

    side = detect_breakout(
        candles[-1],
        triangle,
        current_index,
        config.strategy.triangle.breakout_buffer_percent,
        config.strategy.breakout.min_body_percent,
        config.strategy.triangle.line_tolerance_percent,
    )
    if side is None:
        return Signal(actual_symbol, actual_timeframe, Decision.NO_SETUP, reasons=["no confirmed breakout"], strategy_version=config.strategy.version, triangle_type=triangle.kind, open_time=candles[-1].open_time)

    reasons: list[str] = []
    trend = ema_trend(candles, config.strategy.trend.ema_fast, config.strategy.trend.ema_slow)
    if trend == TrendDirection.NEUTRAL:
        trend = structure_trend(pivots)
    if config.strategy.trend.require_alignment:
        if side == Side.LONG and trend != TrendDirection.BULLISH:
            reasons.append("trend is not bullish for long")
        if side == Side.SHORT and trend != TrendDirection.BEARISH:
            reasons.append("trend is not bearish for short")

    risk = calculate_risk_plan(
        side,
        candles[-1].close,
        pivots,
        triangle,
        current_index,
        equity if equity is not None else config.risk.starting_balance,
        config.risk.risk_per_trade_percent,
        config.risk.min_reward_risk,
    )
    if risk is None:
        reasons.append("invalid risk reward")

    zones = build_zones(pivots, config.strategy.zones.tolerance_percent, config.strategy.zones.min_touches)
    metadata: dict[str, object] = {}
    zone_block = None
    if risk:
        zone_block = blocking_opposite_zone(zones, side, risk.entry_price, risk.stop_loss, config.strategy.zones.avoid_opposite_zone_within_r)
    if zone_block:
        reasons.append("blocked by nearby opposite zone")
        metadata["zone_block"] = zone_block

    if reasons:
        return Signal(
            actual_symbol,
            actual_timeframe,
            Decision.REJECTED,
            side=side,
            reasons=reasons,
            strategy_version=config.strategy.version,
            triangle_type=triangle.kind,
            open_time=candles[-1].open_time,
            metadata=metadata,
        )

    assert risk is not None
    return Signal(
        actual_symbol,
        actual_timeframe,
        Decision.ACCEPTED,
        side=side,
        score=1.0,
        reasons=["triangle breakout confirmed", f"{trend.value} trend aligned"],
        entry_price=risk.entry_price,
        stop_loss=risk.stop_loss,
        take_profit=risk.take_profit,
        reward_risk=risk.reward_risk,
        strategy_version=config.strategy.version,
        triangle_type=triangle.kind,
        open_time=candles[-1].open_time,
        position_size=risk.position_size,
        risk_amount=(equity if equity is not None else config.risk.starting_balance) * config.risk.risk_per_trade_percent,
    )


def _evaluate_scoring(
    candles: list[Candle],
    config: AppConfig,
    symbol: str,
    timeframe: str,
    equity: float | None,
    pivots,
    current_index: int,
) -> Signal:
    current_equity = equity if equity is not None else config.risk.starting_balance
    zones = build_zones(pivots, config.strategy.zones.tolerance_percent, config.strategy.zones.min_touches)
    candidates = find_triangle_candidates(
        pivots,
        current_index,
        config.strategy.triangle.min_candles,
        config.strategy.triangle.max_candles,
        config.strategy.triangle.flat_tolerance_percent,
        config.strategy.triangle.max_candidates,
        candles,
        config.strategy.triangle.line_tolerance_percent,
        config.strategy.triangle.max_wick_violation_percent,
        config.strategy.triangle.max_close_violation_percent,
        config.strategy.triangle.max_allowed_close_violations,
        config.strategy.triangle.max_allowed_wick_violations,
    )
    funnel = {
        "candidate_count": len(candidates),
        "triangle_candidates_found": len(candidates),
        "breakout_candidates_found": 0,
        "scored_candidates": 0,
        "rejected_by_absolute_risk": 0,
        "rejected_by_score": 0,
    }
    if not candidates:
        return Signal(symbol, timeframe, Decision.NO_SETUP, reasons=["no triangle candidates"], strategy_version=config.strategy.version, open_time=candles[-1].open_time, metadata=funnel)

    scored: list[tuple[TriangleCandidate, Side, RiskPlan, ScoreBreakdown, dict[str, object]]] = []
    for candidate in candidates:
        side = detect_breakout(
            candles[-1],
            candidate.triangle,
            current_index,
            config.strategy.triangle.breakout_buffer_percent,
            config.strategy.breakout.min_body_percent,
            config.strategy.triangle.line_tolerance_percent,
        )
        if side is None:
            continue
        funnel["breakout_candidates_found"] += 1
        risk = calculate_risk_plan(
            side,
            candles[-1].close,
            pivots,
            candidate.triangle,
            current_index,
            current_equity,
            config.risk.risk_per_trade_percent,
            config.risk.absolute_min_reward_risk,
            config.risk.target_reward_risk,
        )
        if risk is None:
            funnel["rejected_by_absolute_risk"] += 1
            continue
        score = score_candidate(candidate, candles, pivots, zones, side, risk, config)
        funnel["scored_candidates"] += 1
        zone_block = blocking_opposite_zone(zones, side, risk.entry_price, risk.stop_loss, config.strategy.zones.avoid_opposite_zone_within_r)
        scored.append((candidate, side, risk, score, {"zone_block": zone_block} if zone_block else {}))

    if not scored:
        decision = Decision.REJECTED if funnel["breakout_candidates_found"] else Decision.NO_SETUP
        reason = "no risk-valid breakout candidates" if decision == Decision.REJECTED else "no confirmed breakout candidates"
        return Signal(symbol, timeframe, decision, reasons=[reason], strategy_version=config.strategy.version, open_time=candles[-1].open_time, metadata=funnel)

    scored.sort(key=lambda item: item[3].total_score, reverse=True)
    candidate, side, risk, score, extra_metadata = scored[0]
    metadata = _score_metadata(score, funnel, candidate_count=len(candidates), candidate_rank=1)
    metadata.update(_triangle_cleanliness_metadata(candidate))
    metadata.update(extra_metadata)

    reasons: list[str] = []
    trend_hard_reject = config.strategy.scoring.trend_as_hard_filter and any("trend mismatch" in item for item in score.penalties)
    zone_hard_reject = config.strategy.scoring.zone_as_hard_filter and "zone_block" in extra_metadata
    risk_percent = risk_percent_for_score(score.total_score, config)
    if trend_hard_reject:
        reasons.append("trend rejected by hard filter")
    if zone_hard_reject:
        reasons.append("zone rejected by hard filter")
    if score.total_score < config.strategy.scoring.min_trade_score or risk_percent is None:
        reasons.append("score below minimum")
        metadata["rejected_by_score"] = 1
    if reasons:
        funnel["rejected_by_score"] += 1
        metadata.update(funnel)
        return Signal(
            symbol,
            timeframe,
            Decision.REJECTED,
            side=side,
            score=score.total_score,
            reasons=reasons,
            entry_price=risk.entry_price,
            stop_loss=risk.stop_loss,
            take_profit=risk.take_profit,
            reward_risk=risk.reward_risk,
            strategy_version=config.strategy.version,
            triangle_type=candidate.triangle_type,
            open_time=candles[-1].open_time,
            metadata=metadata,
        )

    assert risk_percent is not None
    sized_risk = calculate_risk_plan(
        side,
        candles[-1].close,
        pivots,
        candidate.triangle,
        current_index,
        current_equity,
        risk_percent,
        config.risk.absolute_min_reward_risk,
        config.risk.target_reward_risk,
    )
    assert sized_risk is not None
    return Signal(
        symbol,
        timeframe,
        Decision.ACCEPTED,
        side=side,
        score=score.total_score,
        reasons=score.reasons,
        entry_price=sized_risk.entry_price,
        stop_loss=sized_risk.stop_loss,
        take_profit=sized_risk.take_profit,
        reward_risk=sized_risk.reward_risk,
        strategy_version=config.strategy.version,
        triangle_type=candidate.triangle_type,
        open_time=candles[-1].open_time,
        position_size=sized_risk.position_size,
        risk_amount=current_equity * risk_percent,
        metadata=metadata,
    )


def _score_metadata(score: ScoreBreakdown, funnel: dict[str, int], candidate_count: int, candidate_rank: int) -> dict[str, object]:
    return {
        **funnel,
        "score_total": score.total_score,
        "score_triangle_quality": score.triangle_quality,
        "score_breakout_quality": score.breakout_quality,
        "score_trend_quality": score.trend_quality,
        "score_zone_quality": score.zone_quality,
        "score_risk_quality": score.risk_quality,
        "score_reasons": score.reasons,
        "score_penalties": score.penalties,
        "candidate_count": candidate_count,
        "candidate_rank": candidate_rank,
    }


def _triangle_cleanliness_metadata(candidate: TriangleCandidate) -> dict[str, object]:
    return {
        "triangle_cleanliness_score": candidate.cleanliness_score,
        "triangle_wick_violation_count": candidate.wick_violation_count,
        "triangle_close_violation_count": candidate.close_violation_count,
        "triangle_max_wick_violation": candidate.max_wick_violation,
        "triangle_max_close_violation": candidate.max_close_violation,
        "triangle_line_tolerance_used": candidate.line_tolerance_used,
    }
