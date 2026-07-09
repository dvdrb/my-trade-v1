from __future__ import annotations

import argparse

from app.config.settings import load_config
from app.core.logger import setup_logger
from app.data.db import DEFAULT_DB_PATH, connect, init_db
from app.data.repositories import CandleRepository, SignalRepository, TradeRepository
from app.runtime.paper import run_paper_loop


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()

    setup_logger()
    init_db(args.db)
    config = load_config()
    if not config.paper.enabled:
        raise SystemExit("paper trading is disabled")
    with connect(args.db) as connection:
        run_paper_loop(
            CandleRepository(connection),
            SignalRepository(connection),
            TradeRepository(connection),
            config,
            args.symbol,
            args.timeframe,
            args.poll_seconds,
        )


if __name__ == "__main__":
    main()
