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


def fetch_candles(symbol: str, timeframe: str, limit: int, end_time: int | None = None, batch_limit: int = 5_000) -> list[Candle]:
    """Fetch a chronological, deduplicated candle window without assuming one API response is sufficient."""
    if limit <= 0:
        return []
    interval_ms = INTERVAL_MS.get(timeframe)
    if interval_ms is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    if batch_limit <= 0:
        raise ValueError("batch_limit must be positive")

    window_end = end_time if end_time is not None else int(time.time() * 1000)
    window_start = window_end - interval_ms * limit
    candles_by_open_time: dict[int, Candle] = {}
    cursor = window_start

    while cursor < window_end:
        batch_end = min(cursor + interval_ms * batch_limit, window_end)
        payload = {
            "type": "candleSnapshot",
            "req": {"coin": symbol, "interval": timeframe, "startTime": cursor, "endTime": batch_end},
        }
        request = urllib.request.Request(API_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        for raw in data:
            candle = normalize_candle(raw, symbol, timeframe)
            if window_start <= candle.open_time < window_end:
                candles_by_open_time[candle.open_time] = candle
        cursor = batch_end

    return sorted(candles_by_open_time.values(), key=lambda candle: candle.open_time)[-limit:]
