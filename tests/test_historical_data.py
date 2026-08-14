from __future__ import annotations

import pytest

from app.core.types import Candle
from app.data.db import connect, init_db
from app.data.historical import derive_timeframe, validate_candles, verify_api_overlap
from app.data.repositories import CandleRepository


def _candle(symbol: str, open_time: int, price: float) -> Candle:
    return Candle(symbol, "15m", open_time, price, price + 2, price - 1, price + 1, 3, open_time + 900_000)


def test_derivation_uses_only_complete_utc_aligned_15m_buckets() -> None:
    source = [_candle("BTC", index * 900_000, 100 + index) for index in range(16)]
    hourly = derive_timeframe(source, "1h")
    four_hour = derive_timeframe(source, "4h")
    assert [(item.open_time, item.open, item.high, item.low, item.close, item.volume) for item in hourly] == [
        (0, 100, 105, 99, 104, 12),
        (3_600_000, 104, 109, 103, 108, 12),
        (7_200_000, 108, 113, 107, 112, 12),
        (10_800_000, 112, 117, 111, 116, 12),
    ]
    assert [(item.open_time, item.open, item.high, item.low, item.close, item.volume) for item in four_hour] == [
        (0, 100, 117, 99, 116, 48)
    ]


def test_derivation_drops_partial_buckets_and_integrity_reports_gaps() -> None:
    source = [_candle("BTC", index * 900_000, 100 + index) for index in (0, 1, 3, 4, 5, 6, 7)]
    integrity = validate_candles(source, "15m")
    assert integrity[0].gaps == 1
    hourly = derive_timeframe(source, "1h")
    assert [(item.open_time, item.open, item.high, item.low, item.close) for item in hourly] == [(3_600_000, 104, 109, 103, 108)]


def test_api_overlap_requires_enough_price_identical_candles() -> None:
    source = [_candle("BTC", index * 900_000, 100 + index) for index in range(3)]
    assert verify_api_overlap(source, lambda *_: source, sample_limit=3, minimum_overlap=3) == {"BTC": 3}
    wrong = [Candle("BTC", "15m", 0, 100, 102, 99, 999, 3, 900_000)]
    with pytest.raises(ValueError, match="mismatch"):
        verify_api_overlap(source, lambda *_: wrong, sample_limit=3, minimum_overlap=1)


def test_replace_timeframe_replaces_stale_candles_only_in_requested_scope(tmp_path) -> None:
    db_path = tmp_path / "bot.sqlite3"
    init_db(db_path)
    with connect(db_path) as connection:
        repository = CandleRepository(connection)
        repository.insert_many([_candle("BTC", 0, 1), Candle("BTC", "1h", 0, 1, 2, 0.5, 1.5)])
        repository.replace_timeframe("BTC", "15m", [_candle("BTC", 900_000, 2)])
        assert [item.open_time for item in repository.all("BTC", "15m")] == [900_000]
        assert len(repository.all("BTC", "1h")) == 1
