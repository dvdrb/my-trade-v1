from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.annotation.features import structure_features
from app.annotation.repository import AnnotationRepository
from app.data.db import connect, init_db


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--db", default="data/bot.sqlite3"); parser.add_argument("--output", default="data/human_ground_truth/features.jsonl")
    args = parser.parse_args(); init_db(args.db); annotations = AnnotationRepository(connect(args.db)).annotations()
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"annotation_id": annotation.annotation_id, **structure_features(structure)} for annotation in annotations for structure in annotation.structures]
    output.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"); print(output)


if __name__ == "__main__": main()
