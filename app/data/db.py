from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("data/bot.sqlite3")


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                open_time INTEGER NOT NULL,
                close_time INTEGER,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL DEFAULT 0,
                UNIQUE(symbol, timeframe, open_time)
            );

            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                open_time INTEGER,
                decision TEXT NOT NULL,
                side TEXT,
                score REAL NOT NULL DEFAULT 0,
                reasons TEXT NOT NULL,
                entry_price REAL,
                stop_loss REAL,
                take_profit REAL,
                reward_risk REAL,
                strategy_version TEXT NOT NULL,
                triangle_type TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_time INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                size REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                exit_time INTEGER,
                exit_price REAL,
                pnl REAL NOT NULL DEFAULT 0,
                r_multiple REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL
            );
            """
        )
        _add_column(connection, "signals", "position_size", "REAL")
        _add_column(connection, "signals", "risk_amount", "REAL")
        _add_column(connection, "signals", "metadata", "TEXT NOT NULL DEFAULT '{}'")
        _add_column(connection, "trades", "signal_time", "INTEGER")
        _add_column(connection, "trades", "strategy_version", "TEXT NOT NULL DEFAULT ''")
        _add_column(connection, "trades", "triangle_type", "TEXT")
        _add_column(connection, "trades", "risk_amount", "REAL")
        _add_column(connection, "trades", "score_total", "REAL")
        _add_column(connection, "trades", "score_trend_quality", "REAL")
        _add_column(connection, "trades", "score_zone_quality", "REAL")
        _add_column(connection, "trades", "score_risk_quality", "REAL")
        _add_column(connection, "trades", "triangle_cleanliness_score", "REAL")
        _add_column(connection, "trades", "triangle_wick_violation_count", "INTEGER")
        _add_column(connection, "trades", "triangle_close_violation_count", "INTEGER")
        _add_column(connection, "trades", "triangle_max_wick_violation", "REAL")
        _add_column(connection, "trades", "triangle_max_close_violation", "REAL")
        _add_column(connection, "trades", "triangle_line_tolerance_used", "REAL")


def _add_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
