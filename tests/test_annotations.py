from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.annotation.models import HumanAnnotation, HumanSide, HumanTrendline, LegacyTriangleGeometry, MarketState, PricePoint, ReplaySession, SimulatedTrade, StrongPoint, Structure, StructureRole, TrendLine, TriangleGeometry
from app.annotation.replay import candle_knowledge_time, step_trade, visible_candles
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
    candles += [Candle("BTC", "1h", index * 1_000, 100, 101, 99, 100) for index in range(1_000)]
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


def test_v1_and_v2_annotations_remain_read_compatible() -> None:
    for schema_version in ("human-ground-truth-v1", "human-ground-truth-v2"):
        annotation = HumanAnnotation.model_validate({
            "schema_version": schema_version,
            "session_id": "old-session",
            "symbol": "BTC",
            "decision_time": 3,
            "market_state": "valid_triangle_no_trade",
            "structures": [structure(3).model_dump(mode="json")],
        })
        assert annotation.schema_version == schema_version
        assert annotation.trendlines == []
        assert annotation.strong_points == []


def test_replay_range_enforces_preroll_training_boundary_and_random_selection(tmp_path: Path) -> None:
    client, _ = seeded_client(tmp_path)
    replay_range = client.get("/api/replay-range/BTC").json()
    assert replay_range["earliest_valid"] >= 199 * 4_000
    assert client.post("/api/sessions", json={"symbol": "BTC", "start_time": 1_000, "selection_mode": "chosen_date"}).status_code == 422
    late = client.post("/api/sessions", json={"symbol": "BTC", "start_time": 950_000, "selection_mode": "chosen_date"})
    assert late.status_code == 200
    assert late.json()["replay_time"] == replay_range["latest_valid"]
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


def test_v3_trendlines_and_strong_points_round_trip_with_projection_rules(tmp_path: Path) -> None:
    client, db = seeded_client(tmp_path); session = create_session(client)
    time = int(session["replay_time"])
    payload = annotation_payload(session)
    payload["trendlines"] = [{"trendline_id": "line", "timeframe": "15m", "p1": {"timestamp": time - 1_000, "price": 99}, "p2": {"timestamp": time + 3_000, "price": 101}, "snap_mode": "weak"}]
    payload["strong_points"] = [{"strong_point_id": "point", "timeframe": "1h", "point": {"timestamp": time, "price": 100}, "snap_mode": "strong"}]
    saved = client.post("/api/annotations", json=payload)
    assert saved.status_code == 200, saved.text
    annotation = AnnotationRepository(connect(db)).annotations()[0]
    assert annotation.schema_version == "human-ground-truth-v3"
    assert annotation.trendlines[0].p2.timestamp == time + 3_000
    assert annotation.strong_points[0].point.price == 100
    payload["annotation_id"] = "future-point"
    payload["strong_points"][0]["point"]["timestamp"] = time + 1
    assert client.post("/api/annotations", json=payload).status_code == 422


def test_v3_human_drawing_models_reject_invalid_geometry() -> None:
    point = PricePoint(timestamp=1, price=100)
    with pytest.raises(ValueError):
        HumanTrendline(timeframe="15m", p1=point, p2=point)
    assert StrongPoint(timeframe="4h", point=point, snap_mode="free").point == point


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
    annotation = repository.save_annotation(HumanAnnotation(session_id=session.session_id, symbol="BTC", decision_time=2, market_state=MarketState.TRADE, side=HumanSide.LONG, structures=[structure()], trendlines=[HumanTrendline(trendline_id="line", timeframe="15m", p1=PricePoint(timestamp=1, price=99), p2=PricePoint(timestamp=3, price=101))], strong_points=[StrongPoint(strong_point_id="point", timeframe="1h", point=PricePoint(timestamp=2, price=100))], trade_plan={"entry_price": 100, "stop_loss": 95, "take_profit": 110}))
    repository.save_trade(SimulatedTrade(annotation_id=annotation.annotation_id, session_id=session.session_id, symbol="BTC", side=HumanSide.LONG, entry_price=100, stop_loss=95, take_profit=110, created_at_market_time=2))
    repository.save_screenshots(annotation.annotation_id, {"4h": b"png", "1h": b"png", "15m": b"png"}, tmp_path / "screenshots")
    output = tmp_path / "batches"
    root = Path(__file__).parents[1]
    subprocess.run([sys.executable, "scripts/export_human_ground_truth.py", "--db", str(db), "--output", str(output), "--batch", "batch_001"], cwd=root, check=True)
    subprocess.run([sys.executable, "scripts/verify_human_ground_truth_batch.py", str(output / "batch_001")], cwd=root, check=True)
    exported = HumanAnnotation.model_validate_json((output / "batch_001" / "annotations.jsonl").read_text())
    assert exported.trendlines[0].trendline_id == "line"
    assert exported.strong_points[0].strong_point_id == "point"
    (output / "batch_001" / "screenshots" / annotation.annotation_id / "revision_001" / "1h.png").unlink()
    verify = subprocess.run([sys.executable, "scripts/verify_human_ground_truth_batch.py", str(output / "batch_001")], cwd=root, text=True, capture_output=True)
    assert verify.returncode != 0
    assert "canonical screenshots must be exactly" in verify.stderr


