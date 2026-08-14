from __future__ import annotations

from app.config.settings import AppConfig
from app.core.types import Candle, Side
from app.indicators.ema import ema
from app.strategy.candidates import TriangleCandidate
from app.strategy.risk import RiskPlan
from app.strategy.triangle import triangle_lower_at, triangle_upper_at
from app.strategy.zones import nearest_resistance, nearest_support


def structural_features(
    child: TriangleCandidate,
    parent_1h: TriangleCandidate | None,
    parent_4h: TriangleCandidate | None,
    entry: list[Candle],
    local: list[Candle],
    regime: list[Candle],
    side: Side,
    risk: RiskPlan,
    entry_zones: object,
    local_zones: object,
    regime_zones: object,
    config: AppConfig,
) -> dict[str, object]:
    """Return descriptive, point-in-time features; none participates in decisions."""
    breakout = entry[-1]
    child_samples = [candle for candle in entry if child.triangle.start_time <= candle.open_time <= breakout.open_time]
    child_height = max(child.triangle.upper_start - child.triangle.lower_start, 0.0)
    child_width = max(1, child.triangle.end_time - child.triangle.start_time)
    body = abs(breakout.close - breakout.open)
    candle_range = breakout.high - breakout.low
    recent_ranges = [candle.high - candle.low for candle in entry[-21:-1]]
    recent_average = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 0.0
    boundary = triangle_upper_at(child.triangle, len(entry) - 1) if side == Side.LONG else triangle_lower_at(child.triangle, len(entry) - 1)
    distance = (breakout.close - boundary) if side == Side.LONG else (boundary - breakout.close)
    risk_distance = max(abs(risk.entry_price - risk.stop_loss), 1e-12)
    features: dict[str, object] = {
        "triangle_type": child.triangle_type,
        "triangle_age": child.age,
        "triangle_duration": child_width,
        "triangle_height": child_height,
        "triangle_width": child_width,
        "triangle_cleanliness": child.cleanliness_score,
        "wick_violation_count": child.wick_violation_count,
        "close_violation_count": child.close_violation_count,
        "max_violation": max(child.max_wick_violation, child.max_close_violation),
        "touch_count_upper": child.high_touch_count,
        "touch_count_lower": child.low_touch_count,
        "upper_line_slope": _slope(child.triangle.upper_start, child.triangle.upper_end, child_width),
        "lower_line_slope": _slope(child.triangle.lower_start, child.triangle.lower_end, child_width),
        "convergence_rate": child.convergence_percent / max(child.age, 1),
        "distance_to_apex": _distance_to_apex(child, len(entry) - 1),
        "relative_position_at_breakout": _relative_position(child, breakout.close, len(entry) - 1),
        "breakout_body_percent": body / candle_range if candle_range else 0.0,
        "breakout_body_vs_recent_average": body / recent_average if recent_average else 0.0,
        "breakout_range_vs_recent_average": candle_range / recent_average if recent_average else 0.0,
        "breakout_close_position": ((breakout.close - breakout.low) / candle_range if side == Side.LONG else (breakout.high - breakout.close) / candle_range) if candle_range else 0.0,
        "breakout_distance_beyond_triangle_band": max(0.0, distance / max(abs(boundary), 1e-12)),
        "breakout_distance_in_recent_range": max(0.0, distance / recent_average) if recent_average else 0.0,
        "pre_breakout_compression": _compression(entry[-21:-1]),
        "candles_near_breakout_boundary": _near_boundary_count(entry[-12:-1], child, side),
        "child_direction_aligned_with_parent": _direction_aligned(parent_1h or parent_4h, side),
        "child_slope_aligned_with_parent": _slope_aligned(parent_1h or parent_4h, child),
        "parent_child_compression_ratio": _compression_ratio(parent_1h or parent_4h, child),
        "parent_child_age_ratio": (parent_1h or parent_4h).age / max(child.age, 1) if parent_1h or parent_4h else None,
        "distance_to_nearest_15m_opposite_zone_r": _opposite_zone_distance(entry_zones, side, risk),
        "distance_to_nearest_1h_opposite_zone_r": _opposite_zone_distance(local_zones, side, risk),
        "distance_to_nearest_4h_opposite_zone_r": _opposite_zone_distance(regime_zones, side, risk),
    }
    features.update(_parent_features("1h", parent_1h, local, child, child_samples, breakout.close))
    features.update(_parent_features("4h", parent_4h, regime, child, child_samples, breakout.close))
    for label, candles in (("15m", entry), ("1h", local), ("4h", regime)):
        features.update(_trend_features(label, candles, side, config))
    return features


