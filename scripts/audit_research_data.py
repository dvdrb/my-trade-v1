from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.data.db import DEFAULT_DB_PATH, connect
from app.data.repositories import CandleRepository
from app.exchange.hyperliquid_data import INTERVAL_MS


REQUIREMENTS = {"15m": 20_000, "1h": 5_000, "4h": 2_000}


def audit_symbol(repo: CandleRepository, symbol: str) -> dict[str, object]:
    timeframes: dict[str, object] = {}
    for timeframe, minimum in REQUIREMENTS.items():
        candles = repo.all(symbol, timeframe)
        gaps = sum(
            1
            for previous, current in zip(candles, candles[1:])
            if current.open_time - previous.open_time != INTERVAL_MS[timeframe]
        )
        timeframes[timeframe] = {
            "candles": len(candles),
            "minimum_required": minimum,
            "meets_minimum": len(candles) >= minimum,
            "internal_gaps": gaps,
            "first": _iso(candles[0].open_time) if candles else None,
            "last": _iso(candles[-1].open_time) if candles else None,
        }
    return timeframes


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp / 1000, UTC).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail-closed data-quality audit for nested-MTF research.")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with connect(args.db) as connection:
        repo = CandleRepository(connection)
        result = {symbol: audit_symbol(repo, symbol) for symbol in args.symbols}
    result["research_ready"] = all(
        bool(values[timeframe]["meets_minimum"]) and int(values[timeframe]["internal_gaps"]) == 0
        for symbol, values in result.items()
        if symbol != "research_ready"
        for timeframe in REQUIREMENTS
    )
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if not result["research_ready"]:
        raise SystemExit("Research data audit failed: do not run optimization or validation splits.")


if __name__ == "__main__":
    main()
