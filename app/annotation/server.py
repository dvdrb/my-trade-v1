from __future__ import annotations

import os
import base64
import csv
import io
import shutil
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.annotation.models import BotCandidateReview, CommitRequest, HumanAnnotation, ReplaySession, ScreenshotRequest, SimulatedTrade, TriangleGeometry
from app.annotation.replay import advance_time, step_trade, visible_candles
from app.annotation.research_range import allowed_replay_range, choose_random_replay, human_research_bounds
from app.annotation.repository import AnnotationRepository
from app.annotation.triangle_adapter import geometry_points
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository
from app.config.settings import load_config
from app.core.types import Decision
from app.strategy.evaluator import evaluate
from app.strategy.pivots import detect_pivots
from app.strategy.triangle import detect_triangle


class SessionRequest(BaseModel):
    symbol: str
    start_time: int | None = None
    mode: Literal["free_replay", "reconstruct_real_trade", "review_bot_candidate"] = "free_replay"
    selection_mode: Literal["random", "chosen_date", "reconstruct", "bot_review"] = "chosen_date"


class AdvanceRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=1000)


class ManualExitRequest(BaseModel):
    price: float = Field(gt=0)
    timestamp: int = Field(ge=0)


class ActualTradesCsvRequest(BaseModel):
    csv_text: str


