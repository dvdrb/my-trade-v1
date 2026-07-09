from __future__ import annotations

from app.config.settings import load_config
from app.core.types import Candle
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository


def test_config_loads_with_safe_defaults() -> None:
    config = load_config()
    assert config.mode == "paper"
    assert config.paper.enabled is True


def test_sqlite_init_and_idempotent_candle_insert(tmp_path) -> None:
    db_path = tmp_path / "bot.sqlite3"
    init_db(db_path)
    with connect(db_path) as connection:
        repo = CandleRepository(connection)
        candle = Candle("BTC", "1h", 1, 10, 12, 9, 11, 100)
        repo.insert_many([candle, candle])
        rows = connection.execute("SELECT COUNT(*) AS count FROM candles").fetchone()
    assert rows["count"] == 1


def test_latest_candles_are_ordered_by_time(tmp_path) -> None:
    db_path = tmp_path / "bot.sqlite3"
    init_db(db_path)
    with connect(db_path) as connection:
        repo = CandleRepository(connection)
        repo.insert_many([Candle("BTC", "1h", time, 1, 2, 0.5, 1.5) for time in [3, 1, 2]])
        candles = repo.latest("BTC", "1h", 2)
    assert [candle.open_time for candle in candles] == [2, 3]
