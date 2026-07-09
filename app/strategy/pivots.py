from __future__ import annotations

from app.core.types import Candle, Pivot


def detect_pivots(candles: list[Candle], left: int, right: int) -> list[Pivot]:
    if left < 1 or right < 1:
        raise ValueError("left and right must be positive")
    pivots: list[Pivot] = []
    for index in range(left, len(candles) - right):
        candle = candles[index]
        left_window = candles[index - left : index]
        right_window = candles[index + 1 : index + right + 1]
        if candle.high > max(item.high for item in left_window) and candle.high >= max(item.high for item in right_window):
            pivots.append(Pivot(candle.symbol, candle.timeframe, candle.open_time, index, candle.high, "high"))
        if candle.low < min(item.low for item in left_window) and candle.low <= min(item.low for item in right_window):
            pivots.append(Pivot(candle.symbol, candle.timeframe, candle.open_time, index, candle.low, "low"))
    return pivots
