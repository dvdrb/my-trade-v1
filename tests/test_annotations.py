from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.annotation.models import (HumanAnnotation, HumanSide, MarketState, PricePoint, ReplaySession,
                                   SimulatedTrade, Structure, StructureRole, TrendLine, TriangleGeometry)
from app.annotation.replay import step_trade, visible_candles
from app.annotation.repository import AnnotationRepository
from app.core.types import Candle
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository
from app.annotation.server import create_app
from fastapi.testclient import TestClient


def candle(time: int, low: float = 90, high: float = 110) -> Candle:
    return Candle("BTC", "15m", time, 100, high, low, 100)


def structure() -> Structure:
    return Structure(timeframe="15m", role=StructureRole.ENTRY, geometry=TriangleGeometry(
        upper_line=TrendLine(p1=PricePoint(timestamp=1, price=110), p2=PricePoint(timestamp=2, price=108)),
        lower_line=TrendLine(p1=PricePoint(timestamp=1, price=90), p2=PricePoint(timestamp=2, price=92))))


def test_visible_candles_never_leak_future_for_any_timeframe() -> None:
    for timeframe in ("15m", "1h", "4h"):
        candles = [Candle("BTC", timeframe, 1, 1, 2, 0.5, 1), Candle("BTC", timeframe, 2, 1, 2, 0.5, 1)]
        assert [c.open_time for c in visible_candles(candles, 1)] == [1]
    incomplete = Candle("BTC", "4h", 0, 1, 2, 0.5, 1, close_time=4)
    assert visible_candles([incomplete], 3) == []
    assert visible_candles([incomplete], 4) == [incomplete]


def test_annotation_coordinates_and_revisions_are_persisted(tmp_path) -> None:
    db = tmp_path / "annotations.sqlite3"; init_db(db); repository = AnnotationRepository(connect(db))
    session = repository.create_session(ReplaySession(symbol="BTC", started_at_market_time=2, replay_time=2))
    annotation = HumanAnnotation(session_id=session.session_id, symbol="BTC", decision_time=2,
                                 market_state=MarketState.VALID_TRIANGLE_NO_TRADE, structures=[structure()])
    repository.save_annotation(annotation)
    annotation.notes = "clear compression"; repository.save_annotation(annotation)
    restored = repository.annotations(session.session_id)[0]
    assert restored.structures[0].geometry.upper_line.p1.timestamp == 1
    assert restored.structures[0].geometry.upper_line.p1.price == 110
    assert len(repository.revisions(annotation.annotation_id)) == 1


def test_simulated_trade_is_conservative_and_intent_remains_unchanged() -> None:
    trade = {"status": "pending", "side": "long", "entry_price": 100, "stop_loss": 95, "take_profit": 110}
    result = step_trade(trade, candle(3, 94, 111))
    assert result["status"] == "stopped"
    assert result["realized_r"] == -1
    annotation = HumanAnnotation(session_id="s", symbol="BTC", decision_time=2, market_state=MarketState.TRADE,
                                 side=HumanSide.LONG, trade_plan={"entry_price": 100, "stop_loss": 95, "take_profit": 110})
    assert annotation.market_state == MarketState.TRADE


def test_trade_persistence_is_separate_from_annotation(tmp_path) -> None:
    db = tmp_path / "trade.sqlite3"; init_db(db); repository = AnnotationRepository(connect(db))
    session = repository.create_session(ReplaySession(symbol="BTC", started_at_market_time=2, replay_time=2))
    annotation = repository.save_annotation(HumanAnnotation(session_id=session.session_id, symbol="BTC", decision_time=2,
        market_state=MarketState.TRADE, side=HumanSide.LONG, trade_plan={"entry_price":100,"stop_loss":95,"take_profit":110}))
    trade = repository.save_trade(SimulatedTrade(annotation_id=annotation.annotation_id, session_id=session.session_id,
        symbol="BTC", side=HumanSide.LONG, entry_price=100, stop_loss=95, take_profit=110, created_at_market_time=2))
    assert repository.annotations()[0].annotation_id == annotation.annotation_id
    assert repository.trades()[0].simulated_trade_id == trade.simulated_trade_id


