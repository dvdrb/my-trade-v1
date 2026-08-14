from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isclose
from typing import Callable, Iterable

from app.core.types import Candle
from app.exchange.hyperliquid_data import INTERVAL_MS


CANONICAL_TIMEFRAME = "15m"


@dataclass(frozen=True)
class CandleIntegrity:
    symbol: str
    timeframe: str
    candles: int
    gaps: int
    duplicate_open_times: int


def validate_candles(candles: Iterable[Candle], timeframe: str) -> list[CandleIntegrity]:
    """Validate chronological OHLC candles, returning per-symbol integrity facts.

    A gap is reported rather than filled: strategy research must never invent
    price action that was absent from the verified source.
    """
    if timeframe not in INTERVAL_MS:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    grouped: dict[str, list[Candle]] = defaultdict(list)
    for candle in candles:
        if candle.timeframe != timeframe:
            raise ValueError(f"expected {timeframe} candles, received {candle.timeframe}")
        if candle.open_time % INTERVAL_MS[timeframe] != 0:
            raise ValueError(f"{candle.symbol} candle is not aligned to {timeframe}: {candle.open_time}")
        if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0:
            raise ValueError(f"{candle.symbol} candle has non-positive OHLC at {candle.open_time}")
        if candle.low > min(candle.open, candle.close) or candle.high < max(candle.open, candle.close):
            raise ValueError(f"{candle.symbol} candle has invalid OHLC bounds at {candle.open_time}")
        if candle.volume < 0:
            raise ValueError(f"{candle.symbol} candle has negative volume at {candle.open_time}")
        if candle.close_time is not None and candle.close_time != candle.open_time + INTERVAL_MS[timeframe]:
            raise ValueError(f"{candle.symbol} candle has invalid close time at {candle.open_time}")
        grouped[candle.symbol].append(candle)

    results: list[CandleIntegrity] = []
    for symbol, items in grouped.items():
        ordered = sorted(items, key=lambda candle: candle.open_time)
        duplicates = sum(current.open_time == previous.open_time for previous, current in zip(ordered, ordered[1:]))
        gaps = sum(current.open_time - previous.open_time != INTERVAL_MS[timeframe] for previous, current in zip(ordered, ordered[1:]) if current.open_time != previous.open_time)
        results.append(CandleIntegrity(symbol, timeframe, len(ordered), gaps, duplicates))
    return sorted(results, key=lambda result: result.symbol)


def derive_timeframe(candles: Iterable[Candle], target_timeframe: str) -> list[Candle]:
    """Derive complete UTC-aligned higher-timeframe candles from canonical 15m bars."""
    if target_timeframe not in ("1h", "4h"):
        raise ValueError("target timeframe must be 1h or 4h")
    source = sorted(candles, key=lambda candle: (candle.symbol, candle.open_time))
    validate_candles(source, CANONICAL_TIMEFRAME)
    target_ms = INTERVAL_MS[target_timeframe]
    expected_count = target_ms // INTERVAL_MS[CANONICAL_TIMEFRAME]
    grouped: dict[tuple[str, int], list[Candle]] = defaultdict(list)
    for candle in source:
        bucket = candle.open_time - candle.open_time % target_ms
        grouped[(candle.symbol, bucket)].append(candle)

    derived: list[Candle] = []
    for (symbol, bucket), items in sorted(grouped.items()):
        ordered = sorted(items, key=lambda candle: candle.open_time)
        expected_times = [bucket + index * INTERVAL_MS[CANONICAL_TIMEFRAME] for index in range(expected_count)]
        if [candle.open_time for candle in ordered] != expected_times:
            continue
        derived.append(Candle(
            symbol=symbol,
            timeframe=target_timeframe,
            open_time=bucket,
            close_time=bucket + target_ms,
            open=ordered[0].open,
            high=max(candle.high for candle in ordered),
            low=min(candle.low for candle in ordered),
            close=ordered[-1].close,
            volume=sum(candle.volume for candle in ordered),
        ))
    return derived


def verify_api_overlap(candles: Iterable[Candle], fetch: Callable[[str, str, int], list[Candle]], sample_limit: int = 5_000, minimum_overlap: int = 20) -> dict[str, int]:
    """Require a price-identical overlap with the official 15m candle endpoint."""
    source_by_symbol: dict[str, dict[int, Candle]] = defaultdict(dict)
    for candle in candles:
        source_by_symbol[candle.symbol][candle.open_time] = candle
    overlaps: dict[str, int] = {}
    for symbol, source in source_by_symbol.items():
        official = fetch(symbol, CANONICAL_TIMEFRAME, sample_limit)
        matched = 0
        for candidate in official:
            local = source.get(candidate.open_time)
            if local is None:
                continue
            if not all(isclose(left, right, rel_tol=1e-10, abs_tol=1e-8) for left, right in ((local.open, candidate.open), (local.high, candidate.high), (local.low, candidate.low), (local.close, candidate.close))):
                raise ValueError(f"official API mismatch for {symbol} at {candidate.open_time}")
            matched += 1
        if matched < minimum_overlap:
            raise ValueError(f"insufficient official API overlap for {symbol}: {matched} < {minimum_overlap}")
        overlaps[symbol] = matched
    return overlaps
