from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.core.types import Signal, Trade


def calculate_metrics(trades: list[Trade], signals: list[Signal], equity_curve: list[float] | None = None) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.status == "closed"]
    wins = [trade for trade in closed if trade.pnl > 0]
    losses = [trade for trade in closed if trade.pnl < 0]
    gross_profit = sum(trade.pnl for trade in wins)
    gross_loss = abs(sum(trade.pnl for trade in losses))
    r_values = [trade.r_multiple for trade in closed]

    rejection_counts: Counter[str] = Counter()
    for signal in signals:
        if signal.decision.value == "rejected":
            rejection_counts.update(signal.reasons)

    return {
        "total_trades": len(closed),
        "accepted_signals": sum(1 for signal in signals if signal.decision.value == "accepted"),
        "rejected_signals": sum(1 for signal in signals if signal.decision.value == "rejected"),
        "rejection_counts_by_reason": dict(rejection_counts),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "average_r": sum(r_values) / len(r_values) if r_values else 0.0,
        "expectancy": sum(trade.pnl for trade in closed) / len(closed) if closed else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else 0.0),
        "max_drawdown": _max_drawdown(equity_curve or []),
        "max_losing_streak": _max_losing_streak(closed),
        "performance_by_side": _group_performance(closed, lambda trade: trade.side.value),
        "performance_by_triangle_type": {},
    }


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
            "pnl": sum(item.pnl for item in items),
            "average_r": sum(item.r_multiple for item in items) / len(items),
        }
        for key, items in grouped.items()
    }
