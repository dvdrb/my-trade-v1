from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.annotation.models import HumanAnnotation, SUPPORTED_SCHEMA_VERSIONS, SimulatedTrade


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(batch: Path) -> list[str]:
    errors: list[str] = []
    manifest_path, annotations_path, trades_path, sums_path = (batch / "manifest.json", batch / "annotations.jsonl", batch / "simulated_trades.jsonl", batch / "SHA256SUMS")
    if not all(path.is_file() for path in (manifest_path, annotations_path, trades_path, sums_path)):
        return ["batch is missing a required artifact"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append("unsupported schema version")
    annotations = [HumanAnnotation.model_validate_json(line) for line in annotations_path.read_text(encoding="utf-8").splitlines() if line]
    trades = [SimulatedTrade.model_validate_json(line) for line in trades_path.read_text(encoding="utf-8").splitlines() if line]
    ids = [annotation.annotation_id for annotation in annotations]
    if len(ids) != len(set(ids)):
        errors.append("annotation IDs are not unique")
    known = set(ids)
    if any(trade.annotation_id not in known for trade in trades):
        errors.append("a simulated trade references an unknown annotation")
    if manifest.get("annotation_count") != len(annotations) or manifest.get("trade_count") != len(trades):
        errors.append("manifest counts do not match exported records")
    required_timeframes = {"4h", "1h", "15m"}
    canonical_revisions = manifest.get("canonical_annotation_revisions", {})
    for annotation in annotations:
        if annotation.decision_time < 0:
            errors.append("annotation has an invalid decision timestamp")
        trendline_ids = [trendline.trendline_id for trendline in annotation.trendlines]
        if len(trendline_ids) != len(set(trendline_ids)):
            errors.append(f"annotation {annotation.annotation_id} has duplicate trendline IDs")
        strong_point_ids = [point.strong_point_id for point in annotation.strong_points]
        if len(strong_point_ids) != len(set(strong_point_ids)):
            errors.append(f"annotation {annotation.annotation_id} has duplicate strong-point IDs")
        for trendline in annotation.trendlines:
            if trendline.p1 == trendline.p2:
                errors.append(f"trendline {trendline.trendline_id} has identical endpoints")
            if trendline.p1.timestamp < 0 or trendline.p2.timestamp < 0 or trendline.p1.price <= 0 or trendline.p2.price <= 0:
                errors.append(f"trendline {trendline.trendline_id} has invalid coordinates")
        for strong_point in annotation.strong_points:
            if strong_point.point.timestamp < 0 or strong_point.point.price <= 0:
                errors.append(f"strong point {strong_point.strong_point_id} has invalid coordinates")
            if strong_point.point.timestamp > annotation.decision_time:
                errors.append(f"strong point {strong_point.strong_point_id} is a future market observation")
        revision = int(canonical_revisions.get(annotation.annotation_id, 1))
        screenshot_directory = batch / "screenshots" / annotation.annotation_id / f"revision_{revision:03d}"
        actual_timeframes = {path.stem for path in screenshot_directory.glob("*.png")}
        if actual_timeframes != required_timeframes:
            errors.append(
                f"annotation {annotation.annotation_id} canonical screenshots must be exactly "
                f"{sorted(required_timeframes)}, found {sorted(actual_timeframes)}"
            )
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = batch / relative
        if not path.is_file() or digest(path) != expected:
            errors.append(f"checksum mismatch: {relative}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a frozen human-ground-truth export batch.")
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    errors = verify(args.batch)
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"verified {args.batch}")


if __name__ == "__main__":
    main()
