from __future__ import annotations

from dataclasses import dataclass

from app.core.types import Candle, Pivot, Triangle
from app.strategy.triangle import triangle_lower_band_at, triangle_upper_band_at


@dataclass(frozen=True)
class TriangleCandidate:
    triangle: Triangle
    triangle_type: str
    start_index: int
    end_index: int
    age: int
    high_touch_count: int
    low_touch_count: int
    convergence_percent: float
    cleanliness_score: float
    wick_violation_count: int = 0
    close_violation_count: int = 0
    max_wick_violation: float = 0.0
    max_close_violation: float = 0.0
    line_tolerance_used: float = 0.0


def find_triangle_candidates(
    pivots: list[Pivot],
    current_index: int,
    min_candles: int,
    max_candles: int,
    flat_tolerance_percent: float,
    max_candidates: int = 20,
    candles: list[Candle] | None = None,
    line_tolerance_percent: float = 0.0,
    max_wick_violation_percent: float = 1.0,
    max_close_violation_percent: float = 1.0,
    max_allowed_close_violations: int = 1_000_000,
    max_allowed_wick_violations: int = 1_000_000,
) -> list[TriangleCandidate]:
    highs = [pivot for pivot in pivots if pivot.kind == "high"][-8:]
    lows = [pivot for pivot in pivots if pivot.kind == "low"][-8:]
    candidates: list[TriangleCandidate] = []
    seen: set[tuple[str, int, int]] = set()

    for high_start_pos in range(max(0, len(highs) - 5), max(0, len(highs) - 1)):
        for low_start_pos in range(max(0, len(lows) - 5), max(0, len(lows) - 1)):
            high_pair = (highs[high_start_pos], highs[-1])
            low_pair = (lows[low_start_pos], lows[-1])
            candidate = _build_candidate(
                high_pair,
                low_pair,
                current_index,
                min_candles,
                max_candles,
                flat_tolerance_percent,
                candles,
                line_tolerance_percent,
                max_wick_violation_percent,
                max_close_violation_percent,
                max_allowed_close_violations,
                max_allowed_wick_violations,
            )
            if candidate is None:
                continue
            key = (candidate.triangle_type, candidate.start_index, candidate.end_index)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

    return sorted(candidates, key=lambda item: (item.end_index, item.cleanliness_score), reverse=True)[:max_candidates]


def _build_candidate(
    high_pair: tuple[Pivot, Pivot],
    low_pair: tuple[Pivot, Pivot],
    current_index: int,
    min_candles: int,
    max_candles: int,
    flat_tolerance_percent: float,
    candles: list[Candle] | None = None,
    line_tolerance_percent: float = 0.0,
    max_wick_violation_percent: float = 1.0,
    max_close_violation_percent: float = 1.0,
    max_allowed_close_violations: int = 1_000_000,
    max_allowed_wick_violations: int = 1_000_000,
) -> TriangleCandidate | None:
    high_start, high_end = high_pair
    low_start, low_end = low_pair
    start_index = min(high_start.index, low_start.index)
    end_index = max(high_end.index, low_end.index)
    age = current_index - start_index
    if age < min_candles or age > max_candles or end_index <= start_index:
        return None

    upper_start, upper_end = high_start.price, high_end.price
    lower_start, lower_end = low_start.price, low_end.price
    highs_flat = abs(upper_end - upper_start) / upper_start <= flat_tolerance_percent
    lows_flat = abs(lower_end - lower_start) / lower_start <= flat_tolerance_percent
    highs_falling = upper_end < upper_start
    lows_rising = lower_end > lower_start

    triangle_type: str | None = None
    if highs_flat and lows_rising:
        triangle_type = "ascending"
        upper_end = upper_start
    elif lows_flat and highs_falling:
        triangle_type = "descending"
        lower_end = lower_start
    elif highs_falling and lows_rising:
        triangle_type = "symmetrical"
    if triangle_type is None:
        return None

    start_width = upper_start - lower_start
    end_width = upper_end - lower_end
    if start_width <= 0 or end_width <= 0:
        return None
    convergence_percent = max(0.0, min(1.0, (start_width - end_width) / start_width))
    triangle = Triangle(
        kind=triangle_type,
        start_index=start_index,
        end_index=end_index,
        start_time=min(high_start.open_time, low_start.open_time),
        end_time=max(high_end.open_time, low_end.open_time),
        upper_start=upper_start,
        upper_end=upper_end,
        lower_start=lower_start,
        lower_end=lower_end,
    )
    wick_count = 0
    close_count = 0
    max_wick = 0.0
    max_close = 0.0
    if candles is not None:
        wick_count, close_count, max_wick, max_close = _measure_violations(triangle, candles, start_index, min(end_index, current_index - 1), line_tolerance_percent)
        if (
            close_count > max_allowed_close_violations
            or wick_count > max_allowed_wick_violations
            or max_close > max_close_violation_percent
            or max_wick > max_wick_violation_percent
        ):
            return None

    cleanliness_score = _cleanliness_score(wick_count, close_count, max_wick, max_close)
    return TriangleCandidate(
        triangle=triangle,
        triangle_type=triangle_type,
        start_index=start_index,
        end_index=end_index,
        age=age,
        high_touch_count=2,
        low_touch_count=2,
        convergence_percent=convergence_percent,
        cleanliness_score=cleanliness_score,
        wick_violation_count=wick_count,
        close_violation_count=close_count,
        max_wick_violation=max_wick,
        max_close_violation=max_close,
        line_tolerance_used=line_tolerance_percent,
    )


def _measure_violations(triangle: Triangle, candles: list[Candle], start_index: int, end_index: int, line_tolerance_percent: float) -> tuple[int, int, float, float]:
    wick_count = 0
    close_count = 0
    max_wick = 0.0
    max_close = 0.0
    for index in range(max(0, start_index), min(end_index + 1, len(candles))):
        candle = candles[index]
        upper = triangle_upper_band_at(triangle, index, line_tolerance_percent)
        lower = triangle_lower_band_at(triangle, index, line_tolerance_percent)
        wick_violation = max(
            0.0,
            (candle.high - upper.upper) / upper.center,
            (lower.lower - candle.low) / lower.center,
        )
        close_violation = max(
            0.0,
            (candle.close - upper.upper) / upper.center,
            (lower.lower - candle.close) / lower.center,
        )
        if wick_violation > 0:
            wick_count += 1
            max_wick = max(max_wick, wick_violation)
        if close_violation > 0:
            close_count += 1
            max_close = max(max_close, close_violation)
    return wick_count, close_count, max_wick, max_close


def _cleanliness_score(wick_count: int, close_count: int, max_wick: float, max_close: float) -> float:
    score = 20.0
    score -= min(6.0, wick_count * 1.0)
    score -= min(10.0, close_count * 3.0)
    score -= min(4.0, max_wick * 500)
    score -= min(6.0, max_close * 1000)
    return max(0.0, min(20.0, score))
