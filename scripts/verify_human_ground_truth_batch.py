from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.annotation.models import HumanAnnotation, SCHEMA_VERSION, SimulatedTrade


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(batch: Path) -> list[str]:
    errors: list[str] = []
    manifest_path, annotations_path, trades_path, sums_path = (batch / "manifest.json", batch / "annotations.jsonl", batch / "simulated_trades.jsonl", batch / "SHA256SUMS")
    if not all(path.is_file() for path in (manifest_path, annotations_path, trades_path, sums_path)):
        return ["batch is missing a required artifact"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
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
    for annotation in annotations:
        if annotation.decision_time < 0:
            errors.append("annotation has an invalid decision timestamp")
        screenshots = list((batch / "screenshots" / annotation.annotation_id).rglob("*.png"))
        if not screenshots:
            errors.append(f"annotation {annotation.annotation_id} is missing screenshots")
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
