from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.core.types import Candle
from app.data.db import DEFAULT_DB_PATH, connect, init_db
from app.data.repositories import CandleRepository


def _float(row: dict[str, str], key: str) -> float:
    return float(row[key])


def load_csv(path: str, symbol: str, timeframe: str) -> list[Candle]:
    candles: list[Candle] = []
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    with csv_path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            candles.append(
                Candle(
                    symbol=row.get("symbol") or symbol,
                    timeframe=row.get("timeframe") or timeframe,
                    open_time=int(row["open_time"]),
                    close_time=int(row["close_time"]) if row.get("close_time") else None,
                    open=_float(row, "open"),
                    high=_float(row, "high"),
                    low=_float(row, "low"),
                    close=_float(row, "close"),
                    volume=float(row.get("volume") or 0),
                )
            )
    return candles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()

    init_db(args.db)
    candles = load_csv(args.csv_path, args.symbol, args.timeframe)
    with connect(args.db) as connection:
        CandleRepository(connection).insert_many(candles)
    print(f"Imported {len(candles)} candles into {args.db}")


if __name__ == "__main__":
    main()
