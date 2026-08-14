from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.config.settings import load_config
from app.core.types import Decision
from app.data.db import connect
from app.data.repositories import CandleRepository
from app.strategy.context import MarketContext
from app.strategy.evaluator import evaluate


def _signals(candles, symbol: str):
    config = load_config("app/config/strategy_15m_scoring.yaml")
    return [evaluate(candles[: index + 1], config, symbol, "15m") for index in range(800, len(candles))]


def _nested_signals(entry, local, regime, symbol: str):
    config = load_config("app/config/strategy_nested_mtf_zone_penalty.yaml")
    window = max(config.market.warmup_candles, config.strategy.trend.ema_slow + config.strategy.pivots.right + config.strategy.triangle.max_candles)
    output = []
    for index in range(800, len(entry)):
        as_of = entry[index].close_time
        local_closed = [candle for candle in local if (candle.close_time or candle.open_time + 3_600_000) <= as_of]
        regime_closed = [candle for candle in regime if (candle.close_time or candle.open_time + 14_400_000) <= as_of]
        context = MarketContext(symbol, "15m", "1h", "4h", entry[max(0, index - window + 1):index + 1], local_closed[-window:], regime_closed[-window:])
        output.append(evaluate(context.entry_candles, config, symbol, "15m", context=context))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-venue structure diagnostic; not a Binance integrity gate.")
    parser.add_argument("--binance-db", default="data/research.sqlite3")
    parser.add_argument("--hyperliquid-db", default="data/bot.sqlite3")
    parser.add_argument("--output", type=Path, default=Path("reports/data_validation/binance_hyperliquid_compatibility.json"))
    args = parser.parse_args()
    result: dict[str, object] = {"generated_at": datetime.now(UTC).isoformat(), "purpose": "cross_venue_compatibility_only", "symbols": {}}
    with connect(args.binance_db) as binance_connection, connect(args.hyperliquid_db) as hyperliquid_connection:
        binance_repo, hyperliquid_repo = CandleRepository(binance_connection), CandleRepository(hyperliquid_connection)
        for symbol in ("BTC", "ETH", "SOL"):
            binance = {candle.open_time: candle for candle in binance_repo.all(symbol, "15m")}
            hyperliquid = {candle.open_time: candle for candle in hyperliquid_repo.all(symbol, "15m")}
            timestamps = sorted(set(binance) & set(hyperliquid))
            if len(timestamps) < 800:
                result["symbols"][symbol] = {"status": "insufficient_overlap", "overlapping_candles": len(timestamps)}
                continue
            timestamps = timestamps[-1_200:]
            b = [binance[timestamp] for timestamp in timestamps]
            h = [hyperliquid[timestamp] for timestamp in timestamps]
            close = [abs(left.close - right.close) / right.close for left, right in zip(b, h)]
            high_low = [max(abs(left.high - right.high) / right.high, abs(left.low - right.low) / right.low) for left, right in zip(b, h)]
            bs, hs = _signals(b, symbol), _signals(h, symbol)
            b_local, h_local = binance_repo.all(symbol, "1h"), hyperliquid_repo.all(symbol, "1h")
            b_regime, h_regime = binance_repo.all(symbol, "4h"), hyperliquid_repo.all(symbol, "4h")
            b_nested, h_nested = _nested_signals(b, b_local, b_regime, symbol), _nested_signals(h, h_local, h_regime, symbol)
            triangle = [(int(signal.metadata.get("triangle_candidates_found", 0)) > 0) == (int(other.metadata.get("triangle_candidates_found", 0)) > 0) for signal, other in zip(bs, hs)]
            breakout = [(signal.side.value if signal.side else None) == (other.side.value if other.side else None) for signal, other in zip(bs, hs)]
            accepted = [signal.decision == other.decision == Decision.ACCEPTED for signal, other in zip(bs, hs)]
            nested = [(int(signal.metadata.get("nested_setups_found", 0)) > 0) == (int(other.metadata.get("nested_setups_found", 0)) > 0) for signal, other in zip(b_nested, h_nested)]
            nested_breakout = [(signal.side.value if signal.side else None) == (other.side.value if other.side else None) for signal, other in zip(b_nested, h_nested)]
            nested_accepted = [signal.decision == other.decision == Decision.ACCEPTED for signal, other in zip(b_nested, h_nested)]
            result["symbols"][symbol] = {"status": "ok", "overlapping_candles": len(timestamps), "mean_close_deviation": sum(close) / len(close), "mean_high_low_deviation": sum(high_low) / len(high_low), "triangle_candidate_agreement": sum(triangle) / len(triangle), "breakout_direction_agreement": sum(breakout) / len(breakout), "accepted_signal_agreement": sum(accepted) / len(accepted), "nested_setup_agreement": sum(nested) / len(nested), "nested_breakout_direction_agreement": sum(nested_breakout) / len(nested_breakout), "nested_accepted_signal_agreement": sum(nested_accepted) / len(nested_accepted)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
