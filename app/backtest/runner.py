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
    open_trades: list[Trade]
    summary: dict


def run_backtest(candle_repo: CandleRepository, signal_repo: SignalRepository | None, trade_repo: TradeRepository | None, config: AppConfig, symbol: str, timeframe: str) -> BacktestResult:
    candles = candle_repo.all(symbol, timeframe)
    signals: list[Signal] = []
    trades: list[Trade] = []
    open_trades_at_end: list[Trade] = []
    equity = config.risk.starting_balance
    equity_curve: list[tuple[int, float]] = []
    open_trade: Trade | None = None
    pending_signal: Signal | None = None
    funnel = {
        "trades_opened": 0,
        "closed_trades": 0,
        "open_trades_at_end": 0,
        "skipped_already_in_position": 0,
        "skipped_pending_signal_exists": 0,
        "skipped_end_of_backtest": 0,
        "skipped_actual_entry_invalid_rr": 0,
    }

    for index, candle in enumerate(candles):
        if open_trade is not None:
            closed = _maybe_close_trade(open_trade, candle, config.risk.fee_percent, config.risk.slippage_percent)
            if closed is not None:
                open_trade = closed
                equity += closed.pnl
                trades.append(closed)
                funnel["closed_trades"] += 1
                if trade_repo:
                    trade_repo.insert(closed)
                open_trade = None

        if pending_signal is not None and open_trade is None:
            open_trade, skip_reason = try_open_trade(pending_signal, candle, config)
            if open_trade is None:
                if skip_reason == "actual_entry_invalid_rr":
                    funnel["skipped_actual_entry_invalid_rr"] += 1
            else:
                funnel["trades_opened"] += 1
            pending_signal = None

        if index > 0:
            signal = evaluate(candles[: index + 1], config, symbol, timeframe, equity)
            signals.append(signal)
            if signal_repo:
                signal_repo.insert(signal)
            if signal.decision == Decision.ACCEPTED:
                if open_trade is not None:
                    funnel["skipped_already_in_position"] += 1
                elif pending_signal is not None:
                    funnel["skipped_pending_signal_exists"] += 1
                else:
                    pending_signal = signal
        equity_curve.append((candle.open_time, equity))

    if pending_signal is not None:
        funnel["skipped_end_of_backtest"] += 1
    if open_trade is not None and candles:
        open_trades_at_end.append(_mark_unrealized(open_trade, candles[-1]))
    funnel["open_trades_at_end"] = len(open_trades_at_end)

    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    summary = calculate_metrics(
        trades,
        signals,
        [item[1] for item in equity_curve],
        open_trades_at_end,
        funnel,
        {
            "strategy_version": config.strategy.version,
            "symbol": symbol,
            "timeframe": timeframe,
            "use_scoring_model": config.strategy.scoring.use_scoring_model,
            "min_trade_score": config.strategy.scoring.min_trade_score,
        },
    )
    write_report(run_id, summary, trades, open_trades_at_end, signals, equity_curve)
    return BacktestResult(run_id, signals, trades, open_trades_at_end, summary)


def _open_trade(signal: Signal, candle: Candle, slippage_percent: float) -> Trade:
    trade, skip_reason = _build_trade(signal, candle, slippage_percent, None)
    if trade is None:
        raise ValueError(skip_reason or "invalid trade")
    return trade


def try_open_trade(signal: Signal, candle: Candle, config: AppConfig) -> tuple[Trade | None, str | None]:
    return _build_trade(signal, candle, config.risk.slippage_percent, config.risk.absolute_min_reward_risk)


def _build_trade(signal: Signal, candle: Candle, slippage_percent: float, absolute_min_reward_risk: float | None) -> tuple[Trade | None, str | None]:
    assert signal.side and signal.stop_loss is not None and signal.take_profit is not None
    if signal.risk_amount is None and signal.position_size is None:
        return None, "accepted signal is missing risk sizing"
    entry = candle.open * (1 + slippage_percent if signal.side == Side.LONG else 1 - slippage_percent)
    if signal.side == Side.LONG:
        actual_risk = entry - signal.stop_loss
        actual_reward = signal.take_profit - entry
    else:
        actual_risk = signal.stop_loss - entry
        actual_reward = entry - signal.take_profit
    if actual_risk <= 0:
        return None, "actual_entry_invalid_rr"
    actual_rr = actual_reward / actual_risk
    if absolute_min_reward_risk is not None and actual_rr < absolute_min_reward_risk:
        return None, "actual_entry_invalid_rr"
    size = signal.risk_amount / actual_risk if signal.risk_amount is not None else signal.position_size
    if size is None or size <= 0:
        return None, "accepted signal is missing position_size"
    return Trade(
        signal.symbol,
        signal.timeframe,
        signal.side,
        candle.open_time,
        entry,
        size,
        signal.stop_loss,
        signal.take_profit,
        signal_time=signal.open_time,
        strategy_version=signal.strategy_version,
        triangle_type=signal.triangle_type,
        risk_amount=signal.risk_amount,
        score_total=_metadata_float(signal, "score_total"),
        score_trend_quality=_metadata_float(signal, "score_trend_quality"),
        score_zone_quality=_metadata_float(signal, "score_zone_quality"),
        score_risk_quality=_metadata_float(signal, "score_risk_quality"),
        triangle_cleanliness_score=_metadata_float(signal, "triangle_cleanliness_score"),
        triangle_wick_violation_count=_metadata_int(signal, "triangle_wick_violation_count"),
        triangle_close_violation_count=_metadata_int(signal, "triangle_close_violation_count"),
        triangle_max_wick_violation=_metadata_float(signal, "triangle_max_wick_violation"),
        triangle_max_close_violation=_metadata_float(signal, "triangle_max_close_violation"),
        triangle_line_tolerance_used=_metadata_float(signal, "triangle_line_tolerance_used"),
    ), None


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
        trade.signal_time,
        trade.strategy_version,
        trade.triangle_type,
        trade.risk_amount,
        trade.score_total,
        trade.score_trend_quality,
        trade.score_zone_quality,
        trade.score_risk_quality,
        trade.triangle_cleanliness_score,
        trade.triangle_wick_violation_count,
        trade.triangle_close_violation_count,
        trade.triangle_max_wick_violation,
        trade.triangle_max_close_violation,
        trade.triangle_line_tolerance_used,
    )


def _mark_unrealized(trade: Trade, candle: Candle) -> Trade:
    if trade.side == Side.LONG:
        pnl = (candle.close - trade.entry_price) * trade.size
        risk = trade.entry_price - trade.stop_loss
    else:
        pnl = (trade.entry_price - candle.close) * trade.size
        risk = trade.stop_loss - trade.entry_price
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
        candle.close,
        pnl,
        r_multiple,
        "open",
        trade.signal_time,
        trade.strategy_version,
        trade.triangle_type,
        trade.risk_amount,
        trade.score_total,
        trade.score_trend_quality,
        trade.score_zone_quality,
        trade.score_risk_quality,
        trade.triangle_cleanliness_score,
        trade.triangle_wick_violation_count,
        trade.triangle_close_violation_count,
        trade.triangle_max_wick_violation,
        trade.triangle_max_close_violation,
        trade.triangle_line_tolerance_used,
    )


def _metadata_float(signal: Signal, key: str) -> float | None:
    value = signal.metadata.get(key)
    return float(value) if isinstance(value, int | float) else None


def _metadata_int(signal: Signal, key: str) -> int | None:
    value = signal.metadata.get(key)
    return int(value) if isinstance(value, int | float) else None
