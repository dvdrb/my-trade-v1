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
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=int(raw.get("t") or raw.get("open_time")),
        close_time=int(raw.get("T") or raw.get("close_time")) if raw.get("T") or raw.get("close_time") else None,
        open=float(raw.get("o") or raw.get("open")),
        high=float(raw.get("h") or raw.get("high")),
        low=float(raw.get("l") or raw.get("low")),
        close=float(raw.get("c") or raw.get("close")),
        volume=float(raw.get("v") or raw.get("volume") or 0),
    )


def fetch_candles(symbol: str, timeframe: str, limit: int) -> list[Candle]:
    now_ms = int(time.time() * 1000)
    interval_ms = INTERVAL_MS.get(timeframe)
    if interval_ms is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    start_time = now_ms - interval_ms * limit
    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": symbol,
            "interval": timeframe,
            "startTime": start_time,
            "endTime": now_ms,
        },
    }
    request = urllib.request.Request(API_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [normalize_candle(item, symbol, timeframe) for item in data][-limit:]