def _parent_features(label: str, parent: TriangleCandidate | None, candles: list[Candle], child: TriangleCandidate, samples: list[Candle], price: float) -> dict[str, object]:
    prefix = f"parent_{label}_"
    if parent is None:
        return {f"{prefix}{key}": None for key in ("exists", "triangle_type", "age", "cleanliness", "convergence", "child_inside_percent", "child_price_range_overlap_percent", "child_position", "distance_to_upper_boundary", "distance_to_lower_boundary", "distance_to_apex", "maturity")}
    parent_end = _parent_end(parent, candles)
    inside, overlap, position, upper_distance, lower_distance = _parent_position(parent, child, samples, price, parent_end)
    return {
        f"{prefix}exists": True,
        f"{prefix}triangle_type": parent.triangle_type,
        f"{prefix}age": parent.age,
        f"{prefix}cleanliness": parent.cleanliness_score,
        f"{prefix}convergence": parent.convergence_percent,
        f"{prefix}child_inside_percent": inside,
        f"{prefix}child_price_range_overlap_percent": overlap,
        f"{prefix}child_position": position,
        f"{prefix}distance_to_upper_boundary": upper_distance,
        f"{prefix}distance_to_lower_boundary": lower_distance,
        f"{prefix}distance_to_apex": _time_to_apex(parent, parent_end),
        f"{prefix}maturity": min(1.0, max(0.0, (parent_end - parent.triangle.start_time) / max(parent.triangle.end_time - parent.triangle.start_time, 1))),
    }


def _parent_end(parent: TriangleCandidate, candles: list[Candle]) -> int:
    if not candles:
        return parent.triangle.end_time
    latest = candles[-1]
    duration = (latest.close_time - latest.open_time) if latest.close_time else (candles[-1].open_time - candles[-2].open_time if len(candles) > 1 else 0)
    return max(parent.triangle.end_time, latest.close_time or latest.open_time + duration)


def _parent_position(parent: TriangleCandidate, child: TriangleCandidate, samples: list[Candle], price: float, parent_end: int) -> tuple[float, float, float | None, float | None, float | None]:
    if not samples:
        return 0.0, 0.0, None, None, None
    inside = 0
    overlap = 0.0
    for candle in samples:
        upper, lower = _parent_bounds(parent, candle.open_time, parent_end)
        span = max(upper - lower, 1e-12)
        inside += int(candle.high <= upper and candle.low >= lower)
        overlap += max(0.0, min(candle.high, upper) - max(candle.low, lower)) / max(candle.high - candle.low, 1e-12)
    upper, lower = _parent_bounds(parent, child.triangle.end_time, parent_end)
    span = max(upper - lower, 1e-12)
    return inside / len(samples), overlap / len(samples), (price - lower) / span, (upper - price) / span, (price - lower) / span


def _parent_bounds(parent: TriangleCandidate, timestamp: int, parent_end: int) -> tuple[float, float]:
    ratio = (timestamp - parent.triangle.start_time) / max(parent_end - parent.triangle.start_time, 1)
    index = parent.triangle.start_index + ratio * (parent.triangle.end_index - parent.triangle.start_index)
    return triangle_upper_at(parent.triangle, index), triangle_lower_at(parent.triangle, index)


