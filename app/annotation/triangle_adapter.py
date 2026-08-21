"""Deterministic research-only adapters for human triangle geometry."""

from app.annotation.models import LegacyTriangleGeometry, PricePoint, TrendLine, TriangleGeometry


def geometry_points(geometry: TriangleGeometry | LegacyTriangleGeometry) -> tuple[PricePoint, ...]:
    """Return canonical vertices, or all points from a legacy two-line record."""
    if isinstance(geometry, TriangleGeometry):
        return geometry.vertices
    return (
        geometry.upper_line.p1,
        geometry.upper_line.p2,
        geometry.lower_line.p1,
        geometry.lower_line.p2,
    )


def derive_trendlines(geometry: TriangleGeometry | LegacyTriangleGeometry) -> tuple[TrendLine, TrendLine]:
    """Adapt a human triangle to upper/lower lines for downstream feature extraction.

    The rightmost vertex is treated as the breakout apex. The remaining vertices
    become the upper and lower base anchors by price. Legacy annotations retain
    their originally stored lines unchanged.
    """
    if isinstance(geometry, LegacyTriangleGeometry):
        return geometry.upper_line, geometry.lower_line
    timestamp_counts = {point.timestamp: sum(candidate.timestamp == point.timestamp for candidate in geometry.vertices) for point in geometry.vertices}
    candidates = [(index, point) for index, point in enumerate(geometry.vertices) if timestamp_counts[point.timestamp] == 1]
    apex_index, apex = max(candidates, key=lambda item: (item[1].timestamp, item[0]))
    base = [point for index, point in enumerate(geometry.vertices) if index != apex_index]
    lower_base, upper_base = sorted(base, key=lambda point: (point.price, point.timestamp))
    return TrendLine(p1=upper_base, p2=apex), TrendLine(p1=lower_base, p2=apex)
