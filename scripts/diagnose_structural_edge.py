from __future__ import annotations

import argparse
import csv
import json
import math
import traceback
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

import yaml

from app.backtest.runner import run_backtest
from app.config.settings import load_config
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository


OUT = Path("reports/research")


def metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    values = [float(row["r_multiple"]) for row in rows]
    wins = [value for value in values if value > 0]
    losses = [-value for value in values if value < 0]
    return {"trade_count": len(values), "win_rate": len(wins) / len(values) if values else 0.0, "average_r": sum(values) / len(values) if values else 0.0, "median_r": median(values) if values else 0.0, "profit_factor": sum(wins) / sum(losses) if losses else None, "total_r": sum(values)}


def _correlation(rows: list[dict[str, Any]], field: str) -> float | None:
    pairs = [(float(row[field]), float(row["r_multiple"])) for row in rows if isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool)]
    if len(pairs) < 20:
        return None
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    denominator = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in pairs) / denominator if denominator else None


def _bucket_diagnostics(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    values = sorted({value for row in rows if (value := row.get(field)) is not None and isinstance(value, (str, int, float, bool))}, key=str)
    if not values or len(values) > 12:
        return []
    return [{"feature": field, "bucket": str(value), **metrics([row for row in rows if row.get(field) == value])} for value in values]


def _numeric_buckets(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    values = sorted(float(row[field]) for row in rows if isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool))
    if len(values) < 20 or values[0] == values[-1]:
        return []
    cuts = [values[len(values) * index // 4] for index in range(1, 4)]
    labels = [f"q1 <= {cuts[0]:.5g}", f"q2 <= {cuts[1]:.5g}", f"q3 <= {cuts[2]:.5g}", f"q4 > {cuts[2]:.5g}"]
    groups = [[] for _ in labels]
    for row in rows:
        value = row.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        bucket = 0 if value <= cuts[0] else 1 if value <= cuts[1] else 2 if value <= cuts[2] else 3
        groups[bucket].append(row)
    return [{"feature": field, "bucket": label, **metrics(group)} for label, group in zip(labels, groups) if group]


def _findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    excluded = {"r_multiple", "pnl", "entry_time", "exit_time"}
    numeric = [key for key in rows[0] if key not in excluded and any(isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool) for row in rows)]
    findings = []
    for field in numeric:
        corr = _correlation(rows, field)
        if corr is None:
            continue
        winners = [float(row[field]) for row in rows if row["winner_or_loser"] == "winner" and isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool)]
        losers = [float(row[field]) for row in rows if row["winner_or_loser"] == "loser" and isinstance(row.get(field), (int, float)) and not isinstance(row.get(field), bool)]
        if not winners or not losers:
            continue
        effect = sum(winners) / len(winners) - sum(losers) / len(losers)
        findings.append({"feature": field, "r_correlation": corr, "winner_loser_mean_difference": effect, "sample_size": len(winners) + len(losers)})
    return sorted(findings, key=lambda item: abs(float(item["r_correlation"])), reverse=True)


def run(symbols: list[str], config_path: str, periods_path: str, db_path: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    periods = yaml.safe_load(Path(periods_path).read_text(encoding="utf-8"))["periods"]
    train = periods["train"]
    start_date, end_date = str(train["start"]), str(train["end"])
    start = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)
    end = int(datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)
    init_db(db_path)
    rows: list[dict[str, Any]] = []
    with connect(db_path) as connection:
        repo = CandleRepository(connection)
        for symbol in symbols:
            config = load_config(config_path)
            config.market.symbols = [symbol]
            result = run_backtest(repo, None, None, config, symbol, "15m", start, end, Path(config_path).stem, start_date, end_date)
            by_time = {signal.open_time: signal for signal in result.signals if signal.metadata}
            for trade in result.trades:
                signal = by_time.get(trade.signal_time)
                if signal is None:
                    continue
                row: dict[str, Any] = {"symbol": trade.symbol, "side": trade.side.value, "entry_time": trade.entry_time, "exit_time": trade.exit_time, "r_multiple": trade.r_multiple, "winner_or_loser": "winner" if trade.r_multiple > 0 else "loser", "pnl": trade.pnl, "score_total": trade.score_total, **signal.metadata}
                rows.append(row)
    diagnostic_rows: list[dict[str, Any]] = []
    for field in sorted({key for row in rows for key in row}):
        diagnostic_rows.extend(_bucket_diagnostics(rows, field))
        diagnostic_rows.extend(_numeric_buckets(rows, field))
    findings = _findings(rows)
    summary = {"created_at": datetime.now(UTC).isoformat(), "period": {"start": start_date, "end": end_date}, "config": config_path, "trade_count": len(rows), "overall": metrics(rows), "by_symbol": {symbol: metrics([row for row in rows if row["symbol"] == symbol]) for symbol in symbols}, "by_side": {side: metrics([row for row in rows if row["side"] == side]) for side in ("long", "short")}, "winner_loser_feature_ranking": findings, "by_symbol_feature_ranking": {symbol: _findings([row for row in rows if row["symbol"] == symbol]) for symbol in symbols}, "bucket_diagnostics": diagnostic_rows}
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build train-only nested-MTF structural diagnostics.")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--config", default="app/config/strategy_nested_mtf_zone_penalty.yaml")
    parser.add_argument("--periods", default="app/config/research_train_validation_periods.yaml")
    parser.add_argument("--db", default="data/research.sqlite3")
    args = parser.parse_args()
    rows, summary = run(args.symbols, args.config, args.periods, args.db)
    OUT.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with (OUT / "structural_diagnostics.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "structural_diagnostics.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    hypotheses = [{"description": f"{finding['feature']} has correlation {finding['r_correlation']:.3f} with realized R on train", "structural_rationale": "observed winner/loser separation; requires validation before use", "train_sample_size": finding["sample_size"], "observed_expectancy_difference": finding["winner_loser_mean_difference"], "symbols_affected": args.symbols, "confidence_level": "exploratory", "proposed_experiment": f"Test one bounded threshold or score adjustment for {finding['feature']} only if cross-symbol buckets agree."} for finding in summary["winner_loser_feature_ranking"][:12]]
    (OUT / "hypothesis_rankings.json").write_text(json.dumps({"created_at": summary["created_at"], "hypotheses": hypotheses}, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} train trades to {OUT / 'structural_diagnostics.csv'}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "structural_diagnostics_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
