from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from app.annotation.models import HumanAnnotation, ReplaySession, SimulatedTrade


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


def _session(row: sqlite3.Row) -> ReplaySession:
    return ReplaySession.model_validate(dict(row))
