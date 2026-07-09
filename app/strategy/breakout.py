from __future__ import annotations

from app.core.types import Candle, Side, Triangle
from app.strategy.triangle import triangle_lower_at, triangle_upper_at


def detect_breakout(candle: Candle, triangle: Triangle, index: int, buffer_percent: float, min_body_percent: float = 0.25) -> Side | None:
    body = abs(candle.close - candle.open)
    full_range = candle.high - candle.low
    if full_range <= 0 or body / full_range < min_body_percent:
        return None
    upper = triangle_upper_at(triangle, index)
    lower = triangle_lower_at(triangle, index)
    if candle.close > upper * (1 + buffer_percent):
        return Side.LONG
    if candle.close < lower * (1 - buffer_percent):
        return Side.SHORT
    return None
