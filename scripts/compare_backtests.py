from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FIELDS = ("closed_trades", "accepted_signals", "win_rate", "expectancy_r", "profit_factor", "max_drawdown", "max_losing_streak", "rejected_by_mtf_zone", "would_be_blocked_trades", "would_be_blocked_expectancy_r", "would_be_blocked_profit_factor")


def load_comparison(path: str | Path) -> dict[str, Any]:
    report_path = Path(path)
    summary = json.loads(report_path.read_text(encoding="utf-8"))
    nested_funnel = summary.get("nested_candidate_funnel", {})
    counterfactual = summary.get("performance_by_would_be_strict_zone_blocked", {}).get("True", {})
    return {
        "config": summary.get("strategy_version", "unknown"),
        "report_path": str(report_path),
        "closed_trades": summary.get("closed_trades", summary.get("total_trades", 0)),
        "accepted_signals": summary.get("accepted_signals", 0),
        "win_rate": summary.get("win_rate", 0.0),
        "expectancy_r": summary.get("expectancy_r", 0.0),
        "profit_factor": summary.get("profit_factor", 0.0),
        "max_drawdown": summary.get("max_drawdown", 0.0),
        "max_losing_streak": summary.get("max_losing_streak", 0),
        "rejected_by_mtf_zone": nested_funnel.get("rejected_by_mtf_zone", summary.get("rejected_by_mtf_zone", 0)),
        "would_be_blocked_trades": counterfactual.get("trades", 0),
        "would_be_blocked_expectancy_r": counterfactual.get("average_r", 0.0),
        "would_be_blocked_profit_factor": counterfactual.get("profit_factor", 0.0),
    }


def format_comparison(paths: list[str | Path]) -> str:
    rows = [load_comparison(path) for path in paths]
    headers = ("config", "report_path", *FIELDS)
    widths = {header: max(len(header), *(len(str(row[header])) for row in rows)) for header in headers}
    line = " | ".join(header.ljust(widths[header]) for header in headers)
    divider = "-|-".join("-" * widths[header] for header in headers)
    body = [" | ".join(str(row[header]).ljust(widths[header]) for header in headers) for row in rows]
    return "\n".join([line, divider, *body])


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare backtest summary JSON files.")
    parser.add_argument("summary_paths", nargs="+", help="One or more reports/backtests/*/summary.json paths")
    args = parser.parse_args()
    print(format_comparison(args.summary_paths))


if __name__ == "__main__":
    main()
