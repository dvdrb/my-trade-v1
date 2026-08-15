from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.annotation.models import MarketState
from app.annotation.repository import AnnotationRepository
from app.config.settings import load_config
from app.core.types import Decision
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository
from app.strategy.evaluator import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare frozen baseline strategy decisions with human annotations.")
    parser.add_argument("--db", default="data/bot.sqlite3"); parser.add_argument("--config", default="app/config/strategy.yaml")
    parser.add_argument("--output", default="reports/human_alignment"); args = parser.parse_args()
    init_db(args.db); connection = connect(args.db); annotations = AnnotationRepository(connection).annotations(); candles = CandleRepository(connection); config = load_config(args.config)
    rows: list[dict[str, object]] = []
    for human in annotations:
        history = [c for c in candles.all(human.symbol, "15m") if c.open_time <= human.decision_time]
        if not history: continue
        bot = evaluate(history, config, symbol=human.symbol, timeframe="15m")
        human_trade = human.market_state == MarketState.TRADE
        bot_trade = bot.decision == Decision.ACCEPTED
        rows.append({"annotation_id": human.annotation_id, "symbol": human.symbol, "decision_time": human.decision_time,
                     "human_state": human.market_state.value, "human_side": human.side.value if human.side else None,
                     "bot_decision": bot.decision.value, "bot_side": bot.side.value if bot.side else None,
                     "trade_agreement": human_trade == bot_trade,
                     "direction_agreement": bool(human.side and bot.side and human.side.value == bot.side.value),
                     "entry_error": (human.trade_plan.entry_price - bot.entry_price) if human.trade_plan and bot.entry_price else None,
                     "sl_error": (human.trade_plan.stop_loss - bot.stop_loss) if human.trade_plan and bot.stop_loss else None,
                     "tp_error": (human.trade_plan.take_profit - bot.take_profit) if human.trade_plan and bot.take_profit else None})
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    with (output / "setup_disagreements.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]) if rows else ["annotation_id"]); writer.writeheader(); writer.writerows(rows)
    false_positive = [r for r in rows if r["bot_decision"] == "accepted" and r["human_state"] != "trade"]
    false_negative = [r for r in rows if r["bot_decision"] != "accepted" and r["human_state"] == "trade"]
    for name, data in (("false_positives.csv", false_positive), ("false_negatives.csv", false_negative), ("triangle_alignment.csv", rows), ("trade_plan_differences.csv", rows), ("feature_comparison.csv", rows)):
        with (output / name).open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]) if rows else ["annotation_id"]); writer.writeheader(); writer.writerows(data)
    (output / "summary.json").write_text(json.dumps({"annotation_count": len(rows), "trade_agreement": sum(bool(r["trade_agreement"]) for r in rows) / len(rows) if rows else None, "false_positives": len(false_positive), "false_negatives": len(false_negative)}, indent=2) + "\n")
    print(output)


if __name__ == "__main__": main()
