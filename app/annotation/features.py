from __future__ import annotations

from app.annotation.models import Structure


def structure_features(structure: Structure) -> dict[str, float | str]:
    upper, lower = structure.geometry.upper_line, structure.geometry.lower_line
    start = min(upper.p1.timestamp, upper.p2.timestamp, lower.p1.timestamp, lower.p2.timestamp)
    end = max(upper.p1.timestamp, upper.p2.timestamp, lower.p1.timestamp, lower.p2.timestamp)
    duration = end - start
    upper_slope = (upper.p2.price - upper.p1.price) / (upper.p2.timestamp - upper.p1.timestamp)
    lower_slope = (lower.p2.price - lower.p1.price) / (lower.p2.timestamp - lower.p1.timestamp)
    start_height = abs(upper.p1.price - lower.p1.price)
    end_height = abs(upper.p2.price - lower.p2.price)
    return {"structure_id": structure.structure_id, "timeframe": structure.timeframe, "role": structure.role.value,
            "duration_ms": duration, "height_start": start_height, "height_end": end_height,
            "upper_slope": upper_slope, "lower_slope": lower_slope,
            "convergence": start_height - end_height, "compression_ratio": end_height / start_height if start_height else 0.0}
