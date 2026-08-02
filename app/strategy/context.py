from __future__ import annotations

from dataclasses import dataclass

from app.core.types import Candle


@dataclass(frozen=True)
class MarketContext:
    symbol: str
    entry_timeframe: str
    local_timeframe: str
    regime_timeframe: str
    entry_candles: list[Candle]
    local_candles: list[Candle]
    regime_candles: list[Candle]
