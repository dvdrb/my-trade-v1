from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, UTC

from app.backtest.metrics import calculate_metrics
from app.backtest.report import write_report
from app.config.settings import AppConfig
from app.core.types import Candle, Decision, Side, Signal, Trade
from app.data.repositories import CandleRepository, SignalRepository, TradeRepository
from app.strategy.evaluator import evaluate
from app.strategy.context import MarketContext


_TIMEFRAME_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def closed_candles_as_of(candles: list[Candle], timestamp: int, timeframe: str) -> list[Candle]:
    """Return only candles whose close is known at ``timestamp``; missing close times use the timeframe."""
    duration = _TIMEFRAME_MS.get(timeframe)
    if duration is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return [candle for candle in candles if (candle.close_time if candle.close_time is not None else candle.open_time + duration) <= timestamp]


@dataclass(frozen=True)
class BacktestResult:
    run_id: str
    signals: list[Signal]
    trades: list[Trade]
    open_trades: list[Trade]
    summary: dict


def run_backtest(candle_repo: CandleRepository, signal_repo: SignalRepository | None, trade_repo: TradeRepository | None, config: AppConfig, symbol: str, timeframe: str, start_time: int | None = None, end_time: int | None = None, config_name: str | None = None, start_date: str | None = None, end_date: str | None = None) -> BacktestResult:
    candles = candle_repo.all(symbol, timeframe)
    candles = [candle for candle in candles if end_time is None or candle.open_time < end_time]
    entry_timeframe = config.market.entry_timeframe or timeframe
    local_timeframe = config.market.local_timeframe or entry_timeframe
    regime_timeframe = config.market.regime_timeframe or local_timeframe
    local_all = candle_repo.all(symbol, local_timeframe) if config.strategy.scoring.use_nested_mtf else []
    regime_all = candle_repo.all(symbol, regime_timeframe) if config.strategy.scoring.use_nested_mtf else []
    local_close_times = [(candle.close_time if candle.close_time is not None else candle.open_time + _TIMEFRAME_MS[local_timeframe]) for candle in local_all]
    regime_close_times = [(candle.close_time if candle.close_time is not None else candle.open_time + _TIMEFRAME_MS[regime_timeframe]) for candle in regime_all]
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
        in_period = start_time is None or candle.open_time >= start_time
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
            entry_slice = candles[: index + 1]
            if config.strategy.scoring.use_nested_mtf:
                as_of = entry_slice[-1].close_time if entry_slice[-1].close_time is not None else entry_slice[-1].open_time + _TIMEFRAME_MS[entry_timeframe]
                window = max(config.market.warmup_candles, config.strategy.trend.ema_slow + config.strategy.pivots.right + config.strategy.triangle.max_candles)
                local_end = bisect_right(local_close_times, as_of)
                regime_end = bisect_right(regime_close_times, as_of)
                context = MarketContext(symbol, entry_timeframe, local_timeframe, regime_timeframe, entry_slice[-window:], local_all[max(0, local_end - window):local_end], regime_all[max(0, regime_end - window):regime_end])
                signal = evaluate(context.entry_candles, config, symbol, entry_timeframe, equity, context)
            else:
                signal = evaluate(entry_slice, config, symbol, timeframe, equity)
            if in_period:
                signals.append(signal)
                if signal_repo:
                    signal_repo.insert(signal)
            if in_period and signal.decision == Decision.ACCEPTED:
                if open_trade is not None:
                    funnel["skipped_already_in_position"] += 1
                elif pending_signal is not None:
                    funnel["skipped_pending_signal_exists"] += 1
                else:
                    pending_signal = signal
        if in_period:
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
            "use_nested_mtf": config.strategy.scoring.use_nested_mtf,
            "min_trade_score": config.strategy.scoring.min_trade_score,
            "config_name": config_name,
            "start_date": start_date,
            "end_date": end_date,
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
        nested_metadata={key: value for key, value in signal.metadata.items() if key in {"nested_context", "parent_timeframe_alignment", "parent_4h_triangle_type", "parent_1h_triangle_type", "child_triangle_type", "regime_trend_direction", "local_trend_direction", "mtf_zone_context", "would_be_blocked_by_strict_mtf_zone", "would_be_blocked_timeframes", "would_be_blocked_zone_kinds", "would_be_blocked_min_distance_to_entry_r", "would_be_blocked_min_distance_to_target_r"}},
        score_parent_4h_structure=_metadata_float(signal, "score_parent_4h_structure"),
        score_parent_1h_structure=_metadata_float(signal, "score_parent_1h_structure"),
        score_nested_triangle=_metadata_float(signal, "score_nested_triangle"),
        score_entry_breakout=_metadata_float(signal, "score_entry_breakout"),
        score_mtf_zones=_metadata_float(signal, "score_mtf_zones"),
        parent_4h_triangle_type=_metadata_str(signal, "parent_4h_triangle_type"),
        parent_1h_triangle_type=_metadata_str(signal, "parent_1h_triangle_type"),
        child_triangle_type=_metadata_str(signal, "child_triangle_type"),
        parent_timeframe_alignment=_metadata_str(signal, "parent_timeframe_alignment"),
        nested_context=_metadata_str(signal, "nested_context"),
        entry_trend_direction=_metadata_str(signal, "entry_trend_direction"),
        local_trend_direction=_metadata_str(signal, "local_trend_direction"),
        regime_trend_direction=_metadata_str(signal, "regime_trend_direction"),
        mtf_zone_context=_metadata_str(signal, "mtf_zone_context"),
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
        trade.nested_metadata,
        trade.score_parent_4h_structure,
        trade.score_parent_1h_structure,
        trade.score_nested_triangle,
        trade.score_entry_breakout,
        trade.score_mtf_zones,
        trade.parent_4h_triangle_type,
        trade.parent_1h_triangle_type,
        trade.child_triangle_type,
        trade.parent_timeframe_alignment,
        trade.nested_context,
        trade.entry_trend_direction,
        trade.local_trend_direction,
        trade.regime_trend_direction,
        trade.mtf_zone_context,
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
        trade.nested_metadata,
        trade.score_parent_4h_structure,
        trade.score_parent_1h_structure,
        trade.score_nested_triangle,
        trade.score_entry_breakout,
        trade.score_mtf_zones,
        trade.parent_4h_triangle_type,
        trade.parent_1h_triangle_type,
        trade.child_triangle_type,
        trade.parent_timeframe_alignment,
        trade.nested_context,
        trade.entry_trend_direction,
        trade.local_trend_direction,
        trade.regime_trend_direction,
        trade.mtf_zone_context,
    )


def _metadata_float(signal: Signal, key: str) -> float | None:
    value = signal.metadata.get(key)
    return float(value) if isinstance(value, int | float) else None


def _metadata_int(signal: Signal, key: str) -> int | None:
    value = signal.metadata.get(key)
    return int(value) if isinstance(value, int | float) else None


def _metadata_str(signal: Signal, key: str) -> str | None:
    value = signal.metadata.get(key)
    return value if isinstance(value, str) else None
