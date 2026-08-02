from __future__ import annotations

import json

from scripts.compare_backtests import format_comparison, load_comparison


def test_compare_backtests_reads_two_summary_files(tmp_path) -> None:
    strict = tmp_path / "strict.json"
    penalty = tmp_path / "penalty.json"
    strict.write_text(json.dumps({"strategy_version": "strict", "closed_trades": 2, "accepted_signals": 5, "win_rate": 0.5, "expectancy_r": 0.2, "profit_factor": 1.3, "max_drawdown": 0.01, "max_losing_streak": 1, "nested_candidate_funnel": {"rejected_by_mtf_zone": 7}}))
    penalty.write_text(json.dumps({"strategy_version": "penalty", "closed_trades": 4, "accepted_signals": 8, "win_rate": 0.4, "expectancy_r": 0.1, "profit_factor": 1.1, "max_drawdown": 0.02, "max_losing_streak": 2, "nested_candidate_funnel": {"rejected_by_mtf_zone": 0}}))
    assert load_comparison(strict)["rejected_by_mtf_zone"] == 7
    output = format_comparison([strict, penalty])
    assert "strict" in output and "penalty" in output and "rejected_by_mtf_zone" in output
