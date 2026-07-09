from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from app.core.types import Signal, Trade


def write_report(run_id: str, summary: dict[str, Any], trades: list[Trade], signals: list[Signal], equity_curve: list[tuple[int, float]]) -> Path:
    directory = Path("reports/backtests") / run_id
    directory.mkdir(parents=True, exist_ok=True)

    with (directory / "summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, allow_nan=False)

    with (directory / "trades.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(Trade.__dataclass_fields__.keys()))
        writer.writeheader()
        for trade in trades:
            row = trade.__dict__.copy()
            row["side"] = trade.side.value
            writer.writerow(row)

    with (directory / "signals.csv").open("w", newline="", encoding="utf-8") as file:
        fieldnames = list(Signal.__dataclass_fields__.keys())
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for signal in signals:
            row = signal.__dict__.copy()
            row["decision"] = signal.decision.value
            row["side"] = signal.side.value if signal.side else None
            row["reasons"] = ";".join(signal.reasons)
            writer.writerow(row)

    with (directory / "equity_curve.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["time", "equity"])
        writer.writeheader()
        for time, equity in equity_curve:
            writer.writerow({"time": time, "equity": equity})

    return directory
