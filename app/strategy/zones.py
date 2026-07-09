from __future__ import annotations

from app.core.types import Pivot, Side, StrongZone


def build_zones(pivots: list[Pivot], tolerance_percent: float, min_touches: int) -> list[StrongZone]:
    zones: list[StrongZone] = []
    for kind, zone_type in (("low", "support"), ("high", "resistance")):
        prices = sorted(pivot.price for pivot in pivots if pivot.kind == kind)
        groups: list[list[float]] = []
        for price in prices:
            for group in groups:
                center = sum(group) / len(group)
                if abs(price - center) / center <= tolerance_percent:
                    group.append(price)
                    break
            else:
                groups.append([price])
        for group in groups:
            if len(group) >= min_touches:
                low = min(group)
                high = max(group)
                zones.append(StrongZone(zone_type, low, high, len(group), float(len(group))))
    return zones


def nearest_support(zones: list[StrongZone], price: float) -> StrongZone | None:
    supports = [zone for zone in zones if zone.kind == "support" and zone.high <= price]
    return max(supports, key=lambda zone: zone.high, default=None)


def nearest_resistance(zones: list[StrongZone], price: float) -> StrongZone | None:
    resistances = [zone for zone in zones if zone.kind == "resistance" and zone.low >= price]
    return min(resistances, key=lambda zone: zone.low, default=None)


def blocked_by_opposite_zone(zones: list[StrongZone], side: Side, entry: float, stop: float, within_r: float) -> bool:
    return blocking_opposite_zone(zones, side, entry, stop, within_r) is not None


def blocking_opposite_zone(zones: list[StrongZone], side: Side, entry: float, stop: float, within_r: float) -> dict[str, float | int | str] | None:
    risk = abs(entry - stop)
    if risk <= 0:
        return {
            "zone_kind": "unknown",
            "zone_low": entry,
            "zone_high": entry,
            "distance_to_zone": 0.0,
            "distance_to_zone_r": 0.0,
            "zone_touches": 0,
            "zone_strength": 0.0,
        }
    if side == Side.LONG:
        resistance = nearest_resistance(zones, entry)
        if resistance is None:
            return None
        distance = resistance.low - entry
        zone = resistance
    else:
        support = nearest_support(zones, entry)
        if support is None:
            return None
        distance = entry - support.high
        zone = support
    distance_r = distance / risk
    if distance_r > within_r:
        return None
    return {
        "zone_kind": zone.kind,
        "zone_low": zone.low,
        "zone_high": zone.high,
        "distance_to_zone": distance,
        "distance_to_zone_r": distance_r,
        "zone_touches": zone.touches,
        "zone_strength": zone.strength,
    }