def create_app(db_path: str | Path = "data/bot.sqlite3", *, research_periods_path: str | Path = "app/config/research_periods.yaml", research_bounds: tuple[int, int] | None = None) -> FastAPI:
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

    def replay_range(symbol: str):
        _, candles = repos()
        start, end = research_bounds or human_research_bounds(research_periods_path)
        try:
            return allowed_replay_range(candles.all(symbol, "15m"), candles.all(symbol, "4h"), research_start=start, research_end=end)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    def validate_annotation(annotation: HumanAnnotation, session: ReplaySession) -> None:
        if annotation.symbol != session.symbol or annotation.decision_time != session.replay_time:
            raise HTTPException(422, "annotation decision time must be the current replay time for its session")
        for structure in annotation.structures:
            # A v2 triangle vertex may deliberately project into the chart's blank
            # time axis. It is user-created geometry, never a future observation.
            if isinstance(structure.geometry, TriangleGeometry):
                continue
            for point in geometry_points(structure.geometry):
                if point.timestamp > session.replay_time:
                    raise HTTPException(422, "structure point is in the future")
        # Human trendlines may project into the blank part of the chart. They are
        # trader-created geometry, not future market observations.
        for strong_point in annotation.strong_points:
            if strong_point.point.timestamp > session.replay_time:
                raise HTTPException(422, "strong point is in the future")
        for level in annotation.levels:
            for point in (level.start, level.end):
                if point is not None and point.timestamp > session.replay_time:
                    raise HTTPException(422, "level point is in the future")

    def decode_png(value: str) -> bytes:
        prefix, _, encoded = value.partition(",")
        if not prefix.startswith("data:image/png") or not encoded:
            raise HTTPException(422, "screenshot must be a PNG data URL")
        try:
            image = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise HTTPException(422, "invalid screenshot data") from error
        if len(image) > 15_000_000:
            raise HTTPException(422, "screenshot is too large")
        return image

    @app.get("/api/health")
    def health() -> dict[str, str]: return {"status": "ok"}

    @app.get("/api/markets")
    def markets() -> list[dict[str, object]]:
        connection = connect(db_path)
        symbols = [row["symbol"] for row in connection.execute("SELECT DISTINCT symbol FROM candles").fetchall()]
        result: list[dict[str, object]] = []
        for symbol in symbols:
            try:
                interval = replay_range(symbol)
            except HTTPException:
                continue
            result.append({"symbol": symbol, "earliest_valid": interval.earliest, "latest_valid": interval.latest})
        return result

    @app.get("/api/replay-range/{symbol}")
    def available_replay_range(symbol: str) -> dict[str, int]:
        interval = replay_range(symbol)
        return {"earliest_valid": interval.earliest, "latest_valid": interval.latest, "pre_roll_candles": interval.pre_roll_candles}

    @app.get("/api/sessions", response_model=list[ReplaySession])
    def sessions() -> list[ReplaySession]: return repos()[0].sessions()

    @app.post("/api/sessions", response_model=ReplaySession)
    def create_session(request: SessionRequest) -> ReplaySession:
        annotations, candles = repos()
        base = candles.all(request.symbol, "15m")
        if not base:
            raise HTTPException(422, "there is no locally stored 15m candle history for this market")
        interval = replay_range(request.symbol)
        if request.selection_mode == "random":
            selected = choose_random_replay(interval, base)
        else:
            if request.start_time is None:
                raise HTTPException(422, "choose a historical date/time or start a random replay")
            selected = request.start_time
        if selected < interval.earliest or selected > interval.latest:
            raise HTTPException(422, "selected time is outside the approved replay range or lacks required pre-roll")
        initial = max((candle for candle in base if candle.open_time <= selected), key=lambda candle: candle.open_time)
        replay_time = initial.close_time if initial.close_time is not None else initial.open_time
        if request.mode == "reconstruct_real_trade":
            prior = [candle.open_time for candle in base if candle.open_time < selected]
            if not prior:
                raise HTTPException(422, "there is no candle before this real trade entry")
            replay_time = prior[-1]
        return annotations.create_session(ReplaySession(symbol=request.symbol, started_at_market_time=replay_time,
                                                         replay_time=replay_time, mode=request.mode,
                                                         selection_mode=request.selection_mode,
                                                         pre_roll_candles=interval.pre_roll_candles))

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
        new_time = min(advance_time(all_candles, session.replay_time, request.count), replay_range(session.symbol).latest)
        for trade in annotations.trades(session_id):
            if trade.status in {"pending", "open"}:
                state = trade.model_dump()
                for candle in (c for c in all_candles if session.replay_time < c.open_time <= new_time):
                    state = step_trade(state, candle)
                    if state["status"] not in {"pending", "open"}: break
                annotations.save_trade(SimulatedTrade.model_validate(state))
        return annotations.update_session_time(session_id, new_time)

    @app.get("/api/sessions/{session_id}/candles/{timeframe}")
    def candles_at_time(session_id: str, timeframe: str, limit: int | None = None) -> list[dict[str, object]]:
        annotations, candle_repo = repos(); session = annotations.get_session(session_id)
        if session is None: raise HTTPException(404, "session not found")
        if timeframe not in {"15m", "1h", "4h"}: raise HTTPException(422, "unsupported timeframe")
        # The backend is the security boundary: no frontend query can obtain future candles.
        default_limit = {"4h": 250, "1h": 400, "15m": 500}[timeframe]
        capped_limit = min(limit or default_limit, 2_000)
        visible = visible_candles(candle_repo.all(session.symbol, timeframe), session.replay_time)
        return [candle.__dict__ for candle in visible[-capped_limit:]]

    @app.get("/api/sessions/{session_id}/annotations", response_model=list[HumanAnnotation])
    def annotations_for_session(session_id: str) -> list[HumanAnnotation]: return repos()[0].annotations(session_id)

    @app.post("/api/annotations", response_model=HumanAnnotation)
    def save_annotation(annotation: HumanAnnotation) -> HumanAnnotation:
        repository, _ = repos(); session = repository.get_session(annotation.session_id)
        if session is None: raise HTTPException(404, "session not found")
        validate_annotation(annotation, session)
        if any(item.annotation_id == annotation.annotation_id for item in repository.annotations()):
            raise HTTPException(409, "committed annotations are immutable; use the explicit revision endpoint")
        return repository.save_annotation(annotation)

    @app.put("/api/annotations/{annotation_id}", response_model=HumanAnnotation)
    def revise_annotation(annotation_id: str, annotation: HumanAnnotation) -> HumanAnnotation:
        repository, _ = repos()
        if annotation.annotation_id != annotation_id or annotation_id not in {item.annotation_id for item in repository.annotations()}:
            raise HTTPException(404, "annotation not found")
        session = repository.get_session(annotation.session_id)
        if session is None:
            raise HTTPException(404, "session not found")
        validate_annotation(annotation, session)
        return repository.save_annotation(annotation)

    @app.post("/api/annotations/record", response_model=HumanAnnotation)
    def record_annotation(request: CommitRequest) -> HumanAnnotation:
        repository, _ = repos()
        annotation = request.annotation
        session = repository.get_session(annotation.session_id)
        if session is None:
            raise HTTPException(404, "session not found")
        validate_annotation(annotation, session)
        if any(item.annotation_id == annotation.annotation_id for item in repository.annotations()):
            raise HTTPException(409, "committed annotations are immutable")
        if set(request.screenshots) != {"4h", "1h", "15m"}:
            raise HTTPException(422, "all three timeframe screenshots are required before recording")
        images = {timeframe: decode_png(image) for timeframe, image in request.screenshots.items()}
        saved = repository.save_annotation(annotation)
        try:
            repository.save_screenshots(saved.annotation_id, images, Path(db_path).parent / "human_ground_truth" / "screenshots")
            if request.place_trade:
                if saved.market_state.value != "trade" or saved.side is None or saved.trade_plan is None:
                    raise HTTPException(422, "a simulated trade requires a valid TRADE decision")
                repository.save_trade(SimulatedTrade(annotation_id=saved.annotation_id, session_id=saved.session_id, symbol=saved.symbol, side=saved.side, entry_price=saved.trade_plan.entry_price, stop_loss=saved.trade_plan.stop_loss, take_profit=saved.trade_plan.take_profit, created_at_market_time=session.replay_time))
        except Exception:
            # A failed record never places a trade, consumes an annotation ID, or clears the UI draft.
            repository.delete_annotation(saved.annotation_id)
            shutil.rmtree(Path(db_path).parent / "human_ground_truth" / "screenshots" / saved.annotation_id, ignore_errors=True)
            raise
        return saved

    @app.post("/api/annotations/{annotation_id}/screenshots")
    def save_screenshot(annotation_id: str, screenshot: ScreenshotRequest) -> dict[str, str]:
        repository, _ = repos()
        if annotation_id not in {annotation.annotation_id for annotation in repository.annotations()}:
            raise HTTPException(404, "annotation not found")
        image = decode_png(screenshot.image_data_url)
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
    def actual_trades(symbol: str | None = None) -> list[dict[str, object]]:
        rows = repos()[0].actual_trades(symbol)
        return [row for row in rows if replay_range(str(row["symbol"])).earliest <= int(row["entry_time"]) <= replay_range(str(row["symbol"])).latest]

    @app.get("/api/bot-candidates")
    def bot_candidates(symbol: str, limit: int = 100) -> list[dict[str, object]]:
        _, candle_repo = repos(); candles = candle_repo.all(symbol, "15m"); config = load_config(); interval = replay_range(symbol)
        results: list[dict[str, object]] = []
        minimum = config.market.warmup_candles
        for index in range(minimum, len(candles)):
            signal = evaluate(candles[: index + 1], config, symbol=symbol, timeframe="15m")
            decision_time = candles[index].open_time
            if signal.decision == Decision.ACCEPTED and interval.earliest <= decision_time <= interval.latest:
                pivots = detect_pivots(candles[: index + 1], config.strategy.pivots.left, config.strategy.pivots.right)
                triangle = detect_triangle(pivots, index, config.strategy.triangle.min_candles, config.strategy.triangle.max_candles, config.strategy.triangle.flat_tolerance_percent)
                geometry = None if triangle is None else {"upper_line": {"p1": {"timestamp": triangle.start_time, "price": triangle.upper_start}, "p2": {"timestamp": triangle.end_time, "price": triangle.upper_end}}, "lower_line": {"p1": {"timestamp": triangle.start_time, "price": triangle.lower_start}, "p2": {"timestamp": triangle.end_time, "price": triangle.lower_end}}}
                results.append({"symbol": symbol, "decision_time": decision_time, "decision": signal.decision.value,
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


app = create_app(os.getenv("ANNOTATOR_DB", "data/human_replay.sqlite3"))
