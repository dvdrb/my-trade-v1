from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC

from app.backtest.metrics import calculate_metrics
from app.backtest.report import write_report
from app.config.settings import AppConfig
from app.core.types import Candle, Decision, Side, Signal, Trade
from app.data.repositories import CandleRepository, SignalRepository, TradeRepository
from app.strategy.evaluator import evaluate


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    signals: list[Signal]
    trades: list[Trade]
    summary: dict


def run_backtest(candle_repo: CandleRepository, signal_repo: SignalRepository | None, trade_repo: TradeRepository | None, config: AppConfig, symbol: str, timeframe: str) -> BacktestResult:
    candles = candle_repo.all(symbol, timeframe)
    signals: list[Signal] = []
    trades: list[Trade] = []
    equity = config.risk.starting_balance
    equity_curve: list[tuple[int, float]] = []
    open_trade: Trade | None = None
    pending_signal: Signal | None = None

    for index, candle in enumerate(candles):
        if open_trade is not None:
            closed = _maybe_close_trade(open_trade, candle, config.risk.fee_percent, config.risk.slippage_percent)
            if closed is not None:
                open_trade = closed
                equity += closed.pnl
                trades.append(closed)
                if trade_repo:
                    trade_repo.insert(closed)
                open_trade = None

        if pending_signal is not None and open_trade is None:
            open_trade = _open_trade(pending_signal, candle, config.risk.slippage_percent)
            pending_signal = None

        if index > 0:
            signal = evaluate(candles[: index + 1], config, symbol, timeframe)
            signals.append(signal)
            if signal_repo:
                signal_repo.insert(signal)
            if signal.decision == Decision.ACCEPTED and open_trade is None and pending_signal is None:
                pending_signal = signal
        equity_curve.append((candle.open_time, equity))

    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    summary = calculate_metrics(trades, signals, [item[1] for item in equity_curve])
    write_report(run_id, summary, trades, signals, equity_curve)
    return BacktestResult(run_id, signals, trades, summary)


def _open_trade(signal: Signal, candle: Candle, slippage_percent: float) -> Trade:
    assert signal.side and signal.stop_loss is not None and signal.take_profit is not None
    entry = candle.open * (1 + slippage_percent if signal.side == Side.LONG else 1 - slippage_percent)
    risk = abs(entry - signal.stop_loss)
    size = 1.0 if risk == 0 else 1.0 / risk
    return Trade(signal.symbol, signal.timeframe, signal.side, candle.open_time, entry, size, signal.stop_loss, signal.take_profit)


def _maybe_close_trade(trade: Trade, candle: Candle, fee_percent: float, slippage_percent: float) -> Trade | None:
    if trade.side == Side.LONG:
        stop_hit = candle.low <= trade.stop_loss
        target_hit = candle.high >= trade.take_profit
        if not stop_hit and not target_hit:
            return None
        raw_exit = trade.stop_loss if stop_hit else trade.take_profit
        exit_price = raw_exit * (1 - slippage_percent)
        pnl = (exit_price - trade.entry_price) * trade.size
        risk = trade.entry_price - trade.stop_loss
    else:
        stop_hit = candle.high >= trade.stop_loss
        target_hit = candle.low <= trade.take_profit
        if not stop_hit and not target_hit:
            return None
        raw_exit = trade.stop_loss if stop_hit else trade.take_profit
        exit_price = raw_exit * (1 + slippage_percent)
        pnl = (trade.entry_price - exit_price) * trade.size
        risk = trade.stop_loss - trade.entry_price
    fees = (trade.entry_price + exit_price) * trade.size * fee_percent
    pnl -= fees
    r_multiple = pnl / (risk * trade.size) if risk > 0 and trade.size > 0 else 0.0
    return Trade(
        trade.symbol,
        trade.timeframe,
        trade.side,
        trade.entry_time,
        trade.entry_price,
        trade.size,
        trade.stop_loss,
        trade.take_profit,
        candle.open_time,
        exit_price,
        pnl,
        r_multiple,
        "closed",
    )
