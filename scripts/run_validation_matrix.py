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
DIAGNOSTIC_COLUMNS = ["symbol", "config_name", "period_name", "diagnostic_group", "diagnostic_key", "closed_trades", "win_rate", "expectancy_r", "profit_factor", "total_pnl", "max_losing_streak"]
DIAGNOSTIC_GROUPS = {
    "side": "performance_by_side",
    "parent_timeframe_alignment": "performance_by_parent_timeframe_alignment",
    "child_triangle_type": "performance_by_child_triangle_type",
    "4h_trend": "performance_by_4h_trend",
    "1h_trend": "performance_by_1h_trend",
    "mtf_zone_context": "performance_by_mtf_zone_context",
    "score_bucket": "performance_by_score_bucket",
}


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


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    trades = sum(int(row["closed_trades"]) for row in rows)
    weight = trades or 1
    return {"closed_trades": trades, "accepted_signals": sum(int(row["accepted_signals"]) for row in rows), "win_rate": sum(float(row["win_rate"]) * int(row["closed_trades"]) for row in rows) / weight, "expectancy_r": sum(float(row["expectancy_r"]) * int(row["closed_trades"]) for row in rows) / weight, "profit_factor": sum(float(row["profit_factor"]) * int(row["closed_trades"]) for row in rows) / weight, "max_drawdown": max((float(row["max_drawdown"]) for row in rows), default=0.0), "max_losing_streak": max((int(row["max_losing_streak"]) for row in rows), default=0), "total_pnl": sum(float(row["total_pnl"]) for row in rows), "zone_rejects": sum(int(row["zone_rejects"]) for row in rows), "sample_warning": trades < 20}


def _group_rows(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault("|".join(str(row[field]) for field in fields), []).append(row)
    return {key: _aggregate(items) for key, items in groups.items()}


def build_summary(rows: list[dict[str, Any]], diagnostics: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
        aggregate = _aggregate(items)
        overall.append({"config_name": name, "periods": len(items), "closed_trades": aggregate["closed_trades"], "average_expectancy_r": aggregate["expectancy_r"], "average_profit_factor": aggregate["profit_factor"], "max_drawdown": aggregate["max_drawdown"], "is_profitable_average": aggregate["expectancy_r"] > 0, "passes_minimum_pf": aggregate["profit_factor"] >= 1.2, "passes_minimum_sample": aggregate["closed_trades"] >= 50, "insufficient_total_sample": aggregate["closed_trades"] < 50, "robustness_warning": "; ".join(reason for reason, ok in (("negative average expectancy", aggregate["expectancy_r"] > 0), ("profit factor below 1.2", aggregate["profit_factor"] >= 1.2), ("fewer than 50 total trades", aggregate["closed_trades"] >= 50)) if not ok)})
    overall.sort(key=lambda item: (item["average_expectancy_r"] > 0, item["average_profit_factor"] > 1, item["closed_trades"], -item["max_drawdown"]), reverse=True)
    comparisons = _control_comparisons(completed)
    return {"best_config_by_symbol": by_symbol, "best_config_by_period": by_period, "overall_config_ranking": overall, "configs_with_positive_expectancy_all_periods": [name for name, items in grouped.items() if all(float(item["expectancy_r"]) > 0 for item in items)], "configs_with_pf_above_1_2_all_periods": [name for name, items in grouped.items() if all(float(item["profit_factor"]) > 1.2 for item in items)], "performance_by_symbol": _group_rows(completed, ("symbol",)), "performance_by_symbol_and_config": _group_rows(completed, ("symbol", "config_name")), "performance_by_symbol_and_period": _group_rows(completed, ("symbol", "period_name")), "performance_by_symbol_config_period": _group_rows(completed, ("symbol", "config_name", "period_name")), "config_vs_control": comparisons, "failure_diagnostics": diagnostics or []}


def _control_comparisons(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["symbol"], row["period_name"]), {})[row["config_name"]] = row
    output: dict[str, dict[str, float | int]] = {}
    for (symbol, period), configs in grouped.items():
        penalty = next((row for name, row in configs.items() if "zone_penalty" in name), None)
        if penalty is None:
            continue
        values: dict[str, float | int] = {}
        for name, row in configs.items():
            if "hard_1h_only" in name:
                prefix = "hard_1h"
            elif "hard_1h_15m" in name:
                prefix = "hard_1h_15m"
            else:
                continue
            values[f"{prefix}_vs_penalty_expectancy_delta"] = float(row["expectancy_r"]) - float(penalty["expectancy_r"])
            values[f"{prefix}_vs_penalty_pf_delta"] = float(row["profit_factor"]) - float(penalty["profit_factor"])
            values[f"{prefix}_vs_penalty_trade_count_delta"] = int(row["closed_trades"]) - int(penalty["closed_trades"])
        output[f"{symbol}|{period}"] = values
    return output


def write_validation_outputs(run_id: str, rows: list[dict[str, Any]], directory: Path = Path("reports/validation"), diagnostics: list[dict[str, Any]] | None = None) -> Path:
    output = directory / run_id
    output.mkdir(parents=True, exist_ok=True)
    with (output / "validation_matrix.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows([{key: row.get(key, "") for key in CSV_COLUMNS} for row in rows])
    with (output / "validation_diagnostics.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=DIAGNOSTIC_COLUMNS)
        writer.writeheader()
        writer.writerows(diagnostics or [])
    (output / "validation_summary.json").write_text(json.dumps(build_summary(rows, diagnostics), indent=2), encoding="utf-8")
    return output


def _diagnostic_rows(symbol: str, config_name: str, period_name: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for group, summary_key in DIAGNOSTIC_GROUPS.items():
        for key, metrics in summary.get(summary_key, {}).items():
            rows.append({"symbol": symbol, "config_name": config_name, "period_name": period_name, "diagnostic_group": group, "diagnostic_key": key, "closed_trades": metrics.get("trades", 0), "win_rate": metrics.get("win_rate", 0.0), "expectancy_r": metrics.get("average_r", 0.0), "profit_factor": metrics.get("profit_factor", 0.0), "total_pnl": metrics.get("total_pnl", 0.0), "max_losing_streak": metrics.get("max_losing_streak", 0)})
    return rows


def run_matrix(symbols: list[str], config_paths: list[str], periods: dict[str, dict[str, str | None]], db_path: str) -> tuple[str, list[dict[str, Any]]]:
    init_db(db_path)
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
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
                    diagnostics.extend(_diagnostic_rows(symbol, config_name, period_name, result.summary))
    write_validation_outputs(run_id, rows, diagnostics=diagnostics)
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
