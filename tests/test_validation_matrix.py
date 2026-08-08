from __future__ import annotations

import csv
import json

from scripts.run_validation_matrix import build_summary, write_validation_outputs


def _row(**overrides):
    row = {"symbol": "BTC", "config_name": "hard_1h", "period_name": "full", "start_date": "", "end_date": "", "report_path": "report.json", "closed_trades": 10, "accepted_signals": 12, "expectancy_r": 0.2, "profit_factor": 1.4, "win_rate": 0.5, "max_drawdown": 0.02, "max_losing_streak": 2, "total_pnl": 2.0, "zone_rejects": 4, "sample_warning": True, "skip_reason": ""}
    row.update(overrides)
    return row


def test_validation_outputs_create_csv_and_json_with_period_metadata(tmp_path) -> None:
    output = write_validation_outputs("run", [_row(start_date="2026-05-01", end_date="2026-07-01")], tmp_path)
    with (output / "validation_matrix.csv").open() as file:
        assert list(csv.DictReader(file))[0]["period_name"] == "full"
    summary = json.loads((output / "validation_summary.json").read_text())
    assert summary["best_config_by_symbol"] == {"BTC": "hard_1h"}
    assert summary["overall_config_ranking"][0]["insufficient_total_sample"] is True


def test_validation_ranking_prefers_positive_expectancy_and_pf() -> None:
    summary = build_summary([_row(config_name="weak", expectancy_r=-0.1, profit_factor=0.9, closed_trades=30), _row(config_name="strong", expectancy_r=0.1, profit_factor=1.1, closed_trades=10)])
    assert summary["overall_config_ranking"][0]["config_name"] == "strong"


def test_missing_candle_row_is_marked_as_skipped() -> None:
    summary = build_summary([_row(symbol="ETH", skip_reason="missing candles", closed_trades=0, sample_warning=True)])
    assert summary["best_config_by_symbol"] == {}
