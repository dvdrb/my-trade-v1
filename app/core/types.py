from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"


class Decision(StrEnum):
    NO_SETUP = "no_setup"
    REJECTED = "rejected"
    ACCEPTED = "accepted"


class TrendDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    close_time: int | None = None


@dataclass(frozen=True)
class Pivot:
    symbol: str
    timeframe: str
    open_time: int
    index: int
    price: float
    kind: str


@dataclass(frozen=True)
class StrongZone:
    kind: str
    low: float
    high: float
    touches: int
    strength: float


@dataclass(frozen=True)
class Triangle:
    kind: str
    start_index: int
    end_index: int
    start_time: int
    end_time: int
    upper_start: float
    upper_end: float
    lower_start: float
    lower_end: float


@dataclass(frozen=True)
class Signal:
    symbol: str
    timeframe: str
    decision: Decision
    side: Side | None = None
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    reward_risk: float | None = None
    strategy_version: str = ""
    triangle_type: str | None = None
    open_time: int | None = None
    position_size: float | None = None
    risk_amount: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Trade:
    symbol: str
    timeframe: str
    side: Side
    entry_time: int
    entry_price: float
    size: float
    stop_loss: float
    take_profit: float
    exit_time: int | None = None
    exit_price: float | None = None
    pnl: float = 0.0
    r_multiple: float = 0.0
    status: str = "open"
    signal_time: int | None = None
    strategy_version: str = ""
    triangle_type: str | None = None
    risk_amount: float | None = None
