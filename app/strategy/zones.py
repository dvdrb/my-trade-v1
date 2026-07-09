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
    risk = abs(entry - stop)
    if risk <= 0:
        return True
    if side == Side.LONG:
        resistance = nearest_resistance(zones, entry)
        return resistance is not None and (resistance.low - entry) / risk <= within_r
    support = nearest_support(zones, entry)
    return support is not None and (entry - support.high) / risk <= within_r
