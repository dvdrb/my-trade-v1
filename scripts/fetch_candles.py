from __future__ import annotations

import argparse
from datetime import UTC, datetime

from app.data.db import DEFAULT_DB_PATH, connect, init_db
from app.data.repositories import CandleRepository
from app.exchange.hyperliquid_data import fetch_candles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--end", help="Exclusive UTC end timestamp (YYYY-MM-DD or ISO-8601); defaults to now")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()

    init_db(args.db)
    end_time = None
    if args.end:
        parsed = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
        end_time = int((parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed).timestamp() * 1000)
    candles = fetch_candles(args.symbol, args.timeframe, args.limit, end_time=end_time)
    with connect(args.db) as connection:
        CandleRepository(connection).insert_many(candles)
    gaps = sum(1 for previous, current in zip(candles, candles[1:]) if current.open_time - previous.open_time != {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}[args.timeframe])
    print(f"Fetched and stored {len(candles)} candles; internal gaps: {gaps}")


if __name__ == "__main__":
    main()
