from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from loguru import logger

from app.config.settings import AppConfig
from app.core.types import Candle, Decision, Side, Trade
from app.data.repositories import CandleRepository, SignalRepository, TradeRepository
from app.exchange.hyperliquid_data import fetch_candles
from app.strategy.evaluator import evaluate


@dataclass
class PaperState:
    last_evaluated_open_time: int | None = None
    open_trade: Trade | None = None


def evaluate_new_closed_candles(candles: list[Candle], state: PaperState, config: AppConfig, signal_repo: SignalRepository, trade_repo: TradeRepository) -> None:
    if not candles:
        return
    latest = candles[-1]
    if state.last_evaluated_open_time == latest.open_time:
        return
    if state.open_trade is not None:
        closed = _maybe_close_paper_trade(state.open_trade, latest)
        if closed:
            trade_repo.insert(closed)
            state.open_trade = None
    signal = evaluate(candles, config, latest.symbol, latest.timeframe)
    signal_repo.insert(signal)
    if signal.decision == Decision.ACCEPTED and state.open_trade is None and signal.side and signal.entry_price and signal.stop_loss and signal.take_profit:
        state.open_trade = Trade(
            signal.symbol,
            signal.timeframe,
            signal.side,
            latest.open_time,
            signal.entry_price,
            1.0,
            signal.stop_loss,
            signal.take_profit,
        )
        trade_repo.insert(state.open_trade)
    state.last_evaluated_open_time = latest.open_time
    logger.info(f"paper decision {signal.decision.value} {latest.symbol} {latest.timeframe}: {signal.reasons}")


def run_paper_loop(
    candle_repo: CandleRepository,
    signal_repo: SignalRepository,
    trade_repo: TradeRepository,
    config: AppConfig,
    symbol: str,
    timeframe: str,
    poll_seconds: int = 60,
    fetcher: Callable[[str, str, int], list[Candle]] = fetch_candles,
) -> None:
    state = PaperState()
    while True:
        candles = fetcher(symbol, timeframe, config.market.warmup_candles)
        candle_repo.insert_many(candles)
        stored = candle_repo.latest(symbol, timeframe, config.market.warmup_candles)
        evaluate_new_closed_candles(stored, state, config, signal_repo, trade_repo)
        time.sleep(poll_seconds)


def _maybe_close_paper_trade(trade: Trade, candle: Candle) -> Trade | None:
    if trade.side == Side.LONG:
        stop_hit = candle.low <= trade.stop_loss
        target_hit = candle.high >= trade.take_profit
        if not stop_hit and not target_hit:
            return None
        exit_price = trade.stop_loss if stop_hit else trade.take_profit
        pnl = exit_price - trade.entry_price
        risk = trade.entry_price - trade.stop_loss
    else:
        stop_hit = candle.high >= trade.stop_loss
        target_hit = candle.low <= trade.take_profit
        if not stop_hit and not target_hit:
            return None
        exit_price = trade.stop_loss if stop_hit else trade.take_profit
        pnl = trade.entry_price - exit_price
        risk = trade.stop_loss - trade.entry_price
    return Trade(
        trade.symbol,
        trade.timeframe,
        trade.side,
        trade.entry_time,
        trade.entry_price,
        trade.size,
        trade.stop_loss,
        trade.take_profit,
        candle.open_time,
        exit_price,
        pnl,
        pnl / risk if risk else 0.0,
        "closed",
    )
