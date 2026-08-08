from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.backtest.runner import run_backtest
from app.config.settings import load_config
from app.data.db import DEFAULT_DB_PATH, connect, init_db
from app.data.repositories import CandleRepository


DEFAULT_CONFIGS = [
    "app/config/strategy_nested_mtf_zone_penalty.yaml",
    "app/config/strategy_nested_mtf_hard_1h_only.yaml",
    "app/config/strategy_nested_mtf_hard_1h_15m_penalty_4h.yaml",
    "app/config/strategy_nested_mtf_strict_all_zones.yaml",
]
CSV_COLUMNS = ["symbol", "config_name", "period_name", "start_date", "end_date", "report_path", "closed_trades", "accepted_signals", "expectancy_r", "profit_factor", "win_rate", "max_drawdown", "max_losing_streak", "total_pnl", "zone_rejects", "sample_warning", "skip_reason"]


def candle_availability(repo: CandleRepository, symbol: str) -> dict[str, int]:
    return {timeframe: len(repo.all(symbol, timeframe)) for timeframe in ("15m", "1h", "4h")}


def parse_periods(path: str | None) -> dict[str, dict[str, str | None]]:
    if path is None:
        return {"full": {"start": None, "end": None}}
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    periods = data.get("periods", {})
    return {name: {"start": str(value["start"]) if value.get("start") else None, "end": str(value["end"]) if value.get("end") else None} for name, value in periods.items()} or {"full": {"start": None, "end": None}}


def date_to_ms(value: str | None) -> int | None:
    return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000) if value else None


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if not row.get("skip_reason")]
    def ranking(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda row: (float(row["expectancy_r"]) > 0, float(row["profit_factor"]) > 1, int(row["closed_trades"]), -float(row["max_drawdown"])), reverse=True)
    by_symbol = {symbol: ranking([row for row in completed if row["symbol"] == symbol])[0]["config_name"] for symbol in {row["symbol"] for row in completed} if ranking([row for row in completed if row["symbol"] == symbol])}
    by_period = {period: ranking([row for row in completed if row["period_name"] == period])[0]["config_name"] for period in {row["period_name"] for row in completed} if ranking([row for row in completed if row["period_name"] == period])}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in completed:
        grouped.setdefault(row["config_name"], []).append(row)
    overall = []
    for name, items in grouped.items():
        overall.append({"config_name": name, "periods": len(items), "closed_trades": sum(int(item["closed_trades"]) for item in items), "average_expectancy_r": sum(float(item["expectancy_r"]) for item in items) / len(items), "average_profit_factor": sum(float(item["profit_factor"]) for item in items) / len(items), "max_drawdown": max(float(item["max_drawdown"]) for item in items), "insufficient_total_sample": sum(int(item["closed_trades"]) for item in items) < 50})
    overall.sort(key=lambda item: (item["average_expectancy_r"] > 0, item["average_profit_factor"] > 1, item["closed_trades"], -item["max_drawdown"]), reverse=True)
    return {"best_config_by_symbol": by_symbol, "best_config_by_period": by_period, "overall_config_ranking": overall, "configs_with_positive_expectancy_all_periods": [name for name, items in grouped.items() if all(float(item["expectancy_r"]) > 0 for item in items)], "configs_with_pf_above_1_2_all_periods": [name for name, items in grouped.items() if all(float(item["profit_factor"]) > 1.2 for item in items)]}


def write_validation_outputs(run_id: str, rows: list[dict[str, Any]], directory: Path = Path("reports/validation")) -> Path:
    output = directory / run_id
    output.mkdir(parents=True, exist_ok=True)
    with (output / "validation_matrix.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (output / "validation_summary.json").write_text(json.dumps(build_summary(rows), indent=2), encoding="utf-8")
    return output


def run_matrix(symbols: list[str], config_paths: list[str], periods: dict[str, dict[str, str | None]], db_path: str) -> tuple[str, list[dict[str, Any]]]:
    init_db(db_path)
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    rows: list[dict[str, Any]] = []
    with connect(db_path) as connection:
        repo = CandleRepository(connection)
        for symbol in symbols:
            availability = candle_availability(repo, symbol)
            print(f"{symbol} candles: {availability}")
            for config_path in config_paths:
                config_name = Path(config_path).stem
                for period_name, period in periods.items():
                    base = {"symbol": symbol, "config_name": config_name, "period_name": period_name, "start_date": period["start"] or "", "end_date": period["end"] or ""}
                    if any(count == 0 for count in availability.values()):
                        rows.append({**base, "report_path": "", "closed_trades": 0, "accepted_signals": 0, "expectancy_r": 0.0, "profit_factor": 0.0, "win_rate": 0.0, "max_drawdown": 0.0, "max_losing_streak": 0, "total_pnl": 0.0, "zone_rejects": 0, "sample_warning": True, "skip_reason": f"missing candles: {availability}"})
                        continue
                    config = load_config(config_path)
                    config.market.symbols = [symbol]
                    result = run_backtest(repo, None, None, config, symbol, config.market.entry_timeframe or config.market.timeframe, date_to_ms(period["start"]), date_to_ms(period["end"]), config_name, period["start"], period["end"])
                    nested = result.summary.get("nested_candidate_funnel", {})
                    rows.append({**base, "report_path": f"reports/backtests/{result.run_id}/summary.json", "closed_trades": result.summary["closed_trades"], "accepted_signals": result.summary["accepted_signals"], "expectancy_r": result.summary["expectancy_r"], "profit_factor": result.summary["profit_factor"], "win_rate": result.summary["win_rate"], "max_drawdown": result.summary["max_drawdown"], "max_losing_streak": result.summary["max_losing_streak"], "total_pnl": result.summary["total_pnl"], "zone_rejects": nested.get("rejected_by_mtf_zone", 0), "sample_warning": result.summary["closed_trades"] < 20, "skip_reason": ""})
    write_validation_outputs(run_id, rows)
    return run_id, rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run nested-MTF validation across symbols, configs, and date periods.")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--configs", nargs="+", default=DEFAULT_CONFIGS)
    parser.add_argument("--periods", help="YAML file with a top-level periods mapping")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    run_id, rows = run_matrix(args.symbols, args.configs, parse_periods(args.periods), args.db)
    print(f"Validation report: reports/validation/{run_id} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
