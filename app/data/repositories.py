from __future__ import annotations

import json
import sqlite3

from app.core.types import Candle, Decision, Signal, Side, Trade


class CandleRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def insert(self, candle: Candle) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO candles
            (symbol, timeframe, open_time, close_time, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candle.symbol,
                candle.timeframe,
                candle.open_time,
                candle.close_time,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
            ),
        )

    def insert_many(self, candles: list[Candle]) -> None:
        for candle in candles:
            self.insert(candle)
        self.connection.commit()

    def latest(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        rows = self.connection.execute(
            """
            SELECT * FROM (
                SELECT * FROM candles
                WHERE symbol = ? AND timeframe = ?
                ORDER BY open_time DESC
                LIMIT ?
            )
            ORDER BY open_time ASC
            """,
            (symbol, timeframe, limit),
        ).fetchall()
        return [_row_to_candle(row) for row in rows]

    def all(self, symbol: str, timeframe: str) -> list[Candle]:
        rows = self.connection.execute(
            "SELECT * FROM candles WHERE symbol = ? AND timeframe = ? ORDER BY open_time ASC",
            (symbol, timeframe),
        ).fetchall()
        return [_row_to_candle(row) for row in rows]


class SignalRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def insert(self, signal: Signal) -> None:
        self.connection.execute(
            """
            INSERT INTO signals
            (symbol, timeframe, open_time, decision, side, score, reasons, entry_price,
             stop_loss, take_profit, reward_risk, strategy_version, triangle_type, position_size,
             risk_amount, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.symbol,
                signal.timeframe,
                signal.open_time,
                signal.decision.value,
                signal.side.value if signal.side else None,
                signal.score,
                json.dumps(signal.reasons),
                signal.entry_price,
                signal.stop_loss,
                signal.take_profit,
                signal.reward_risk,
                signal.strategy_version,
                signal.triangle_type,
                signal.position_size,
                signal.risk_amount,
                json.dumps(signal.metadata),
            ),
        )
        self.connection.commit()


class TradeRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def insert(self, trade: Trade) -> None:
        self.connection.execute(
            """
            INSERT INTO trades
            (symbol, timeframe, side, entry_time, entry_price, size, stop_loss, take_profit,
             exit_time, exit_price, pnl, r_multiple, status, signal_time, strategy_version,
             triangle_type, risk_amount, score_total, score_trend_quality, score_zone_quality,
             score_risk_quality, triangle_cleanliness_score, triangle_wick_violation_count,
             triangle_close_violation_count, triangle_max_wick_violation,
             triangle_max_close_violation, triangle_line_tolerance_used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.symbol,
                trade.timeframe,
                trade.side.value,
                trade.entry_time,
                trade.entry_price,
                trade.size,
                trade.stop_loss,
                trade.take_profit,
                trade.exit_time,
                trade.exit_price,
                trade.pnl,
                trade.r_multiple,
                trade.status,
                trade.signal_time,
                trade.strategy_version,
                trade.triangle_type,
                trade.risk_amount,
                trade.score_total,
                trade.score_trend_quality,
                trade.score_zone_quality,
                trade.score_risk_quality,
                trade.triangle_cleanliness_score,
                trade.triangle_wick_violation_count,
                trade.triangle_close_violation_count,
                trade.triangle_max_wick_violation,
                trade.triangle_max_close_violation,
                trade.triangle_line_tolerance_used,
            ),
        )
        self.connection.commit()


def _row_to_candle(row: sqlite3.Row) -> Candle:
    return Candle(
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        open_time=row["open_time"],
        close_time=row["close_time"],
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
    )


def signal_from_row(row: sqlite3.Row) -> Signal:
    side = Side(row["side"]) if row["side"] else None
    return Signal(
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        open_time=row["open_time"],
        decision=Decision(row["decision"]),
        side=side,
        score=row["score"],
        reasons=json.loads(row["reasons"]),
        entry_price=row["entry_price"],
        stop_loss=row["stop_loss"],
        take_profit=row["take_profit"],
        reward_risk=row["reward_risk"],
        strategy_version=row["strategy_version"],
        triangle_type=row["triangle_type"],
        position_size=row["position_size"] if "position_size" in row.keys() else None,
        risk_amount=row["risk_amount"] if "risk_amount" in row.keys() else None,
        metadata=json.loads(row["metadata"]) if "metadata" in row.keys() and row["metadata"] else {},
    )
