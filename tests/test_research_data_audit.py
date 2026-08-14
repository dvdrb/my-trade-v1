from __future__ import annotations

from app.core.types import Candle
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository
from scripts.audit_research_data import common_history


def _candle(symbol: str, timeframe: str, open_time: int) -> Candle:
    duration = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}[timeframe]
    return Candle(symbol, timeframe, open_time, 100, 101, 99, 100, 1, open_time + duration)


def test_common_history_detects_a_missing_cross_symbol_candle(tmp_path) -> None:
    db_path = tmp_path / "bot.sqlite3"
    init_db(db_path)
    with connect(db_path) as connection:
        repository = CandleRepository(connection)
        for symbol in ("BTC", "ETH", "SOL"):
            repository.insert_many([_candle(symbol, "15m", 0), _candle(symbol, "15m", 900_000), _candle(symbol, "15m", 1_800_000)])
        connection.execute("DELETE FROM candles WHERE symbol = 'SOL' AND timeframe = '15m' AND open_time = 900000")
        connection.commit()
        history = common_history(repository, ["BTC", "ETH", "SOL"])
    assert history["15m"]["common_candles"] == 2
    assert history["15m"]["common_gaps"] == 1
    assert history["15m"]["meets_minimum"] is False