def test_api_replay_persistence_screenshots_and_trade_lifecycle(tmp_path) -> None:
    db = tmp_path / "api.sqlite3"; init_db(db)
    CandleRepository(connect(db)).insert_many([
        Candle("BTC", "15m", 1_000, 100, 101, 99, 100),
        Candle("BTC", "15m", 2_000, 100, 111, 99, 110),
        Candle("BTC", "15m", 3_000, 110, 111, 94, 95),
    ])
    client = TestClient(create_app(db)); session = client.post("/api/sessions", json={"symbol": "BTC", "start_time": 1_000}).json()
    session_id = session["session_id"]
    assert [item["open_time"] for item in client.get(f"/api/sessions/{session_id}/candles/15m").json()] == [1_000]
    payload = HumanAnnotation(session_id=session_id, symbol="BTC", decision_time=1_000, market_state=MarketState.TRADE,
        side=HumanSide.LONG, structures=[structure()], trade_plan={"entry_price": 100, "stop_loss": 95, "take_profit": 110}).model_dump(mode="json")
    saved = client.post("/api/annotations", json=payload); assert saved.status_code == 200
    annotation_id = saved.json()["annotation_id"]
    png = "data:image/png;base64,iVBORw0KGgo="
    assert client.post(f"/api/annotations/{annotation_id}/screenshots", json={"timeframe": "15m", "image_data_url": png}).status_code == 200
    assert client.get(f"/api/annotations/{annotation_id}/screenshots").json()[0]["timeframe"] == "15m"
    assert client.post("/api/trades", json={"annotation_id": annotation_id, "session_id": session_id, "symbol": "BTC", "side": "long", "entry_price": 100, "stop_loss": 95, "take_profit": 110, "created_at_market_time": 1_000}).status_code == 200
    client.post(f"/api/sessions/{session_id}/advance", json={"count": 1})
    assert client.get(f"/api/sessions/{session_id}/trades").json()[0]["status"] == "target"
    restarted = TestClient(create_app(db)).get(f"/api/sessions/{session_id}/annotations").json()[0]
    assert restarted["structures"][0]["geometry"]["upper_line"]["p1"] == {"timestamp": 1, "price": 110.0}


def test_api_rejects_future_annotation_coordinate(tmp_path) -> None:
    db = tmp_path / "future.sqlite3"; init_db(db); CandleRepository(connect(db)).insert_many([Candle("BTC", "15m", 1_000, 1, 2, 0.5, 1)])
    client = TestClient(create_app(db)); session = client.post("/api/sessions", json={"symbol": "BTC", "start_time": 1_000}).json()
    annotation = HumanAnnotation(session_id=session["session_id"], symbol="BTC", decision_time=1_000, market_state=MarketState.VALID_TRIANGLE_NO_TRADE, structures=[structure()]).model_dump(mode="json")
    annotation["structures"][0]["geometry"]["upper_line"]["p2"]["timestamp"] = 1_001
    assert client.post("/api/annotations", json=annotation).status_code == 422
    level_only = HumanAnnotation(session_id=session["session_id"], symbol="BTC", decision_time=1_000,
        market_state=MarketState.NO_STRUCTURE, levels=[{"timeframe": "15m", "kind": "support", "start": {"timestamp": 1_001, "price": 1}}]).model_dump(mode="json")
    assert client.post("/api/annotations", json=level_only).status_code == 422


def test_reconstruction_starts_before_the_real_trade_entry(tmp_path) -> None:
    db = tmp_path / "reconstruct.sqlite3"; init_db(db)
    CandleRepository(connect(db)).insert_many([Candle("BTC", "15m", 1_000, 1, 2, 0.5, 1), Candle("BTC", "15m", 2_000, 1, 2, 0.5, 1)])
    client = TestClient(create_app(db))
    session = client.post("/api/sessions", json={"symbol": "BTC", "start_time": 2_000, "mode": "reconstruct_real_trade"}).json()
    assert session["replay_time"] == 1_000


def test_export_freezes_annotation_trade_and_screenshot_batch(tmp_path) -> None:
    db = tmp_path / "export.sqlite3"; init_db(db); repository = AnnotationRepository(connect(db))
    session = repository.create_session(ReplaySession(symbol="BTC", started_at_market_time=2, replay_time=2))
    annotation = repository.save_annotation(HumanAnnotation(session_id=session.session_id, symbol="BTC", decision_time=2,
        market_state=MarketState.TRADE, side=HumanSide.LONG, structures=[structure()], trade_plan={"entry_price":100,"stop_loss":95,"take_profit":110}))
    repository.save_trade(SimulatedTrade(annotation_id=annotation.annotation_id, session_id=session.session_id, symbol="BTC", side=HumanSide.LONG,
        entry_price=100, stop_loss=95, take_profit=110, created_at_market_time=2))
    repository.save_screenshot(annotation.annotation_id, "15m", b"\x89PNG\r\n\x1a\n", tmp_path / "screenshots")
    output = tmp_path / "batches"
    subprocess.run([sys.executable, "scripts/export_human_ground_truth.py", "--db", str(db), "--output", str(output), "--batch", "batch_001"], cwd=Path(__file__).parents[1], check=True)
    batch = output / "batch_001"
    assert (batch / "screenshots" / annotation.annotation_id / "15m.png").is_file()
    assert "screenshots/" in (batch / "SHA256SUMS").read_text(encoding="utf-8")
    rerun = subprocess.run([sys.executable, "scripts/export_human_ground_truth.py", "--db", str(db), "--output", str(output), "--batch", "batch_001"], cwd=Path(__file__).parents[1], capture_output=True, text=True)
    assert rerun.returncode != 0
