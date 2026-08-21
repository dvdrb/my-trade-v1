from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.annotation.models import HumanAnnotation, HumanSide, LegacyTriangleGeometry, MarketState, PricePoint, ReplaySession, SimulatedTrade, Structure, StructureRole, TrendLine, TriangleGeometry
from app.annotation.replay import step_trade, visible_candles
from app.annotation.repository import AnnotationRepository
from app.annotation.research_range import human_research_bounds
from app.annotation.server import create_app
from app.core.types import Candle
from app.data.db import connect, init_db
from app.data.repositories import CandleRepository
from scripts.export_human_ground_truth import DEFAULT_HUMAN_REPLAY_DB


def candle(time: int, low: float = 90, high: float = 110) -> Candle:
    return Candle("BTC", "15m", time, 100, high, low, 100)


def structure(time: int = 1) -> Structure:
    start = max(0, time - 2)
    return Structure(timeframe="15m", role=StructureRole.ENTRY, geometry=TriangleGeometry(vertices=(
        PricePoint(timestamp=start, price=110), PricePoint(timestamp=start + 1, price=90),
        PricePoint(timestamp=start + 2, price=100),
    )))


def seeded_client(tmp_path: Path) -> tuple[TestClient, int]:
    db = tmp_path / "replay.sqlite3"; init_db(db)
    candles = [Candle("BTC", "15m", index * 1_000, 100, 101, 99, 100) for index in range(1_000)]
    candles += [Candle("BTC", "4h", index * 4_000, 100, 101, 99, 100) for index in range(300)]
    CandleRepository(connect(db)).insert_many(candles)
    return TestClient(create_app(db, research_bounds=(0, 900_000))), db


def create_session(client: TestClient, at: int = 800_000) -> dict[str, object]:
    response = client.post("/api/sessions", json={"symbol": "BTC", "start_time": at, "selection_mode": "chosen_date"})
    assert response.status_code == 200, response.text
    return response.json()


def annotation_payload(session: dict[str, object], state: MarketState = MarketState.VALID_TRIANGLE_NO_TRADE) -> dict[str, object]:
    time = int(session["replay_time"])
    values: dict[str, object] = {"session_id": session["session_id"], "symbol": "BTC", "decision_time": time, "market_state": state.value, "structures": [structure(time).model_dump(mode="json")]}
    if state == MarketState.TRADE:
        values |= {"side": "long", "trade_plan": {"entry_price": 100, "stop_loss": 95, "take_profit": 110}}
    return HumanAnnotation.model_validate(values).model_dump(mode="json")


def test_visible_candles_never_leak_incomplete_higher_timeframes() -> None:
    incomplete = Candle("BTC", "4h", 0, 1, 2, 0.5, 1, close_time=4)
    assert visible_candles([incomplete], 3) == []
    assert visible_candles([incomplete], 4) == [incomplete]


def test_canonical_human_research_bounds_are_training_only() -> None:
    start, end = human_research_bounds()
    assert start == 1_735_689_600_000  # 2025-01-01T00:00:00Z
    assert end == 1_766_361_600_000  # 2025-12-22T00:00:00Z, validation.start


def test_human_ground_truth_export_defaults_to_the_replay_database() -> None:
    assert DEFAULT_HUMAN_REPLAY_DB == "data/human_replay.sqlite3"


def test_replay_range_enforces_preroll_training_boundary_and_random_selection(tmp_path: Path) -> None:
    client, _ = seeded_client(tmp_path)
    replay_range = client.get("/api/replay-range/BTC").json()
    assert replay_range["earliest_valid"] >= 199 * 4_000
    assert client.post("/api/sessions", json={"symbol": "BTC", "start_time": 1_000, "selection_mode": "chosen_date"}).status_code == 422
    assert client.post("/api/sessions", json={"symbol": "BTC", "start_time": 950_000, "selection_mode": "chosen_date"}).status_code == 422
    random_session = client.post("/api/sessions", json={"symbol": "BTC", "selection_mode": "random"})
    assert random_session.status_code == 200
    assert replay_range["earliest_valid"] <= random_session.json()["replay_time"] <= replay_range["latest_valid"]


def test_candles_are_bounded_and_future_safe(tmp_path: Path) -> None:
    client, _ = seeded_client(tmp_path); session = create_session(client)
    candles = client.get(f"/api/sessions/{session['session_id']}/candles/15m").json()
    assert len(candles) == 500
    assert max(item["open_time"] for item in candles) <= session["replay_time"]


def test_commits_are_immutable_and_each_record_uses_a_new_annotation_id(tmp_path: Path) -> None:
    client, _ = seeded_client(tmp_path); session = create_session(client)
    first = annotation_payload(session)
    saved = client.post("/api/annotations", json=first); assert saved.status_code == 200
    assert client.post("/api/annotations", json=first).status_code == 409
    client.post(f"/api/sessions/{session['session_id']}/advance", json={"count": 1})
    current = client.get(f"/api/sessions/{session['session_id']}").json()
    second = annotation_payload(current)
    second["annotation_id"] = "independent-second-decision"
    assert client.post("/api/annotations", json=second).status_code == 200
    client.post(f"/api/sessions/{session['session_id']}/advance", json={"count": 1})
    later = client.get(f"/api/sessions/{session['session_id']}").json()
    third = annotation_payload(later)
    third["annotation_id"] = "independent-third-decision"
    assert client.post("/api/annotations", json=third).status_code == 200
    decisions = client.get(f"/api/sessions/{session['session_id']}/annotations").json()
    assert len(decisions) == 3
    assert len({item["annotation_id"] for item in decisions}) == 3
    assert decisions[0]["decision_time"] == session["replay_time"]


