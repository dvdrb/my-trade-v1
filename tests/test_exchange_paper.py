from __future__ import annotations

from app.config.settings import AppConfig
from app.core.types import Candle, Decision, Side, Signal
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository, SignalRepository, TradeRepository
from app.exchange.hyperliquid_data import normalize_candle
from app.runtime.paper import PaperState, evaluate_new_closed_candles


def test_hyperliquid_candle_normalization() -> None:
    candle = normalize_candle({"t": 1, "T": 2, "o": "10", "h": "12", "l": "9", "c": "11", "v": "5"}, "BTC", "1h")
    assert candle.open_time == 1
    assert candle.close == 11


def test_duplicate_fetched_candles_are_not_inserted(tmp_path) -> None:
    db_path = tmp_path / "bot.sqlite3"
    init_db(db_path)
    candle = Candle("BTC", "1h", 1, 10, 12, 9, 11)
    with connect(db_path) as connection:
        repo = CandleRepository(connection)
        repo.insert_many([candle, candle])
        assert len(repo.all("BTC", "1h")) == 1


def test_paper_runner_evaluates_only_new_closed_candles_and_trades_locally(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "bot.sqlite3"
    init_db(db_path)
    calls = 0

    def fake_evaluate(candles, config, symbol, timeframe):
        nonlocal calls
        calls += 1
        return Signal("BTC", "1h", Decision.ACCEPTED, Side.LONG, reasons=["ok"], entry_price=100, stop_loss=95, take_profit=110, reward_risk=2, strategy_version="test")

    monkeypatch.setattr("app.runtime.paper.evaluate", fake_evaluate)
    with connect(db_path) as connection:
        signal_repo = SignalRepository(connection)
        trade_repo = TradeRepository(connection)
        state = PaperState()
        candles = [Candle("BTC", "1h", 1, 100, 101, 99, 100)]
        evaluate_new_closed_candles(candles, state, AppConfig(), signal_repo, trade_repo)
        evaluate_new_closed_candles(candles, state, AppConfig(), signal_repo, trade_repo)
        evaluate_new_closed_candles([*candles, Candle("BTC", "1h", 2, 100, 111, 99, 110)], state, AppConfig(), signal_repo, trade_repo)
        trades = connection.execute("SELECT status FROM trades").fetchall()
    assert calls == 2
    assert [row["status"] for row in trades] == ["open", "closed", "open"]