def exact_time_client(tmp_path: Path) -> tuple[TestClient, list[Candle]]:
    db = tmp_path / "exact.sqlite3"; init_db(db)
    ten_am = 1_735_724_000_000  # 2025-01-01T10:00:00Z
    fifteen = 15 * 60_000
    base = [Candle("BTC", "15m", ten_am + index * fifteen, 100, 110, 90, 100, close_time=ten_am + (index + 1) * fifteen) for index in range(50)]
    four_hours = 4 * 60 * 60_000
    four = [Candle("BTC", "4h", ten_am - (200 - index) * four_hours, 100, 110, 90, 100, close_time=ten_am - (199 - index) * four_hours) for index in range(200)]
    four.append(Candle("BTC", "4h", ten_am, 100, 110, 90, 100, close_time=ten_am + four_hours))
    CandleRepository(connect(db)).insert_many([*base, *four])
    return TestClient(create_app(db, research_bounds=(ten_am, ten_am + 50 * fifteen))), base


def test_chosen_replay_resolves_to_closed_15m_knowledge_time(tmp_path: Path) -> None:
    client, base = exact_time_client(tmp_path)
    ten_fifteen = candle_knowledge_time(base[0])
    assert client.post("/api/sessions", json={"symbol": "BTC", "start_time": ten_fifteen, "selection_mode": "chosen_date"}).json()["replay_time"] == ten_fifteen
    assert client.post("/api/sessions", json={"symbol": "BTC", "start_time": ten_fifteen + 7 * 60_000, "selection_mode": "chosen_date"}).json()["replay_time"] == ten_fifteen
    assert client.post("/api/sessions", json={"symbol": "BTC", "start_time": candle_knowledge_time(base[1]), "selection_mode": "chosen_date"}).json()["replay_time"] == candle_knowledge_time(base[1])


def test_random_replay_preserves_selected_candidate_and_range_latest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, base = exact_time_client(tmp_path)
    import app.annotation.research_range as ranges
    monkeypatch.setattr(ranges.random, "choice", lambda candidates: candle_knowledge_time(base[2]))
    interval = client.get("/api/replay-range/BTC").json()
    random_session = client.post("/api/sessions", json={"symbol": "BTC", "selection_mode": "random"}).json()
    assert random_session["replay_time"] == candle_knowledge_time(base[2])
    latest = client.post("/api/sessions", json={"symbol": "BTC", "start_time": 9_999_999_999_999, "selection_mode": "chosen_date"}).json()
    assert latest["replay_time"] == interval["latest_valid"]


