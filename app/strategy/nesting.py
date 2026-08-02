from __future__ import annotations

from app.core.types import Candle, Side
from app.strategy.candidates import TriangleCandidate
from app.strategy.triangle import triangle_lower_at, triangle_upper_at


def is_child_inside_parent(parent: TriangleCandidate, child: TriangleCandidate, parent_candles: list[Candle], child_candles: list[Candle], tolerance_percent: float = 0.003) -> bool:
    """Allow modest band overrun while requiring the child's structure to be within the parent."""
    if not parent_candles or not child_candles:
        return False
    parent_start = parent.triangle.start_time
    # The latest parent candle is usable through its close, not merely its open.
    # Using its open time rejected every entry child formed within an already
    # closed 4h candle and made the 4h context practically unreachable.
    latest_parent = parent_candles[-1]
    inferred_duration = parent_candles[-1].open_time - parent_candles[-2].open_time if len(parent_candles) > 1 else 0
    latest_parent_close = latest_parent.close_time if latest_parent.close_time is not None else latest_parent.open_time + inferred_duration
    parent_end = max(parent.triangle.end_time, latest_parent_close)
    if child.triangle.start_time < parent_start or child.triangle.end_time > parent_end:
        return False
    samples = [candle for candle in child_candles if child.triangle.start_time <= candle.open_time <= child.triangle.end_time]
    if not samples:
        return False
    parent_span = max(1, parent_end - parent_start)
    inside = 0
    for candle in samples:
        ratio = (candle.open_time - parent_start) / parent_span
        parent_index = parent.triangle.start_index + ratio * (parent.triangle.end_index - parent.triangle.start_index)
        upper = triangle_upper_at(parent.triangle, parent_index) * (1 + tolerance_percent)
        lower = triangle_lower_at(parent.triangle, parent_index) * (1 - tolerance_percent)
        if candle.high <= upper and candle.low >= lower:
            inside += 1
    return inside / len(samples) >= 0.75


def score_nested_relationship(parent: TriangleCandidate | None, child: TriangleCandidate, parent_candles: list[Candle], child_candles: list[Candle], side: Side | None = None, tolerance_percent: float = 0.003) -> tuple[float, str]:
    if parent is None:
        return 0.0, "no parent triangle"
    if not is_child_inside_parent(parent, child, parent_candles, child_candles, tolerance_percent):
        return 0.0, "child outside parent triangle"
    direction = "aligned" if side is None or parent.triangle.kind == "symmetrical" or (parent.triangle.kind == "ascending" and side == Side.LONG) or (parent.triangle.kind == "descending" and side == Side.SHORT) else "acceptable"
    return (20.0 if direction == "aligned" else 14.0), f"nested child {direction} with parent"


def find_nested_triangle_setups(parents: list[TriangleCandidate], children: list[TriangleCandidate], parent_candles: list[Candle], child_candles: list[Candle], tolerance_percent: float = 0.003) -> list[tuple[TriangleCandidate, TriangleCandidate]]:
    return [(parent, child) for child in children for parent in parents if is_child_inside_parent(parent, child, parent_candles, child_candles, tolerance_percent)]
