from __future__ import annotations

from app.core.types import Pivot, Triangle


def line_price_at(start_index: int, start_price: float, end_index: int, end_price: float, index: int) -> float:
    if end_index == start_index:
        return end_price
    slope = (end_price - start_price) / (end_index - start_index)
    return start_price + slope * (index - start_index)


def detect_triangle(
    pivots: list[Pivot],
    current_index: int,
    min_candles: int,
    max_candles: int,
    flat_tolerance_percent: float,
) -> Triangle | None:
    highs = [pivot for pivot in pivots if pivot.kind == "high"][-3:]
    lows = [pivot for pivot in pivots if pivot.kind == "low"][-3:]
    if len(highs) < 2 or len(lows) < 2:
        return None

    start_index = min(highs[0].index, lows[0].index)
    end_index = max(highs[-1].index, lows[-1].index)
    age = current_index - start_index
    if age < min_candles or age > max_candles:
        return None

    upper_start, upper_end = highs[0].price, highs[-1].price
    lower_start, lower_end = lows[0].price, lows[-1].price
    highs_flat = abs(upper_end - upper_start) / upper_start <= flat_tolerance_percent
    lows_flat = abs(lower_end - lower_start) / lower_start <= flat_tolerance_percent
    highs_falling = upper_end < upper_start
    lows_rising = lower_end > lower_start

    kind: str | None = None
    if highs_flat and lows_rising:
        kind = "ascending"
        upper_end = upper_start
    elif lows_flat and highs_falling:
        kind = "descending"
        lower_end = lower_start
    elif highs_falling and lows_rising:
        kind = "symmetrical"
    if kind is None:
        return None

    return Triangle(
        kind=kind,
        start_index=start_index,
        end_index=end_index,
        start_time=min(highs[0].open_time, lows[0].open_time),
        end_time=max(highs[-1].open_time, lows[-1].open_time),
        upper_start=upper_start,
        upper_end=upper_end,
        lower_start=lower_start,
        lower_end=lower_end,
    )


def triangle_upper_at(triangle: Triangle, index: int) -> float:
    return line_price_at(triangle.start_index, triangle.upper_start, triangle.end_index, triangle.upper_end, index)


def triangle_lower_at(triangle: Triangle, index: int) -> float:
    return line_price_at(triangle.start_index, triangle.lower_start, triangle.end_index, triangle.lower_end, index)
