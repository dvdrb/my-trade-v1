from __future__ import annotations

from dataclasses import dataclass

from app.core.types import Pivot, Side, Triangle
from app.strategy.triangle import triangle_lower_at, triangle_upper_at


@dataclass(frozen=True)
class RiskPlan:
    entry_price: float
    stop_loss: float
    take_profit: float
    reward_risk: float
    position_size: float


def calculate_risk_plan(
    side: Side,
    entry_price: float,
    pivots: list[Pivot],
    triangle: Triangle,
    current_index: int,
    equity: float,
    risk_per_trade_percent: float,
    min_reward_risk: float,
    target_reward_risk: float | None = None,
) -> RiskPlan | None:
    take_profit_rr = target_reward_risk if target_reward_risk is not None else min_reward_risk
    if side == Side.LONG:
        lows = [pivot.price for pivot in pivots if pivot.kind == "low"]
        if not lows:
            return None
        stop_loss = min(lows[-1], triangle_lower_at(triangle, current_index))
        risk = entry_price - stop_loss
        take_profit = entry_price + risk * take_profit_rr
    else:
        highs = [pivot.price for pivot in pivots if pivot.kind == "high"]
        if not highs:
            return None
        stop_loss = max(highs[-1], triangle_upper_at(triangle, current_index))
        risk = stop_loss - entry_price
        take_profit = entry_price - risk * take_profit_rr
    if risk <= 0:
        return None
    risk_amount = equity * risk_per_trade_percent
    position_size = risk_amount / risk
    reward_risk = abs(take_profit - entry_price) / risk
    if reward_risk < min_reward_risk:
        return None
    return RiskPlan(entry_price, stop_loss, take_profit, reward_risk, position_size)
