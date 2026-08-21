from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import random

import yaml

from app.core.types import Candle


PRE_ROLL_4H_CANDLES = 200
MINIMUM_FORWARD_15M_CANDLES = 20


@dataclass(frozen=True)
class ReplayRange:
    """The server-owned interval in which blind human decisions are allowed."""

    earliest: int
    latest: int
    pre_roll_candles: int = PRE_ROLL_4H_CANDLES


def _timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


def human_research_bounds(path: str | Path = "app/config/research_periods.yaml") -> tuple[int, int]:
    """Return [start, final-holdout-start), from the canonical research split."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    periods = data["periods"]
    return _timestamp(str(periods["train"]["start"])), _timestamp(str(periods["final_holdout"]["start"]))


def allowed_replay_range(
    candles_15m: list[Candle], candles_4h: list[Candle], *, research_start: int, research_end: int,
) -> ReplayRange:
    """Calculate safe replay points with real 4h pre-roll and useful forward room."""
    if not candles_15m or not candles_4h:
        raise ValueError("15m and 4h historical candles are required for replay")
    closed_4h = sorted(c.close_time if c.close_time is not None else c.open_time for c in candles_4h)
    if len(closed_4h) < PRE_ROLL_4H_CANDLES:
        raise ValueError("not enough closed 4h candles for the required replay pre-roll")
    pre_roll_time = closed_4h[PRE_ROLL_4H_CANDLES - 1]
    allowed = sorted(c.close_time if c.close_time is not None else c.open_time for c in candles_15m if research_start <= (c.close_time if c.close_time is not None else c.open_time) < research_end)
    valid = [time for time in allowed if time >= pre_roll_time]
    if len(valid) <= MINIMUM_FORWARD_15M_CANDLES:
        raise ValueError("not enough research-period candles after replay pre-roll")
    return ReplayRange(valid[0], valid[-MINIMUM_FORWARD_15M_CANDLES - 1])


def choose_random_replay(replay_range: ReplayRange, candles_15m: list[Candle]) -> int:
    candidates = [c.close_time if c.close_time is not None else c.open_time for c in candles_15m if replay_range.earliest <= (c.close_time if c.close_time is not None else c.open_time) <= replay_range.latest]
    if not candidates:
        raise ValueError("no valid random replay points")
    return random.choice(candidates)
