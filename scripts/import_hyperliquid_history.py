from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from app.core.types import Candle
from app.data.db import DEFAULT_DB_PATH, connect, init_db
from app.data.historical import CANONICAL_TIMEFRAME, derive_timeframe, validate_candles, verify_api_overlap
from app.data.repositories import CandleRepository
from app.exchange.hyperliquid_data import fetch_candles


RESEARCH_SYMBOLS = {"BTC", "ETH", "SOL"}
MINIMUM_CANDLES = {"15m": 20_000, "1h": 5_000, "4h": 2_000}


def load_canonical_csv(path: Path) -> list[Candle]:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        required = {"symbol", "open_time", "open", "high", "low", "close", "volume"}
        if reader.fieldnames is None or not required <= set(reader.fieldnames):
            raise ValueError(f"canonical CSV must include: {', '.join(sorted(required))}")
        candles = [
            Candle(
                symbol=row["symbol"].upper(),
                timeframe=CANONICAL_TIMEFRAME,
                open_time=int(row["open_time"]),
                close_time=int(row["close_time"]) if row.get("close_time") else None,
                open=float(row["open"]), high=float(row["high"]), low=float(row["low"]), close=float(row["close"]),
                volume=float(row["volume"]),
            )
            for row in reader
        ]
    if {candle.symbol for candle in candles} != RESEARCH_SYMBOLS:
        raise ValueError("canonical CSV must contain exactly BTC, ETH, and SOL")
    return candles


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_complete_common_history(candles: list[Candle], timeframe: str) -> list[dict[str, object]]:
    integrity = validate_candles(candles, timeframe)
    if any(item.candles < MINIMUM_CANDLES[timeframe] or item.gaps or item.duplicate_open_times for item in integrity):
        raise SystemExit(f"{timeframe} data does not meet research coverage requirements: {integrity}")
    by_symbol = {symbol: [candle.open_time for candle in candles if candle.symbol == symbol] for symbol in RESEARCH_SYMBOLS}
    reference = by_symbol["BTC"]
    if any(open_times != reference for symbol, open_times in by_symbol.items() if symbol != "BTC"):
        raise SystemExit(f"{timeframe} source does not have an identical common BTC/ETH/SOL time grid")
    return [item.__dict__ for item in integrity]


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a checksum-verified Hyperliquid 15m dataset and derive 1h/4h candles.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--sha256", required=True, dest="expected_sha256", help="Trusted SHA-256 for the canonical source file")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--manifest", type=Path, default=Path("reports/research/historical_import_manifest.json"))
    args = parser.parse_args()

    actual_sha256 = sha256(args.csv_path)
    if actual_sha256.lower() != args.expected_sha256.lower():
        raise SystemExit("canonical dataset checksum mismatch")
    canonical = load_canonical_csv(args.csv_path)
    integrity = require_complete_common_history(canonical, CANONICAL_TIMEFRAME)
    overlap = verify_api_overlap(canonical, fetch_candles)
    hourly, four_hour = derive_timeframe(canonical, "1h"), derive_timeframe(canonical, "4h")
    hourly_integrity = require_complete_common_history(hourly, "1h")
    four_hour_integrity = require_complete_common_history(four_hour, "4h")

    grouped: dict[tuple[str, str], list[Candle]] = defaultdict(list)
    for candle in [*canonical, *hourly, *four_hour]:
        grouped[(candle.symbol, candle.timeframe)].append(candle)
    init_db(args.db)
    with connect(args.db) as connection:
        repository = CandleRepository(connection)
        for (symbol, timeframe), candles in grouped.items():
            repository.replace_timeframe(symbol, timeframe, sorted(candles, key=lambda candle: candle.open_time))
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps({"source": str(args.csv_path), "sha256": actual_sha256, "integrity": {"15m": integrity, "1h": hourly_integrity, "4h": four_hour_integrity}, "official_api_overlap": overlap, "imported": {f"{symbol}:{timeframe}": len(candles) for (symbol, timeframe), candles in grouped.items()}}, indent=2) + "\n", encoding="utf-8")
    print(f"Imported verified canonical 15m data and derived 1h/4h candles into {args.db}")


if __name__ == "__main__":
    main()
