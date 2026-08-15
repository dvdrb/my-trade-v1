from __future__ import annotations

import os
import base64
import csv
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.annotation.models import BotCandidateReview, HumanAnnotation, ReplaySession, ScreenshotRequest, SimulatedTrade
from app.annotation.replay import advance_time, step_trade, visible_candles
from app.annotation.repository import AnnotationRepository
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository
from app.config.settings import load_config
from app.core.types import Decision
from app.strategy.evaluator import evaluate
from app.strategy.pivots import detect_pivots
from app.strategy.triangle import detect_triangle


class SessionRequest(BaseModel):
    symbol: str
    start_time: int
    mode: str = "free_replay"


class AdvanceRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=1000)


class ManualExitRequest(BaseModel):
    price: float = Field(gt=0)
    timestamp: int = Field(ge=0)


class ActualTradesCsvRequest(BaseModel):
    csv_text: str


def create_app(db_path: str | Path = "data/bot.sqlite3") -> FastAPI:
    init_db(db_path)
    actual_csv = Path(db_path).parent / "human_ground_truth" / "actual_trades.csv"
    if actual_csv.exists():
        with actual_csv.open(encoding="utf-8", newline="") as file:
            AnnotationRepository(connect(db_path)).import_actual_trades(list(csv.DictReader(file)))
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

    @app.get("/api/sessions", response_model=list[ReplaySession])
    def sessions() -> list[ReplaySession]: return repos()[0].sessions()

    @app.post("/api/sessions", response_model=ReplaySession)
    def create_session(request: SessionRequest) -> ReplaySession:
        annotations, candles = repos()
        base = candles.all(request.symbol, "15m")
        if not base or request.start_time < base[0].open_time or request.start_time > base[-1].open_time:
            raise HTTPException(422, "start_time must be within locally stored 15m candle history")
        initial = max((candle for candle in base if candle.open_time <= request.start_time), key=lambda candle: candle.open_time)
        replay_time = initial.close_time if initial.close_time is not None else initial.open_time
        if request.mode == "reconstruct_real_trade":
            prior = [candle.open_time for candle in base if candle.open_time < request.start_time]
            if not prior:
                raise HTTPException(422, "there is no candle before this real trade entry")
            replay_time = prior[-1]
        return annotations.create_session(ReplaySession(symbol=request.symbol, started_at_market_time=replay_time,
                                                         replay_time=replay_time, mode=request.mode))

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
        for level in annotation.levels:
            for point in (level.start, level.end):
                if point is not None and point.timestamp > session.replay_time:
                    raise HTTPException(422, "level point is in the future")
        return repository.save_annotation(annotation)

    @app.post("/api/annotations/{annotation_id}/screenshots")
    def save_screenshot(annotation_id: str, screenshot: ScreenshotRequest) -> dict[str, str]:
        repository, _ = repos()
        if annotation_id not in {annotation.annotation_id for annotation in repository.annotations()}:
            raise HTTPException(404, "annotation not found")
        prefix, _, encoded = screenshot.image_data_url.partition(",")
        if not prefix.startswith("data:image/png") or not encoded:
            raise HTTPException(422, "screenshot must be a PNG data URL")
        try: image = base64.b64decode(encoded, validate=True)
        except ValueError as error: raise HTTPException(422, "invalid screenshot data") from error
        if len(image) > 15_000_000: raise HTTPException(422, "screenshot is too large")
        path = repository.save_screenshot(annotation_id, screenshot.timeframe, image, Path(db_path).parent / "human_ground_truth" / "screenshots")
        return {"image_path": path}

    @app.get("/api/annotations/{annotation_id}/screenshots")
    def screenshots(annotation_id: str) -> list[dict[str, str]]: return repos()[0].screenshots(annotation_id)

    @app.post("/api/trades", response_model=SimulatedTrade)
    def place_trade(trade: SimulatedTrade) -> SimulatedTrade:
        repository, _ = repos(); session = repository.get_session(trade.session_id)
        if session is None or trade.created_at_market_time > session.replay_time: raise HTTPException(422, "trade creation must be at current replay time")
        annotations = {annotation.annotation_id: annotation for annotation in repository.annotations(trade.session_id)}
        if trade.annotation_id not in annotations: raise HTTPException(422, "trade must belong to a saved annotation")
        invalid = (trade.side.value == "long" and (trade.stop_loss >= trade.entry_price or trade.take_profit <= trade.entry_price)) or (trade.side.value == "short" and (trade.stop_loss <= trade.entry_price or trade.take_profit >= trade.entry_price))
        if invalid: raise HTTPException(422, "trade plan is invalid for its selected direction")
        return repository.save_trade(trade)

    @app.get("/api/sessions/{session_id}/trades", response_model=list[SimulatedTrade])
    def trades(session_id: str) -> list[SimulatedTrade]: return repos()[0].trades(session_id)

    @app.post("/api/trades/{trade_id}/manual-exit", response_model=SimulatedTrade)
    def manual_exit(trade_id: str, request: ManualExitRequest) -> SimulatedTrade:
        repository, _ = repos(); trade = next((item for item in repository.trades() if item.simulated_trade_id == trade_id), None)
        if trade is None: raise HTTPException(404, "trade not found")
        session = repository.get_session(trade.session_id)
        if session is None or request.timestamp > session.replay_time: raise HTTPException(422, "manual exit cannot use future time")
        if trade.status != "open": raise HTTPException(422, "only open trades can be manually exited")
        risk = abs(trade.entry_price - trade.stop_loss); realized = (request.price - trade.entry_price) / risk
        if trade.side.value == "short": realized *= -1
        completed = trade.model_copy(update={"status": "manual_exit", "exit_time": request.timestamp, "exit_price": request.price, "realized_r": realized})
        return repository.save_trade(completed)

    @app.post("/api/actual-trades/import")
    def import_actual_trades(request: ActualTradesCsvRequest) -> dict[str, int]:
        rows = list(csv.DictReader(io.StringIO(request.csv_text)))
        required = {"trade_id", "symbol", "entry_time", "side", "entry_price", "stop_loss", "take_profit"}
        if not rows or not required.issubset(rows[0]): raise HTTPException(422, "CSV does not have the required actual-trade schema")
        repos()[0].import_actual_trades(rows); return {"imported": len(rows)}

    @app.get("/api/actual-trades")
    def actual_trades(symbol: str | None = None) -> list[dict[str, object]]: return repos()[0].actual_trades(symbol)

    @app.get("/api/bot-candidates")
    def bot_candidates(symbol: str, limit: int = 100) -> list[dict[str, object]]:
        _, candle_repo = repos(); candles = candle_repo.all(symbol, "15m"); config = load_config()
        results: list[dict[str, object]] = []
        minimum = config.market.warmup_candles
        for index in range(minimum, len(candles)):
            signal = evaluate(candles[: index + 1], config, symbol=symbol, timeframe="15m")
            if signal.decision == Decision.ACCEPTED:
                pivots = detect_pivots(candles[: index + 1], config.strategy.pivots.left, config.strategy.pivots.right)
                triangle = detect_triangle(pivots, index, config.strategy.triangle.min_candles, config.strategy.triangle.max_candles, config.strategy.triangle.flat_tolerance_percent)
                geometry = None if triangle is None else {"upper_line": {"p1": {"timestamp": triangle.start_time, "price": triangle.upper_start}, "p2": {"timestamp": triangle.end_time, "price": triangle.upper_end}}, "lower_line": {"p1": {"timestamp": triangle.start_time, "price": triangle.lower_start}, "p2": {"timestamp": triangle.end_time, "price": triangle.lower_end}}}
                results.append({"symbol": symbol, "decision_time": candles[index].open_time, "decision": signal.decision.value,
                                "side": signal.side.value if signal.side else None, "entry_price": signal.entry_price,
                                "stop_loss": signal.stop_loss, "take_profit": signal.take_profit, "triangle_type": signal.triangle_type,
                                "strategy_version": signal.strategy_version, "bot_geometry": geometry})
                if len(results) >= limit: break
        return results

    @app.post("/api/bot-reviews", response_model=BotCandidateReview)
    def save_bot_review(review: BotCandidateReview) -> BotCandidateReview:
        if review.annotation_id not in {item.annotation_id for item in repos()[0].annotations()}:
            raise HTTPException(422, "bot review must reference a saved human annotation")
        return repos()[0].save_bot_review(review)

    ui_dist = Path(__file__).resolve().parents[2] / "ui" / "annotator" / "dist"
    if ui_dist.is_dir(): app.mount("/", StaticFiles(directory=ui_dist, html=True), name="ui")
    return app


app = create_app(os.getenv("ANNOTATOR_DB", "data/bot.sqlite3"))
