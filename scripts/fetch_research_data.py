from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.data.binance_usdm import SYMBOL_MAP, download_archive, fetch_klines, parse_archive
from app.data.db import connect, init_db
from app.data.historical import derive_timeframe, validate_candles
from app.data.repositories import CandleRepository


def months_between(start: datetime, end: datetime) -> list[str]:
    cursor = datetime(start.year, start.month, 1, tzinfo=UTC)
    months: list[str] = []
    while cursor < end:
        months.append(cursor.strftime("%Y-%m"))
        cursor = datetime(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1, tzinfo=UTC)
    return months


def canonical_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire checksum-verified Binance USD-M research candles.")
    parser.add_argument("--provider", required=True, choices=["binance-usdm"])
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--timeframe", default="15m", choices=["15m"])
    parser.add_argument("--start", default="2020-09-01")
    parser.add_argument("--end")
    parser.add_argument("--raw-root", type=Path, default=Path("data/research/raw/binance_usdm"))
    parser.add_argument("--canonical", type=Path, default=Path("data/research/canonical/binance_usdm_15m.csv"))
    parser.add_argument("--manifest", type=Path, default=Path("data/research/manifests/binance_usdm_manifest.json"))
    parser.add_argument("--db", default="data/research.sqlite3")
    args = parser.parse_args()
    if set(args.symbols) != set(SYMBOL_MAP):
        raise SystemExit("Binance research acquisition requires exactly BTC ETH SOL")
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC) if args.end else datetime.now(UTC)
    archive_months = months_between(start, datetime(end.year, end.month, 1, tzinfo=UTC))
    by_symbol: dict[str, dict[int, object]] = defaultdict(dict)
    records = []
    for local in args.symbols:
        remote = SYMBOL_MAP[local]
        for month in archive_months:
            record = download_archive(remote, args.timeframe, month, args.raw_root)
            records.append(record.__dict__)
            for candle in parse_archive(Path(record.path), local):
                by_symbol[local][candle.open_time] = candle
        current_start = int(datetime(end.year, end.month, 1, tzinfo=UTC).timestamp() * 1000)
        for candle in fetch_klines(remote, current_start, int(end.timestamp() * 1000)):
            by_symbol[local][candle.open_time] = candle

    first = max(min(values) for values in by_symbol.values())
    last = min(max(values) for values in by_symbol.values())
    step = 900_000
    expected = list(range(first, last + step, step))
    repaired: dict[str, list[int]] = {}
    for local, values in by_symbol.items():
        missing = [timestamp for timestamp in expected if timestamp not in values]
        repaired[local] = missing
        remote = SYMBOL_MAP[local]
        for offset in range(0, len(missing), 1_500):
            chunk = missing[offset:offset + 1_500]
            if not chunk:
                continue
            for candle in fetch_klines(remote, chunk[0], chunk[-1] + step):
                if candle.open_time in set(chunk):
                    values[candle.open_time] = candle
    common = [[by_symbol[symbol][timestamp] for timestamp in expected] for symbol in args.symbols]
    canonical = [candle for candles in common for candle in candles]
    integrity = validate_candles(canonical, "15m")
    if any(item.gaps or item.duplicate_open_times for item in integrity):
        raise SystemExit(f"unable to repair all Binance data gaps: {integrity}")
    args.canonical.parent.mkdir(parents=True, exist_ok=True)
    with args.canonical.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["symbol", "open_time", "close_time", "open", "high", "low", "close", "volume"])
        writer.writerows((c.symbol, c.open_time, c.close_time, c.open, c.high, c.low, c.close, c.volume) for c in canonical)
    digest = canonical_sha256(args.canonical)
    args.canonical.with_suffix(".sha256").write_text(f"{digest}  {args.canonical.name}\n", encoding="utf-8")
    hourly, four_hour = derive_timeframe(canonical, "1h"), derive_timeframe(canonical, "4h")
    init_db(args.db)
    with connect(args.db) as connection:
        repository = CandleRepository(connection)
        for symbol in args.symbols:
            repository.replace_timeframe(symbol, "15m", [c for c in canonical if c.symbol == symbol])
            repository.replace_timeframe(symbol, "1h", [c for c in hourly if c.symbol == symbol])
            repository.replace_timeframe(symbol, "4h", [c for c in four_hour if c.symbol == symbol])
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps({"provider": "binance_usdm", "market_type": "perpetual", "source_symbols": SYMBOL_MAP, "canonical_timeframe": "15m", "common_start": first, "common_end": last, "candle_count_by_symbol": {symbol: len(by_symbol[symbol]) for symbol in args.symbols}, "downloaded_archives": records, "repaired_gaps": repaired, "archive_checksum_status": "PASS", "canonical_sha256": digest, "created_at": datetime.now(UTC).isoformat()}, indent=2) + "\n", encoding="utf-8")
    print(f"Canonical dataset: {args.canonical} ({digest})")


if __name__ == "__main__":
    main()
