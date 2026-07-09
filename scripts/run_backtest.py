from __future__ import annotations

import argparse

from app.config.settings import load_config
from app.data.db import DEFAULT_DB_PATH, connect, init_db
from app.data.repositories import CandleRepository, SignalRepository, TradeRepository
from app.backtest.runner import run_backtest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()

    init_db(args.db)
    config = load_config()
    with connect(args.db) as connection:
        result = run_backtest(
            CandleRepository(connection),
            SignalRepository(connection),
            TradeRepository(connection),
            config,
            args.symbol,
            args.timeframe,
        )
    print(f"Backtest {result.run_id}: {result.summary}")


if __name__ == "__main__":
    main()
