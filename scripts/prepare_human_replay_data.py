from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app.annotation.research_range import human_research_bounds
from app.core.types import Candle
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository


def load_approved_candles(source: Path, research_start: int, research_end: int) -> list[Candle]:
    """Read only the train/validation portion of a verified local research source."""
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT symbol, timeframe, open_time, close_time, open, high, low, close, volume
        FROM candles
        WHERE timeframe IN ('15m', '1h', '4h')
          AND open_time >= ?
          AND COALESCE(close_time, open_time) < ?
        ORDER BY symbol, timeframe, open_time
        """,
        (research_start, research_end),
    ).fetchall()
    connection.close()
    return [
        Candle(
            symbol=row["symbol"], timeframe=row["timeframe"], open_time=row["open_time"],
            close_time=row["close_time"], open=row["open"], high=row["high"], low=row["low"],
            close=row["close"], volume=row["volume"],
        )
        for row in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a holdout-free local database for human replay capture.")
    parser.add_argument("--source", type=Path, default=Path("data/research.sqlite3"))
    parser.add_argument("--target", type=Path, default=Path("data/human_replay.sqlite3"))
    parser.add_argument("--periods", type=Path, default=Path("app/config/research_periods.yaml"))
    parser.add_argument("--manifest", type=Path, default=Path("data/human_replay_manifest.json"))
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit(f"approved research source is missing: {args.source}")
    if args.target.exists():
        raise SystemExit(f"refusing to overwrite existing replay database: {args.target}")

    research_start, research_end = human_research_bounds(args.periods)
    candles = load_approved_candles(args.source, research_start, research_end)
    expected = {"BTC", "ETH", "SOL"}
    if {candle.symbol for candle in candles} != expected or {candle.timeframe for candle in candles} != {"15m", "1h", "4h"}:
        raise SystemExit("source does not contain all required symbols and timeframes in the approved interval")
    if any((candle.close_time or candle.open_time) >= research_end for candle in candles):
        raise SystemExit("refusing to copy a final-holdout candle into the human replay database")

    init_db(args.target)
    repository = CandleRepository(connect(args.target))
    for symbol in sorted(expected):
        for timeframe in ("15m", "1h", "4h"):
            repository.insert_many([candle for candle in candles if candle.symbol == symbol and candle.timeframe == timeframe])
    counts = {f"{symbol}:{timeframe}": sum(candle.symbol == symbol and candle.timeframe == timeframe for candle in candles) for symbol in sorted(expected) for timeframe in ("15m", "1h", "4h")}
    args.manifest.write_text(json.dumps({
        "source": str(args.source), "target": str(args.target), "research_start": research_start,
        "research_end_exclusive": research_end, "holdout_candles_copied": 0, "counts": counts,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Created holdout-free replay data: {args.target}")


if __name__ == "__main__":
    main()
