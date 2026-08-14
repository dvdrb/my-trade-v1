from __future__ import annotations

import argparse
import json
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from app.data.db import DEFAULT_DB_PATH, connect
from app.data.repositories import CandleRepository
from app.exchange.hyperliquid_data import INTERVAL_MS


REQUIREMENTS = {"15m": 20_000, "1h": 5_000, "4h": 2_000}


def audit_symbol(repo: CandleRepository, symbol: str) -> dict[str, object]:
    timeframes: dict[str, object] = {}
    for timeframe, minimum in REQUIREMENTS.items():
        candles = repo.all(symbol, timeframe)
        gaps = sum(
            1
            for previous, current in zip(candles, candles[1:])
            if current.open_time - previous.open_time != INTERVAL_MS[timeframe]
        )
        timeframes[timeframe] = {
            "candles": len(candles),
            "minimum_required": minimum,
            "meets_minimum": len(candles) >= minimum,
            "internal_gaps": gaps,
            "first": _iso(candles[0].open_time) if candles else None,
            "last": _iso(candles[-1].open_time) if candles else None,
        }
    return timeframes


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp / 1000, UTC).isoformat().replace("+00:00", "Z")


def common_history(repo: CandleRepository, symbols: list[str]) -> dict[str, object]:
    result: dict[str, object] = {}
    for timeframe, minimum in REQUIREMENTS.items():
        by_symbol = {symbol: repo.all(symbol, timeframe) for symbol in symbols}
        if any(not candles for candles in by_symbol.values()):
            result[timeframe] = {"common_candles": 0, "minimum_required": minimum, "common_gaps": 0, "meets_minimum": False}
            continue
        start = max(candles[0].open_time for candles in by_symbol.values())
        end = min(candles[-1].open_time for candles in by_symbol.values())
        common_open_times = set.intersection(*(set(candle.open_time for candle in candles if start <= candle.open_time <= end) for candles in by_symbol.values()))
        expected = (end - start) // INTERVAL_MS[timeframe] + 1
        result[timeframe] = {
            "first": _iso(start),
            "last": _iso(end),
            "common_candles": len(common_open_times),
            "minimum_required": minimum,
            "common_gaps": expected - len(common_open_times),
            "meets_minimum": len(common_open_times) >= minimum and expected == len(common_open_times),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail-closed data-quality audit for nested-MTF research.")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--provider", choices=["hyperliquid", "binance_usdm"], default="binance_usdm")
    parser.add_argument("--db", default="data/research.sqlite3")
    parser.add_argument("--manifest", type=Path, default=Path("data/research/manifests/binance_usdm_manifest.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with connect(args.db) as connection:
        repo = CandleRepository(connection)
        result = {symbol: audit_symbol(repo, symbol) for symbol in args.symbols}
        result["common_history"] = common_history(repo, args.symbols)
    individual_ready = all(
        bool(values[timeframe]["meets_minimum"]) and int(values[timeframe]["internal_gaps"]) == 0
        for symbol, values in result.items()
        if symbol not in {"research_ready", "common_history"}
        for timeframe in REQUIREMENTS
    )
    common_ready = all(bool(values["meets_minimum"]) for values in result["common_history"].values())
    provider_checks: dict[str, bool] = {}
    if args.provider == "binance_usdm":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest.exists() else {}
        canonical = Path("data/research/canonical/binance_usdm_15m.csv")
        provider_checks = {
            "archive_checksums": manifest.get("archive_checksum_status") == "PASS",
            "canonical_sha256": canonical.exists() and manifest.get("canonical_sha256") == hashlib.sha256(canonical.read_bytes()).hexdigest(),
            "provider": manifest.get("provider") == "binance_usdm",
        }
    result["provider_checks"] = provider_checks
    result["research_ready"] = individual_ready and common_ready and all(provider_checks.values())
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if not result["research_ready"]:
        raise SystemExit("Research data audit failed: do not run optimization or validation splits.")


if __name__ == "__main__":
    main()
