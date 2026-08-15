from __future__ import annotations

from app.core.types import Candle


TIMEFRAME_MS = {"15m": 15 * 60_000, "1h": 60 * 60_000, "4h": 4 * 60 * 60_000}


def visible_candles(candles: list[Candle], replay_time: int) -> list[Candle]:
    """Return only fully knowable candles at the replay point.

    Aggregated 1h/4h OHLC values are future information until their close.  Sources
    without a close_time are treated as already-finalized legacy rows.
    """
    return [candle for candle in candles if candle.open_time <= replay_time and (candle.close_time is None or candle.close_time <= replay_time)]


def advance_time(candles: list[Candle], replay_time: int, count: int = 1) -> int:
    known = [candle.close_time if candle.close_time is not None else candle.open_time for candle in candles if (candle.close_time if candle.close_time is not None else candle.open_time) > replay_time]
    return known[min(count - 1, len(known) - 1)] if known else replay_time


def step_trade(trade: dict[str, object], candle: Candle) -> dict[str, object]:
    """Apply a single candle conservatively: if SL and TP both touch, SL wins."""
    if trade["status"] == "pending":
        entry = float(trade["entry_price"])
        if candle.low <= entry <= candle.high:
            trade.update(status="open", entry_time=candle.open_time)
    if trade["status"] != "open":
        return trade
    side, stop, target = str(trade["side"]), float(trade["stop_loss"]), float(trade["take_profit"])
    stopped = candle.low <= stop if side == "long" else candle.high >= stop
    targeted = candle.high >= target if side == "long" else candle.low <= target
    if stopped or targeted:
        # Conservative ambiguous-candle handling must never credit a target before a stop.
        exit_price, status = (stop, "stopped") if stopped else (target, "target")
        risk = abs(float(trade["entry_price"]) - stop)
        r = (exit_price - float(trade["entry_price"])) / risk
        if side == "short": r *= -1
        trade.update(status=status, exit_time=candle.open_time, exit_price=exit_price, realized_r=r)
    return trade