def test_state_invariants_and_directional_plans() -> None:
    with pytest.raises(ValueError, match="no_structure"):
        HumanAnnotation(session_id="s", symbol="BTC", decision_time=1, market_state=MarketState.NO_STRUCTURE, side=HumanSide.LONG)
    with pytest.raises(ValueError, match="require a structure"):
        HumanAnnotation(session_id="s", symbol="BTC", decision_time=1, market_state=MarketState.TRADE, side=HumanSide.LONG, trade_plan={"entry_price": 100, "stop_loss": 95, "take_profit": 110})
    with pytest.raises(ValueError, match="invalid for its selected direction"):
        HumanAnnotation(session_id="s", symbol="BTC", decision_time=1, market_state=MarketState.TRADE, side=HumanSide.LONG, structures=[structure()], trade_plan={"entry_price": 100, "stop_loss": 105, "take_profit": 110})


def test_human_triangle_serializes_three_vertices_and_legacy_lines_still_parse() -> None:
    canonical = structure(10)
    assert canonical.model_dump(mode="json")["geometry"] == {
        "vertices": [
            {"timestamp": 8, "price": 110.0}, {"timestamp": 9, "price": 90.0}, {"timestamp": 10, "price": 100.0},
        ],
        "snap_mode": "free",
    }
    legacy = Structure.model_validate({"timeframe": "15m", "role": "entry", "geometry": {
        "upper_line": {"p1": {"timestamp": 1, "price": 110}, "p2": {"timestamp": 3, "price": 100}},
        "lower_line": {"p1": {"timestamp": 1, "price": 90}, "p2": {"timestamp": 3, "price": 100}},
    }})
    assert isinstance(legacy.geometry, LegacyTriangleGeometry)


def test_projected_triangle_vertex_is_saved_without_exposing_future_candles(tmp_path: Path) -> None:
    client, db = seeded_client(tmp_path); session = create_session(client)
    payload = annotation_payload(session)
    vertices = payload["structures"][0]["geometry"]["vertices"]
    vertices[2]["timestamp"] = int(session["replay_time"]) + 15 * 60 * 1000
    saved = client.post("/api/annotations", json=payload)
    assert saved.status_code == 200, saved.text
    reloaded = AnnotationRepository(connect(db)).annotations()[0]
    assert reloaded.structures[0].geometry.model_dump(mode="json")["vertices"] == vertices
    candles = client.get(f"/api/sessions/{session['session_id']}/candles/15m").json()
    assert max(item["open_time"] for item in candles) <= session["replay_time"]


def test_record_failure_does_not_create_trade_and_screenshot_revisions_are_retained(tmp_path: Path) -> None:
    client, db = seeded_client(tmp_path); session = create_session(client)
    payload = annotation_payload(session, MarketState.TRADE)
    bad = client.post("/api/annotations/record", json={"annotation": payload, "screenshots": {}, "place_trade": True})
    assert bad.status_code == 422
    assert AnnotationRepository(connect(db)).trades() == []
    assert AnnotationRepository(connect(db)).annotations() == []
    png = "data:image/png;base64,iVBORw0KGgo="
    recorded = client.post("/api/annotations/record", json={"annotation": payload, "screenshots": {"4h": png, "1h": png, "15m": png}, "place_trade": True})
    assert recorded.status_code == 200, recorded.text
    repository = AnnotationRepository(connect(db))
    assert len(repository.trades()) == 1
    assert {item["timeframe"] for item in repository.screenshots(payload["annotation_id"])} == {"4h", "1h", "15m"}


def test_ambiguous_ohlc_is_not_silently_recorded_as_a_loss() -> None:
    trade = {"status": "pending", "side": "long", "entry_price": 100, "stop_loss": 95, "take_profit": 110}
    assert step_trade(trade, candle(3, 94, 111))["status"] == "ambiguous"
    open_trade = {"status": "open", "side": "short", "entry_price": 100, "stop_loss": 105, "take_profit": 90}
    assert step_trade(open_trade, candle(4, 89, 106))["status"] == "ambiguous"


def test_export_and_verify_batch_preserves_unique_annotations(tmp_path: Path) -> None:
    db = tmp_path / "export.sqlite3"; init_db(db); repository = AnnotationRepository(connect(db))
    session = repository.create_session(ReplaySession(symbol="BTC", started_at_market_time=2, replay_time=2))
    annotation = repository.save_annotation(HumanAnnotation(session_id=session.session_id, symbol="BTC", decision_time=2, market_state=MarketState.TRADE, side=HumanSide.LONG, structures=[structure()], trade_plan={"entry_price": 100, "stop_loss": 95, "take_profit": 110}))
    repository.save_screenshots(annotation.annotation_id, {"4h": b"png", "1h": b"png", "15m": b"png"}, tmp_path / "screenshots")
    output = tmp_path / "batches"
    root = Path(__file__).parents[1]
    subprocess.run([sys.executable, "scripts/export_human_ground_truth.py", "--db", str(db), "--output", str(output), "--batch", "batch_001"], cwd=root, check=True)
    subprocess.run([sys.executable, "scripts/verify_human_ground_truth_batch.py", str(output / "batch_001")], cwd=root, check=True)
    (output / "batch_001" / "screenshots" / annotation.annotation_id / "revision_001" / "1h.png").unlink()
    verify = subprocess.run([sys.executable, "scripts/verify_human_ground_truth_batch.py", str(output / "batch_001")], cwd=root, text=True, capture_output=True)
    assert verify.returncode != 0
    assert "canonical screenshots must be exactly" in verify.stderr
