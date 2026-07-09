from __future__ import annotations

from app.backtest.metrics import calculate_metrics
from app.backtest.runner import _maybe_close_trade, run_backtest
from app.config.settings import AppConfig
from app.core.types import Candle, Decision, Side, Signal, Trade
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository


def candle(time: int, open_: float = 100, high: float = 101, low: float = 99, close: float = 100) -> Candle:
    return Candle("BTC", "1h", time, open_, high, low, close)


def test_backtest_sequential_replay_no_lookahead_and_next_candle_entry(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "bot.sqlite3"
    init_db(db_path)
    calls: list[int] = []

    def fake_evaluate(candles, config, symbol, timeframe):
        calls.append(len(candles))
        if len(candles) == 2:
            return Signal("BTC", "1h", Decision.ACCEPTED, Side.LONG, entry_price=100, stop_loss=99, take_profit=102, reward_risk=2, strategy_version="test", open_time=candles[-1].open_time)
        return Signal("BTC", "1h", Decision.NO_SETUP, strategy_version="test", open_time=candles[-1].open_time)

    monkeypatch.setattr("app.backtest.runner.evaluate", fake_evaluate)
    with connect(db_path) as connection:
        repo = CandleRepository(connection)
        repo.insert_many([candle(1), candle(2), candle(3, open_=100, high=103, low=100), candle(4)])
        result = run_backtest(repo, None, None, AppConfig(), "BTC", "1h")
    assert calls == [2, 3, 4]
    assert result.trades[0].entry_time == 3


def test_fee_slippage_take_profit_stop_loss_and_ambiguous_conservative() -> None:
    long_trade = Trade("BTC", "1h", Side.LONG, 1, 100, 1, 95, 110)
    tp = _maybe_close_trade(long_trade, candle(2, high=111, low=100), 0.001, 0.001)
    sl = _maybe_close_trade(long_trade, candle(3, high=101, low=94), 0.001, 0.001)
    ambiguous = _maybe_close_trade(long_trade, candle(4, high=111, low=94), 0.0, 0.0)
    assert tp and tp.pnl < 10
    assert sl and sl.pnl < 0
    assert ambiguous and ambiguous.exit_price == 95


def test_metrics_and_report_files_generated(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    trade = Trade("BTC", "1h", Side.LONG, 1, 100, 1, 95, 110, 2, 110, 10, 2, "closed")
    signal = Signal("BTC", "1h", Decision.REJECTED, reasons=["bad trend"])
    metrics = calculate_metrics([trade], [signal], [1000, 1010])
    assert metrics["total_trades"] == 1
    assert metrics["rejection_counts_by_reason"] == {"bad trend": 1}
    from app.backtest.report import write_report

    directory = write_report("test-run", metrics, [trade], [signal], [(1, 1000)])
    assert (directory / "summary.json").exists()
    assert (directory / "trades.csv").exists()
    assert (directory / "signals.csv").exists()
