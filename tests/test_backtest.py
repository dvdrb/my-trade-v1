from __future__ import annotations

from app.backtest.metrics import calculate_metrics
from app.backtest.runner import _maybe_close_trade, _open_trade, run_backtest
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

    def fake_evaluate(candles, config, symbol, timeframe, equity=None):
        calls.append(len(candles))
        if len(candles) == 2:
            return Signal(
                "BTC",
                "1h",
                Decision.ACCEPTED,
                Side.LONG,
                entry_price=100,
                stop_loss=99,
                take_profit=102,
                reward_risk=2,
                strategy_version="test",
                triangle_type="ascending",
                open_time=candles[-1].open_time,
                position_size=5,
                risk_amount=5,
            )
        return Signal("BTC", "1h", Decision.NO_SETUP, strategy_version="test", open_time=candles[-1].open_time)

    monkeypatch.setattr("app.backtest.runner.evaluate", fake_evaluate)
    with connect(db_path) as connection:
        repo = CandleRepository(connection)
        repo.insert_many([candle(1), candle(2), candle(3, open_=100, high=103, low=100), candle(4)])
        result = run_backtest(repo, None, None, AppConfig(), "BTC", "1h")
    assert calls == [2, 3, 4]
    assert result.trades[0].entry_time == 3
    assert result.trades[0].size == 5
    assert result.trades[0].signal_time == 2
    assert result.trades[0].strategy_version == "test"
    assert result.trades[0].triangle_type == "ascending"


def test_open_trade_uses_signal_position_size() -> None:
    signal = Signal(
        "BTC",
        "1h",
        Decision.ACCEPTED,
        Side.LONG,
        entry_price=100,
        stop_loss=95,
        take_profit=110,
        strategy_version="test",
        triangle_type="symmetrical",
        open_time=10,
        position_size=2.5,
        risk_amount=12.5,
    )
    trade = _open_trade(signal, candle(11, open_=100), 0.0)
    assert trade.size == 2.5
    assert trade.risk_amount == 12.5
    assert trade.signal_time == 10


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
    trade = Trade("BTC", "1h", Side.LONG, 1, 100, 1, 95, 110, 2, 110, 10, 2, "closed", 1, "test", "ascending", 5, 82, 16, 18, 20, 17, 1, 0, 0.001, 0.0, 0.002)
    signal = Signal("BTC", "1h", Decision.REJECTED, reasons=["bad trend"], metadata={"triangle_candidates_found": 2, "breakout_candidates_found": 1, "scored_candidates": 1, "rejected_by_score": 1})
    metrics = calculate_metrics([trade], [signal], [1000, 1010])
    assert metrics["total_trades"] == 1
    assert metrics["expectancy_r"] == 2
    assert metrics["expectancy_usd"] == 10
    assert metrics["total_pnl"] == 10
    assert metrics["performance_by_triangle_type"]["ascending"]["trades"] == 1
    assert metrics["score_bucket_performance"]["80_100"]["trades"] == 1
    assert metrics["performance_by_trend_score_bucket"]["15_20"]["trades"] == 1
    assert metrics["performance_by_zone_score_bucket"]["15_20"]["trades"] == 1
    assert metrics["performance_by_risk_score_bucket"]["15_20"]["trades"] == 1
    assert metrics["performance_by_triangle_cleanliness_bucket"]["15_20"]["trades"] == 1
    assert metrics["candidate_funnel"]["triangle_candidates_found"] == 2
    assert metrics["candidate_funnel"]["rejected_by_score"] == 1
    assert metrics["rejection_counts_by_reason"] == {"bad trend": 1}
    from app.backtest.report import write_report

    directory = write_report("test-run", metrics, [trade], [], [signal], [(1, 1000)])
    assert (directory / "summary.json").exists()
    assert (directory / "trades.csv").exists()
    assert (directory / "open_trades.csv").exists()
    assert (directory / "signals.csv").exists()


def test_skipped_accepted_signals_and_open_trade_at_end_are_reported(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "bot.sqlite3"
    init_db(db_path)

    def fake_evaluate(candles, config, symbol, timeframe, equity=None):
        return Signal(
            "BTC",
            timeframe,
            Decision.ACCEPTED,
            Side.LONG,
            entry_price=100,
            stop_loss=95,
            take_profit=150,
            reward_risk=10,
            strategy_version="test",
            triangle_type="symmetrical",
            open_time=candles[-1].open_time,
            position_size=1,
            risk_amount=5,
        )

    monkeypatch.setattr("app.backtest.runner.evaluate", fake_evaluate)
    with connect(db_path) as connection:
        repo = CandleRepository(connection)
        repo.insert_many([candle(1), candle(2), candle(3), candle(4), candle(5, close=104)])
        result = run_backtest(repo, None, None, AppConfig(), "BTC", "1h")

    assert result.summary["accepted_signals"] == 4
    assert result.summary["trades_opened"] == 1
    assert result.summary["closed_trades"] == 0
    assert result.summary["open_trades_at_end"] == 1
    assert result.summary["skipped_already_in_position"] == 3
    assert result.summary["skipped_pending_signal_exists"] == 0
    assert result.summary["skipped_end_of_backtest"] == 0
    assert result.open_trades[0].status == "open"
    assert round(result.open_trades[0].pnl, 2) == 3.95


def test_pending_signal_at_end_is_reported_as_skipped(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "bot.sqlite3"
    init_db(db_path)

    def fake_evaluate(candles, config, symbol, timeframe, equity=None):
        if len(candles) == 3:
            return Signal(
                "BTC",
                timeframe,
                Decision.ACCEPTED,
                Side.LONG,
                entry_price=100,
                stop_loss=95,
                take_profit=110,
                strategy_version="test",
                open_time=candles[-1].open_time,
                position_size=1,
                risk_amount=5,
            )
        return Signal("BTC", timeframe, Decision.NO_SETUP, strategy_version="test", open_time=candles[-1].open_time)

    monkeypatch.setattr("app.backtest.runner.evaluate", fake_evaluate)
    with connect(db_path) as connection:
        repo = CandleRepository(connection)
        repo.insert_many([candle(1), candle(2), candle(3)])
        result = run_backtest(repo, None, None, AppConfig(), "BTC", "1h")

    assert result.summary["accepted_signals"] == 1
    assert result.summary["trades_opened"] == 0
    assert result.summary["skipped_end_of_backtest"] == 1


def test_15m_timeframe_passes_through_backtest_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "bot.sqlite3"
    init_db(db_path)
    seen: list[str] = []

    def fake_evaluate(candles, config, symbol, timeframe, equity=None):
        seen.append(timeframe)
        return Signal("BTC", timeframe, Decision.NO_SETUP, strategy_version="test", open_time=candles[-1].open_time)

    monkeypatch.setattr("app.backtest.runner.evaluate", fake_evaluate)
    with connect(db_path) as connection:
        repo = CandleRepository(connection)
        repo.insert_many([Candle("BTC", "15m", time, 1, 2, 0.5, 1.5) for time in [1, 2, 3]])
        run_backtest(repo, None, None, AppConfig(), "BTC", "15m")
    assert seen == ["15m", "15m"]