def _trend_features(label: str, candles: list[Candle], side: Side, config: AppConfig) -> dict[str, object]:
    values = [candle.close for candle in candles]
    fast = ema(values, config.strategy.trend.ema_fast)[-1] if values else None
    slow = ema(values, config.strategy.trend.ema_slow)[-1] if values else None
    close = values[-1] if values else 0.0
    direction = "neutral" if fast is None or slow is None or fast == slow else ("bullish" if fast > slow else "bearish")
    desired = "bullish" if side == Side.LONG else "bearish"
    return {f"{label}_trend": direction, f"{label}_trade_alignment": direction == desired, f"price_vs_{label}_ema50": close / fast - 1 if fast else None, f"price_vs_{label}_ema200": close / slow - 1 if slow else None, f"{label}_trend_strength": abs(fast - slow) / close if fast and slow and close else None}


def _slope(start: float, end: float, width: int) -> float:
    return (end - start) / width if width else 0.0


def _relative_position(candidate: TriangleCandidate, price: float, index: int) -> float:
    upper, lower = triangle_upper_at(candidate.triangle, index), triangle_lower_at(candidate.triangle, index)
    return (price - lower) / max(upper - lower, 1e-12)


def _distance_to_apex(candidate: TriangleCandidate, index: int) -> float | None:
    upper_slope = _slope(candidate.triangle.upper_start, candidate.triangle.upper_end, max(candidate.triangle.end_index - candidate.triangle.start_index, 1))
    lower_slope = _slope(candidate.triangle.lower_start, candidate.triangle.lower_end, max(candidate.triangle.end_index - candidate.triangle.start_index, 1))
    if lower_slope <= upper_slope:
        return None
    apex = candidate.triangle.start_index + (candidate.triangle.upper_start - candidate.triangle.lower_start) / (lower_slope - upper_slope)
    return apex - index


def _time_to_apex(candidate: TriangleCandidate, timestamp: int) -> float | None:
    distance = _distance_to_apex(candidate, candidate.triangle.end_index)
    if distance is None:
        return None
    duration = max(candidate.triangle.end_time - candidate.triangle.start_time, 1) / max(candidate.triangle.end_index - candidate.triangle.start_index, 1)
    return candidate.triangle.end_time + distance * duration - timestamp


def _compression(candles: list[Candle]) -> float:
    if len(candles) < 4:
        return 0.0
    first = sum(candle.high - candle.low for candle in candles[: len(candles) // 2]) / max(len(candles) // 2, 1)
    last = sum(candle.high - candle.low for candle in candles[len(candles) // 2 :]) / max(len(candles) - len(candles) // 2, 1)
    return 1 - last / first if first else 0.0


def _near_boundary_count(candles: list[Candle], child: TriangleCandidate, side: Side) -> int:
    count = 0
    for offset, candle in enumerate(candles, start=max(child.age - len(candles), 0)):
        boundary = triangle_upper_at(child.triangle, child.triangle.start_index + offset) if side == Side.LONG else triangle_lower_at(child.triangle, child.triangle.start_index + offset)
        if abs(candle.close - boundary) / max(abs(boundary), 1e-12) <= 0.003:
            count += 1
    return count


def _direction_aligned(parent: TriangleCandidate | None, side: Side) -> bool | None:
    if parent is None:
        return None
    return parent.triangle_type == "symmetrical" or (parent.triangle_type == "ascending") == (side == Side.LONG)


def _slope_aligned(parent: TriangleCandidate | None, child: TriangleCandidate) -> bool | None:
    if parent is None:
        return None
    return (parent.triangle.upper_end - parent.triangle.upper_start) * (child.triangle.upper_end - child.triangle.upper_start) >= 0


def _compression_ratio(parent: TriangleCandidate | None, child: TriangleCandidate) -> float | None:
    if parent is None:
        return None
    parent_height = max(parent.triangle.upper_start - parent.triangle.lower_start, 1e-12)
    return (child.triangle.upper_start - child.triangle.lower_start) / parent_height


def _opposite_zone_distance(zones: object, side: Side, risk: RiskPlan) -> float | None:
    zone = nearest_resistance(zones, risk.entry_price) if side == Side.LONG else nearest_support(zones, risk.entry_price)  # type: ignore[arg-type]
    if zone is None:
        return None
    distance = zone.low - risk.entry_price if side == Side.LONG else risk.entry_price - zone.high
    return distance / max(abs(risk.entry_price - risk.stop_loss), 1e-12)
