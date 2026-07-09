from __future__ import annotations

from app.config.settings import AppConfig
from app.core.types import Candle, Decision, Signal, Side, TrendDirection
from app.strategy.breakout import detect_breakout
from app.strategy.pivots import detect_pivots
from app.strategy.risk import calculate_risk_plan
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
