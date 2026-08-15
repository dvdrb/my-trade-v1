from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.annotation.models import HumanAnnotation, ReplaySession, SimulatedTrade
from app.annotation.replay import advance_time, step_trade, visible_candles
from app.annotation.repository import AnnotationRepository
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository


class SessionRequest(BaseModel):
    symbol: str
    start_time: int
    mode: str = "free_replay"


class AdvanceRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=1000)


def create_app(db_path: str | Path = "data/bot.sqlite3") -> FastAPI:
    init_db(db_path)
    app = FastAPI(title="Human Trading Workstation", version="1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])

    def repos() -> tuple[AnnotationRepository, CandleRepository]:
        connection = connect(db_path)
        return AnnotationRepository(connection), CandleRepository(connection)

    @app.get("/api/health")
    def health() -> dict[str, str]: return {"status": "ok"}

    @app.get("/api/markets")
    def markets() -> list[dict[str, object]]:
        connection = connect(db_path)
        rows = connection.execute("SELECT symbol, timeframe, MIN(open_time) start_time, MAX(open_time) end_time, COUNT(*) count FROM candles WHERE timeframe IN ('15m','1h','4h') GROUP BY symbol, timeframe").fetchall()
        return [dict(row) for row in rows]

    @app.post("/api/sessions", response_model=ReplaySession)
    def create_session(request: SessionRequest) -> ReplaySession:
        annotations, candles = repos()
        base = candles.all(request.symbol, "15m")
        if not base or request.start_time < base[0].open_time or request.start_time > base[-1].open_time:
            raise HTTPException(422, "start_time must be within locally stored 15m candle history")
        return annotations.create_session(ReplaySession(symbol=request.symbol, started_at_market_time=request.start_time,
                                                         replay_time=request.start_time, mode=request.mode))

    @app.get("/api/sessions/{session_id}", response_model=ReplaySession)
    def session(session_id: str) -> ReplaySession:
        session = repos()[0].get_session(session_id)
        if session is None: raise HTTPException(404, "session not found")
        return session

    @app.post("/api/sessions/{session_id}/advance", response_model=ReplaySession)
    def advance(session_id: str, request: AdvanceRequest) -> ReplaySession:
        annotations, candles = repos(); session = annotations.get_session(session_id)
        if session is None: raise HTTPException(404, "session not found")
        all_candles = candles.all(session.symbol, "15m")
        new_time = advance_time(all_candles, session.replay_time, request.count)
        for trade in annotations.trades(session_id):
            if trade.status in {"pending", "open"}:
                state = trade.model_dump()
                for candle in (c for c in all_candles if session.replay_time < c.open_time <= new_time):
                    state = step_trade(state, candle)
                    if state["status"] not in {"pending", "open"}: break
                annotations.save_trade(SimulatedTrade.model_validate(state))
        return annotations.update_session_time(session_id, new_time)

    @app.get("/api/sessions/{session_id}/candles/{timeframe}")
    def candles_at_time(session_id: str, timeframe: str) -> list[dict[str, object]]:
        annotations, candle_repo = repos(); session = annotations.get_session(session_id)
        if session is None: raise HTTPException(404, "session not found")
        if timeframe not in {"15m", "1h", "4h"}: raise HTTPException(422, "unsupported timeframe")
        # The backend is the security boundary: no frontend query can obtain future candles.
        return [candle.__dict__ for candle in visible_candles(candle_repo.all(session.symbol, timeframe), session.replay_time)]

    @app.get("/api/sessions/{session_id}/annotations", response_model=list[HumanAnnotation])
    def annotations_for_session(session_id: str) -> list[HumanAnnotation]: return repos()[0].annotations(session_id)

    @app.post("/api/annotations", response_model=HumanAnnotation)
    def save_annotation(annotation: HumanAnnotation) -> HumanAnnotation:
        repository, _ = repos(); session = repository.get_session(annotation.session_id)
        if session is None: raise HTTPException(404, "session not found")
        if annotation.symbol != session.symbol or annotation.decision_time > session.replay_time:
            raise HTTPException(422, "annotations cannot reference a different symbol or future replay time")
        for structure in annotation.structures:
            for point in (structure.geometry.upper_line.p1, structure.geometry.upper_line.p2, structure.geometry.lower_line.p1, structure.geometry.lower_line.p2):
                if point.timestamp > session.replay_time: raise HTTPException(422, "structure point is in the future")
        return repository.save_annotation(annotation)

    @app.post("/api/trades", response_model=SimulatedTrade)
    def place_trade(trade: SimulatedTrade) -> SimulatedTrade:
        repository, _ = repos(); session = repository.get_session(trade.session_id)
        if session is None or trade.created_at_market_time > session.replay_time: raise HTTPException(422, "trade creation must be at current replay time")
        annotations = {annotation.annotation_id: annotation for annotation in repository.annotations(trade.session_id)}
        if trade.annotation_id not in annotations: raise HTTPException(422, "trade must belong to a saved annotation")
        return repository.save_trade(trade)

    @app.get("/api/sessions/{session_id}/trades", response_model=list[SimulatedTrade])
    def trades(session_id: str) -> list[SimulatedTrade]: return repos()[0].trades(session_id)

    ui_dist = Path(__file__).resolve().parents[2] / "ui" / "annotator" / "dist"
    if ui_dist.is_dir(): app.mount("/", StaticFiles(directory=ui_dist, html=True), name="ui")
    return app


app = create_app(os.getenv("ANNOTATOR_DB", "data/bot.sqlite3"))
