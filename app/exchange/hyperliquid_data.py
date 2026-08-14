from __future__ import annotations

import json
import time
import urllib.request

from app.core.types import Candle


API_URL = "https://api.hyperliquid.xyz/info"
INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}
MAX_CANDLE_SNAPSHOT = 5_000


def normalize_candle(raw: dict, symbol: str, timeframe: str) -> Candle:
    def value(short_key: str, long_key: str):
        return raw[short_key] if short_key in raw else raw.get(long_key)

    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=int(value("t", "open_time")),
        close_time=int(value("T", "close_time")) if value("T", "close_time") is not None else None,
        open=float(value("o", "open")),
        high=float(value("h", "high")),
        low=float(value("l", "low")),
        close=float(value("c", "close")),
        volume=float(value("v", "volume") or 0),
    )


def fetch_candles(symbol: str, timeframe: str, limit: int, end_time: int | None = None) -> list[Candle]:
    """Fetch a chronological candle window from Hyperliquid's capped snapshot endpoint."""
    if limit <= 0:
        return []
    if limit > MAX_CANDLE_SNAPSHOT:
        raise ValueError(f"Hyperliquid candleSnapshot supports at most {MAX_CANDLE_SNAPSHOT} recent candles; use an archived source for longer history")
    interval_ms = INTERVAL_MS.get(timeframe)
    if interval_ms is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    window_end = end_time if end_time is not None else int(time.time() * 1000)
    window_start = window_end - interval_ms * limit
    payload = {
        "type": "candleSnapshot",
        "req": {"coin": symbol, "interval": timeframe, "startTime": window_start, "endTime": window_end},
    }
    request = urllib.request.Request(API_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    candles = {candle.open_time: candle for candle in (normalize_candle(raw, symbol, timeframe) for raw in data)}
    return [candle for candle in sorted(candles.values(), key=lambda item: item.open_time) if window_start <= candle.open_time < window_end][-limit:]
