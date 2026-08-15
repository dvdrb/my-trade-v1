from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.annotation.models import BotCandidateReview, HumanAnnotation, ReplaySession, SimulatedTrade


def _now() -> str:
    return datetime.now(UTC).isoformat()


class AnnotationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_session(self, session: ReplaySession) -> ReplaySession:
        self.connection.execute(
            "INSERT INTO replay_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session.session_id, session.symbol, session.started_at_market_time, session.replay_time,
             session.ended_at_market_time, session.status, session.mode,
             session.created_at.isoformat(), session.updated_at.isoformat()),
        )
        self.connection.commit()
        return session

    def get_session(self, session_id: str) -> ReplaySession | None:
        row = self.connection.execute("SELECT * FROM replay_sessions WHERE session_id = ?", (session_id,)).fetchone()
        return _session(row) if row else None

    def sessions(self) -> list[ReplaySession]:
        return [_session(row) for row in self.connection.execute("SELECT * FROM replay_sessions ORDER BY updated_at DESC")]

    def update_session_time(self, session_id: str, replay_time: int) -> ReplaySession:
        self.connection.execute("UPDATE replay_sessions SET replay_time = ?, updated_at = ? WHERE session_id = ?",
                                (replay_time, _now(), session_id))
        self.connection.commit()
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"unknown replay session {session_id}")
        return session

    def save_annotation(self, annotation: HumanAnnotation) -> HumanAnnotation:
        previous = self.connection.execute("SELECT payload FROM human_annotations WHERE annotation_id = ?",
                                           (annotation.annotation_id,)).fetchone()
        now = _now()
        payload = annotation.model_dump_json()
        if previous:
            revision = self.connection.execute("SELECT COALESCE(MAX(revision_number), 0) FROM annotation_revisions WHERE annotation_id = ?", (annotation.annotation_id,)).fetchone()[0] + 1
            self.connection.execute("INSERT INTO annotation_revisions (annotation_id, revision_number, payload, created_at) VALUES (?, ?, ?, ?)",
                                    (annotation.annotation_id, revision, previous["payload"], now))
            self.connection.execute("UPDATE human_annotations SET session_id=?, symbol=?, decision_time=?, schema_version=?, payload=?, updated_at=? WHERE annotation_id=?",
                                    (annotation.session_id, annotation.symbol, annotation.decision_time, annotation.schema_version, payload, now, annotation.annotation_id))
        else:
            self.connection.execute("INSERT INTO human_annotations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                    (annotation.annotation_id, annotation.session_id, annotation.symbol, annotation.decision_time,
                                     annotation.schema_version, payload, annotation.created_at.isoformat(), annotation.updated_at.isoformat()))
        self.connection.commit()
        return annotation

    def annotations(self, session_id: str | None = None) -> list[HumanAnnotation]:
        query, args = "SELECT payload FROM human_annotations", ()
        if session_id:
            query += " WHERE session_id = ?"; args = (session_id,)
        query += " ORDER BY decision_time, created_at"
        return [HumanAnnotation.model_validate_json(row["payload"]) for row in self.connection.execute(query, args)]

    def revisions(self, annotation_id: str) -> list[HumanAnnotation]:
        return [HumanAnnotation.model_validate_json(row["payload"]) for row in self.connection.execute(
            "SELECT payload FROM annotation_revisions WHERE annotation_id = ? ORDER BY revision_number", (annotation_id,))]

    def save_trade(self, trade: SimulatedTrade) -> SimulatedTrade:
        payload = trade.model_dump_json()
        self.connection.execute(
            "INSERT OR REPLACE INTO simulated_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trade.simulated_trade_id, trade.annotation_id, trade.session_id, trade.symbol, trade.side.value,
             trade.entry_price, trade.stop_loss, trade.take_profit, trade.created_at_market_time, trade.status,
             trade.entry_time, trade.exit_time, trade.exit_price, trade.realized_r, payload,
             trade.created_at.isoformat(), trade.updated_at.isoformat()),
        )
        self.connection.commit(); return trade

    def trades(self, session_id: str | None = None) -> list[SimulatedTrade]:
        query, args = "SELECT payload FROM simulated_trades", ()
        if session_id:
            query += " WHERE session_id = ?"; args = (session_id,)
        return [SimulatedTrade.model_validate_json(row["payload"]) for row in self.connection.execute(query, args)]

    def save_screenshot(self, annotation_id: str, timeframe: str, image_data: bytes, root: str | Path) -> str:
        directory = Path(root) / annotation_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{timeframe}.png"
        path.write_bytes(image_data)
        self.connection.execute("INSERT OR REPLACE INTO annotation_screenshots VALUES (?, ?, ?, ?, ?)",
                                (str(uuid4()), annotation_id, timeframe, str(path), _now()))
        self.connection.commit()
        return str(path)

    def screenshots(self, annotation_id: str) -> list[dict[str, str]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT timeframe, image_path, created_at FROM annotation_screenshots WHERE annotation_id = ? ORDER BY timeframe", (annotation_id,))]

    def import_actual_trades(self, rows: list[dict[str, object]]) -> None:
        self.connection.executemany(
            "INSERT OR REPLACE INTO actual_manual_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(str(row["trade_id"]), str(row["symbol"]), int(row["entry_time"]), str(row["side"]),
              float(row["entry_price"]), float(row["stop_loss"]), float(row["take_profit"]),
              int(row["exit_time"]) if row.get("exit_time") else None, float(row["exit_price"]) if row.get("exit_price") else None,
              str(row.get("notes") or "")) for row in rows],
        ); self.connection.commit()

    def actual_trades(self, symbol: str | None = None) -> list[dict[str, object]]:
        query, args = "SELECT * FROM actual_manual_trades", ()
        if symbol: query += " WHERE symbol = ?"; args = (symbol,)
        return [dict(row) for row in self.connection.execute(query, args)]

    def save_bot_review(self, review: BotCandidateReview) -> BotCandidateReview:
        self.connection.execute("INSERT OR REPLACE INTO bot_candidate_reviews VALUES (?, ?, ?, ?, ?)",
                                (review.review_id, review.annotation_id, json.dumps(review.candidate), review.verdict.value, review.created_at.isoformat()))
        self.connection.commit(); return review


def _session(row: sqlite3.Row) -> ReplaySession:
    return ReplaySession.model_validate(dict(row))
