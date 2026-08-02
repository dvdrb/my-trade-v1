from __future__ import annotations

import argparse
from datetime import datetime, UTC

from app.config.settings import load_config
from app.data.db import DEFAULT_DB_PATH, connect, init_db
from app.data.repositories import CandleRepository, SignalRepository, TradeRepository
from app.backtest.runner import run_backtest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol")
    parser.add_argument("--timeframe")
    parser.add_argument("--config", default="app/config/strategy.yaml")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--start", help="Inclusive UTC date (YYYY-MM-DD)")
    parser.add_argument("--end", help="Exclusive UTC date (YYYY-MM-DD)")
    args = parser.parse_args()

    init_db(args.db)
    config = load_config(args.config)
    symbol = args.symbol or config.market.symbols[0]
    timeframe = args.timeframe or config.market.timeframe
    config.market.symbols = [symbol]
    config.market.timeframe = timeframe
    with connect(args.db) as connection:
        result = run_backtest(
            CandleRepository(connection),
            SignalRepository(connection),
            TradeRepository(connection),
            config,
            symbol,
            timeframe,
            _date_to_ms(args.start),
            _date_to_ms(args.end),
        )
    print(f"Backtest {result.run_id}: {result.summary}")


def _date_to_ms(value: str | None) -> int | None:
    if value is None:
        return None
    return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)


if __name__ == "__main__":
    main()