def test_advance_steps_only_newly_known_candle_and_never_moves_back(tmp_path: Path) -> None:
    client, base = exact_time_client(tmp_path)
    session = client.post("/api/sessions", json={"symbol": "BTC", "start_time": candle_knowledge_time(base[0]), "selection_mode": "chosen_date"}).json()
    repository = AnnotationRepository(connect(tmp_path / "exact.sqlite3"))
    trade = SimulatedTrade(annotation_id="a", session_id=session["session_id"], symbol="BTC", side=HumanSide.LONG, entry_price=100, stop_loss=80, take_profit=120, created_at_market_time=session["replay_time"])
    repository.connection.execute("INSERT INTO human_annotations VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("a", session["session_id"], "BTC", session["replay_time"], "human-ground-truth-v3", annotation_payload(session, MarketState.TRADE).__class__ and HumanAnnotation.model_validate(annotation_payload(session, MarketState.TRADE)).model_copy(update={"annotation_id": "a"}).model_dump_json(), "now", "now")); repository.connection.commit()
    repository.save_trade(trade)
    advanced = client.post(f"/api/sessions/{session['session_id']}/advance", json={"count": 1}).json()
    stepped = AnnotationRepository(connect(tmp_path / "exact.sqlite3")).trades(session["session_id"])[0]
    assert advanced["replay_time"] == candle_knowledge_time(base[1])
    assert stepped.status == "open" and stepped.entry_time == candle_knowledge_time(base[1])
    again = client.post(f"/api/sessions/{session['session_id']}/advance", json={"count": 1000}).json()
    assert again["replay_time"] >= advanced["replay_time"]


def test_trade_lifecycle_and_ohlc_times_use_knowledge_time() -> None:
    closed = Candle("BTC", "15m", 10_000, 100, 110, 90, 100, close_time=11_000)
    assert step_trade({"status": "pending", "side": "long", "entry_price": 100, "stop_loss": 85, "take_profit": 120}, closed)["entry_time"] == 11_000
    assert step_trade({"status": "open", "side": "long", "entry_price": 100, "stop_loss": 85, "take_profit": 105}, closed)["exit_time"] == 11_000
    assert step_trade({"status": "pending", "side": "long", "entry_price": 100, "stop_loss": 95, "take_profit": 110}, closed)["status"] == "ambiguous"
    assert step_trade({"status": "open", "side": "long", "entry_price": 100, "stop_loss": 95, "take_profit": 110}, Candle("BTC", "15m", 1, 100, 105, 94, 100, close_time=2))["status"] == "stopped"
    assert step_trade({"status": "open", "side": "long", "entry_price": 100, "stop_loss": 90, "take_profit": 105}, Candle("BTC", "15m", 1, 100, 106, 96, 100, close_time=2))["status"] == "target"


def test_strong_point_must_be_a_visible_candle_open_but_projection_remains_legal(tmp_path: Path) -> None:
    client, base = exact_time_client(tmp_path)
    session = client.post("/api/sessions", json={"symbol": "BTC", "start_time": candle_knowledge_time(base[0]), "selection_mode": "chosen_date"}).json()
    payload = annotation_payload(session)
    payload["structures"][0]["geometry"]["vertices"][2]["timestamp"] = session["replay_time"] + 9_999
    payload["strong_points"] = [{"strong_point_id": "hidden", "timeframe": "15m", "point": {"timestamp": base[1].open_time, "price": 100}, "snap_mode": "free"}]
    assert client.post("/api/annotations", json=payload).status_code == 422
    payload["strong_points"][0]["point"]["timestamp"] = base[0].open_time
    assert client.post("/api/annotations", json=payload).status_code == 200
    payload["annotation_id"] = "hidden-4h"
    payload["strong_points"][0] = {"strong_point_id": "hidden-4h", "timeframe": "4h", "point": {"timestamp": base[0].open_time, "price": 100}, "snap_mode": "free"}
    assert client.post("/api/annotations", json=payload).status_code == 422


def test_schema_version_is_closed() -> None:
    with pytest.raises(ValueError):
        HumanAnnotation(session_id="s", symbol="BTC", decision_time=1, market_state=MarketState.NO_STRUCTURE, schema_version="anything")


def test_export_includes_only_free_replay_annotations_and_trades(tmp_path: Path) -> None:
    db = tmp_path / "modes.sqlite3"; init_db(db); repository = AnnotationRepository(connect(db))
    sessions = [repository.create_session(ReplaySession(symbol="BTC", started_at_market_time=2, replay_time=2, mode=mode)) for mode in ("free_replay", "reconstruct_real_trade", "review_bot_candidate")]
    annotations: list[HumanAnnotation] = []
    for index, session in enumerate(sessions):
        annotation = repository.save_annotation(HumanAnnotation(annotation_id=f"annotation-{index}", session_id=session.session_id, symbol="BTC", decision_time=2, market_state=MarketState.TRADE, side=HumanSide.LONG, structures=[structure()], trade_plan={"entry_price": 100, "stop_loss": 95, "take_profit": 110}))
        repository.save_trade(SimulatedTrade(annotation_id=annotation.annotation_id, session_id=session.session_id, symbol="BTC", side=HumanSide.LONG, entry_price=100, stop_loss=95, take_profit=110, created_at_market_time=2))
        annotations.append(annotation)
    output = tmp_path / "batches"; root = Path(__file__).parents[1]
    subprocess.run([sys.executable, "scripts/export_human_ground_truth.py", "--db", str(db), "--output", str(output), "--batch", "batch_001"], cwd=root, check=True)
    exported = [HumanAnnotation.model_validate_json(line) for line in (output / "batch_001" / "annotations.jsonl").read_text().splitlines()]
    manifest = json.loads((output / "batch_001" / "manifest.json").read_text())
    assert [item.annotation_id for item in exported] == [annotations[0].annotation_id]
    assert manifest["included_session_modes"] == ["free_replay"]
    assert manifest["excluded_annotation_count_by_session_mode"] == {"reconstruct_real_trade": 1, "review_bot_candidate": 1}


def test_manual_exit_uses_current_replay_time_and_price(tmp_path: Path) -> None:
    client, db = seeded_client(tmp_path); session = create_session(client)
    repository = AnnotationRepository(connect(db))
    annotation = repository.save_annotation(HumanAnnotation.model_validate(annotation_payload(session, MarketState.TRADE)))
    trade = repository.save_trade(SimulatedTrade(annotation_id=annotation.annotation_id, session_id=session["session_id"], symbol="BTC", side=HumanSide.LONG, entry_price=100, stop_loss=95, take_profit=110, created_at_market_time=session["replay_time"], status="open", entry_time=session["replay_time"]))
    response = client.post(f"/api/trades/{trade.simulated_trade_id}/manual-exit", json={"price": 101, "timestamp": session["replay_time"]})
    assert response.status_code == 200
    assert response.json()["status"] == "manual_exit"
    assert response.json()["exit_time"] == session["replay_time"]
    assert response.json()["exit_price"] == 101
