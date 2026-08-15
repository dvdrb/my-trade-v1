from __future__ import annotations

from app.annotation.models import (HumanAnnotation, HumanSide, MarketState, PricePoint, ReplaySession,
                                   SimulatedTrade, Structure, StructureRole, TrendLine, TriangleGeometry)
from app.annotation.replay import step_trade, visible_candles
from app.annotation.repository import AnnotationRepository
from app.core.types import Candle
from app.data.db import connect, init_db


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
