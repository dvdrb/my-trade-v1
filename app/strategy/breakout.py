from __future__ import annotations

from app.core.types import Candle, Side, Triangle
from app.strategy.triangle import triangle_lower_band_at, triangle_upper_band_at


def detect_breakout(candle: Candle, triangle: Triangle, index: int, buffer_percent: float, min_body_percent: float = 0.25, line_tolerance_percent: float = 0.0) -> Side | None:
    body = abs(candle.close - candle.open)
    full_range = candle.high - candle.low
    if full_range <= 0 or body / full_range < min_body_percent:
        return None
    upper = triangle_upper_band_at(triangle, index, line_tolerance_percent)
    lower = triangle_lower_band_at(triangle, index, line_tolerance_percent)
    if candle.close > upper.upper * (1 + buffer_percent):
        return Side.LONG
    if candle.close < lower.lower * (1 - buffer_percent):
        return Side.SHORT
    return None
