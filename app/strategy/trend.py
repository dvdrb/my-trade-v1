from __future__ import annotations

from app.core.types import Candle, Pivot, TrendDirection
from app.indicators.ema import ema


def ema_trend(candles: list[Candle], fast_period: int, slow_period: int) -> TrendDirection:
    if len(candles) < slow_period:
        return TrendDirection.NEUTRAL
    closes = [candle.close for candle in candles]
    fast = ema(closes, fast_period)[-1]
    slow = ema(closes, slow_period)[-1]
    if fast is None or slow is None:
        return TrendDirection.NEUTRAL
    if fast > slow and candles[-1].close > slow:
        return TrendDirection.BULLISH
    if fast < slow and candles[-1].close < slow:
        return TrendDirection.BEARISH
    return TrendDirection.NEUTRAL


def structure_trend(pivots: list[Pivot]) -> TrendDirection:
    highs = [pivot for pivot in pivots if pivot.kind == "high"][-2:]
    lows = [pivot for pivot in pivots if pivot.kind == "low"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return TrendDirection.NEUTRAL
    if highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price:
        return TrendDirection.BULLISH
    if highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price:
        return TrendDirection.BEARISH
    return TrendDirection.NEUTRAL
