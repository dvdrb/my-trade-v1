from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.annotation.repository import AnnotationRepository
from app.annotation.models import SCHEMA_VERSION
from app.data.db import connect, init_db


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export an immutable human-ground-truth batch.")
    parser.add_argument("--db", default="data/bot.sqlite3"); parser.add_argument("--output", default="data/human_ground_truth/batches")
    parser.add_argument("--batch", default=None); args = parser.parse_args()
    init_db(args.db); repository = AnnotationRepository(connect(args.db))
    annotations, trades = repository.annotations(), repository.trades()
    root = Path(args.output); root.mkdir(parents=True, exist_ok=True)
    batch_name = args.batch or f"batch_{len([p for p in root.iterdir() if p.is_dir()]) + 1:03d}"
    batch = root / batch_name
    if batch.exists(): raise SystemExit(f"refusing to overwrite frozen batch: {batch}")
    batch.mkdir(); (batch / "screenshots").mkdir()
    annotation_file, trade_file = batch / "annotations.jsonl", batch / "simulated_trades.jsonl"
    annotation_file.write_text("".join(a.model_dump_json() + "\n" for a in annotations), encoding="utf-8")
    trade_file.write_text("".join(t.model_dump_json() + "\n" for t in trades), encoding="utf-8")
    screenshot_files: list[Path] = []
    for annotation in annotations:
        for screenshot in repository.screenshots(annotation.annotation_id):
            source = Path(screenshot["image_path"])
            if source.is_file():
                destination = batch / "screenshots" / annotation.annotation_id / f"{screenshot['timeframe']}.png"
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                screenshot_files.append(destination)
    times = [a.decision_time for a in annotations]
    manifest = {"schema_version": SCHEMA_VERSION, "created_at": datetime.now(UTC).isoformat(),
                "annotation_count": len(annotations), "trade_count": len(trades),
                "symbols": sorted({a.symbol for a in annotations}), "market_range": [min(times), max(times)] if times else None}
    (batch / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    files = [annotation_file, trade_file, batch / "manifest.json", *screenshot_files]
    (batch / "SHA256SUMS").write_text("".join(f"{digest(path)}  {path.relative_to(batch)}\n" for path in files), encoding="utf-8")
    print(batch)


if __name__ == "__main__": main()
