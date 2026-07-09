from __future__ import annotations

import argparse

from app.data.db import DEFAULT_DB_PATH, connect, init_db
from app.data.repositories import CandleRepository
from app.exchange.hyperliquid_data import fetch_candles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()

    init_db(args.db)
    candles = fetch_candles(args.symbol, args.timeframe, args.limit)
    with connect(args.db) as connection:
        CandleRepository(connection).insert_many(candles)
    print(f"Fetched and stored {len(candles)} candles")


if __name__ == "__main__":
    main()
