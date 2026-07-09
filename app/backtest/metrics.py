from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.core.types import Signal, Trade


def calculate_metrics(
    trades: list[Trade],
    signals: list[Signal],
    equity_curve: list[float] | None = None,
    open_trades: list[Trade] | None = None,
    funnel: dict[str, int] | None = None,
    run_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.status == "closed"]
    wins = [trade for trade in closed if trade.pnl > 0]
    losses = [trade for trade in closed if trade.pnl < 0]
    gross_profit = sum(trade.pnl for trade in wins)
    gross_loss = abs(sum(trade.pnl for trade in losses))
    r_values = [trade.r_multiple for trade in closed]
    total_pnl = sum(trade.pnl for trade in closed)
    average_r = sum(r_values) / len(r_values) if r_values else 0.0
    average_pnl = total_pnl / len(closed) if closed else 0.0

    rejection_counts: Counter[str] = Counter()
    for signal in signals:
        if signal.decision.value == "rejected":
            rejection_counts.update(signal.reasons)

    funnel_metrics = {
        "accepted_signals": sum(1 for signal in signals if signal.decision.value == "accepted"),
        "trades_opened": len(trades) + len(open_trades or []),
        "closed_trades": len(closed),
        "open_trades_at_end": len(open_trades or []),
        "skipped_already_in_position": 0,
        "skipped_pending_signal_exists": 0,
        "skipped_end_of_backtest": 0,
        "skipped_actual_entry_invalid_rr": 0,
    }
    if funnel:
        funnel_metrics.update(funnel)
        funnel_metrics["accepted_signals"] = sum(1 for signal in signals if signal.decision.value == "accepted")

    summary = {
        **(run_metadata or {}),
        "total_trades": len(closed),
        **funnel_metrics,
        "rejected_signals": sum(1 for signal in signals if signal.decision.value == "rejected"),
        "rejection_counts_by_reason": dict(rejection_counts),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "average_r": average_r,
        "expectancy_r": average_r,
        "average_pnl": average_pnl,
        "expectancy_usd": average_pnl,
        "total_pnl": total_pnl,
        "profit_factor": gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else 0.0),
        "max_drawdown": _max_drawdown(equity_curve or []),
        "max_losing_streak": _max_losing_streak(closed),
        "performance_by_side": _group_performance(closed, lambda trade: trade.side.value),
        "performance_by_triangle_type": _triangle_performance(closed),
        "score_bucket_performance": _score_bucket_performance(closed),
        "performance_by_score_bucket": _score_bucket_performance(closed),
        "performance_by_trend_score_bucket": _quality_bucket_performance(closed, "score_trend_quality"),
        "performance_by_zone_score_bucket": _quality_bucket_performance(closed, "score_zone_quality"),
        "performance_by_risk_score_bucket": _quality_bucket_performance(closed, "score_risk_quality"),
        "performance_by_triangle_cleanliness_bucket": _quality_bucket_performance(closed, "triangle_cleanliness_score"),
        "candidate_funnel": _candidate_funnel(signals),
    }
    summary["score_bucket_trade_count"] = sum(bucket["trades"] for bucket in summary["score_bucket_performance"].values())
    return summary


def _max_drawdown(equity: list[float]) -> float:
    peak = None
    max_dd = 0.0
    for value in equity:
        peak = value if peak is None else max(peak, value)
        if peak:
            max_dd = max(max_dd, (peak - value) / peak)
    return max_dd


def _max_losing_streak(trades: list[Trade]) -> int:
    streak = 0
    max_streak = 0
    for trade in trades:
        if trade.pnl < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def _group_performance(trades: list[Trade], key_func) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        grouped[key_func(trade)].append(trade)
    return {
        key: {
            "trades": len(items),
            "win_rate": sum(1 for item in items if item.pnl > 0) / len(items),
            "average_r": sum(item.r_multiple for item in items) / len(items),
            "total_pnl": sum(item.pnl for item in items),
            "profit_factor": _profit_factor(items),
        }
        for key, items in grouped.items()
    }


def _triangle_performance(trades: list[Trade]) -> dict[str, dict[str, float]]:
    result = {
        kind: {"trades": 0, "win_rate": 0.0, "average_r": 0.0, "total_pnl": 0.0, "profit_factor": 0.0}
        for kind in ("ascending", "descending", "symmetrical")
    }
    result.update(_group_performance([trade for trade in trades if trade.triangle_type], lambda trade: trade.triangle_type or "unknown"))
    return result


def _profit_factor(trades: list[Trade]) -> float:
    wins = [trade for trade in trades if trade.pnl > 0]
    losses = [trade for trade in trades if trade.pnl < 0]
    gross_profit = sum(trade.pnl for trade in wins)
    gross_loss = abs(sum(trade.pnl for trade in losses))
    return gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else 0.0)


def _score_bucket_performance(trades: list[Trade]) -> dict[str, dict[str, float]]:
    return _bucket_performance(
        trades,
        lambda trade: trade.score_total,
        [(80, 100, "80_100"), (70, 79.9999, "70_79"), (60, 69.9999, "60_69"), (50, 59.9999, "50_59"), (40, 49.9999, "40_49"), (0, 39.9999, "0_39")],
    )


def _quality_bucket_performance(trades: list[Trade], field_name: str) -> dict[str, dict[str, float]]:
    return _bucket_performance(trades, lambda trade: getattr(trade, field_name), [(15, 20, "15_20"), (10, 14.9999, "10_14"), (5, 9.9999, "5_9"), (0, 4.9999, "0_4")])


def _bucket_performance(trades: list[Trade], value_func, buckets: list[tuple[float, float, str]]) -> dict[str, dict[str, float]]:
    result = {label: {"trades": 0, "win_rate": 0.0, "average_r": 0.0, "total_pnl": 0.0, "profit_factor": 0.0} for _, _, label in buckets}
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        value = value_func(trade)
        if value is None:
            continue
        for low, high, label in buckets:
            if low <= value <= high:
                grouped[label].append(trade)
                break
    for label, items in grouped.items():
        result[label] = {
            "trades": len(items),
            "win_rate": sum(1 for item in items if item.pnl > 0) / len(items),
            "average_r": sum(item.r_multiple for item in items) / len(items),
            "total_pnl": sum(item.pnl for item in items),
            "profit_factor": _profit_factor(items),
        }
    return result


def _candidate_funnel(signals: list[Signal]) -> dict[str, int]:
    return {
        "candles_processed": len(signals),
        "triangle_candidates_found": sum(int(signal.metadata.get("triangle_candidates_found", 0)) for signal in signals),
        "breakout_candidates_found": sum(int(signal.metadata.get("breakout_candidates_found", 0)) for signal in signals),
        "scored_candidates": sum(int(signal.metadata.get("scored_candidates", 0)) for signal in signals),
        "accepted_signals": sum(1 for signal in signals if signal.decision.value == "accepted"),
        "rejected_by_absolute_risk": sum(int(signal.metadata.get("rejected_by_absolute_risk", 0)) for signal in signals),
        "rejected_by_score": sum(int(signal.metadata.get("rejected_by_score", 0)) for signal in signals),
    }
