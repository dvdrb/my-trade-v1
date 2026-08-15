from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


SCHEMA_VERSION = "human-ground-truth-v1"


def utc_now() -> datetime:
    return datetime.now(UTC)


class MarketState(StrEnum):
    NO_STRUCTURE = "no_structure"
    VALID_TRIANGLE_NO_TRADE = "valid_triangle_no_trade"
    MAYBE_SETUP = "maybe_setup"
    TRADE = "trade"


class HumanSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class StructureRole(StrEnum):
    MACRO_PARENT = "macro_parent"
    LOCAL_PARENT = "local_parent"
    ENTRY = "entry"
    OTHER = "other"


class PricePoint(BaseModel):
    timestamp: int = Field(ge=0)
    price: float = Field(gt=0)


class TrendLine(BaseModel):
    p1: PricePoint
    p2: PricePoint

    @model_validator(mode="after")
    def requires_distinct_timestamps(self) -> "TrendLine":
        if self.p1.timestamp == self.p2.timestamp:
            raise ValueError("trendline points must have different timestamps")
        return self


class TriangleGeometry(BaseModel):
    upper_line: TrendLine
    lower_line: TrendLine
    snap_mode: Literal["free", "weak", "strong"] = "free"


class Structure(BaseModel):
    structure_id: str = Field(default_factory=lambda: str(uuid4()))
    timeframe: Literal["15m", "1h", "4h"]
    role: StructureRole = StructureRole.OTHER
    geometry: TriangleGeometry
    note: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PriceLevel(BaseModel):
    level_id: str = Field(default_factory=lambda: str(uuid4()))
    timeframe: Literal["15m", "1h", "4h"]
    kind: Literal["support", "resistance", "strong_level", "strong_zone"]
    start: PricePoint
    end: PricePoint | None = None
    note: str | None = None


class TradePlan(BaseModel):
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    sl_reason: str | None = None
    tp_reason: str | None = None

    @model_validator(mode="after")
    def plan_has_directional_risk(self) -> "TradePlan":
        if self.entry_price == self.stop_loss or self.entry_price == self.take_profit:
            raise ValueError("entry, stop loss, and take profit must be distinct")
        return self

    def metrics(self, side: HumanSide) -> dict[str, float]:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return {"risk_distance": risk, "reward_distance": reward, "reward_risk": reward / risk,
                "risk_percent": risk / self.entry_price * 100, "reward_percent": reward / self.entry_price * 100}


class HumanAnnotation(BaseModel):
    schema_version: str = SCHEMA_VERSION
    annotation_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    symbol: str
    decision_time: int = Field(ge=0)
    market_state: MarketState
    side: HumanSide | None = None
    confidence: int | None = Field(default=None, ge=1, le=5)
    structures: list[Structure] = Field(default_factory=list)
    levels: list[PriceLevel] = Field(default_factory=list)
    trade_plan: TradePlan | None = None
    notes: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def state_requirements(self) -> "HumanAnnotation":
        if self.market_state in {MarketState.MAYBE_SETUP, MarketState.TRADE} and self.side is None:
            raise ValueError("side is required for maybe_setup and trade")
        if self.market_state == MarketState.TRADE and self.trade_plan is None:
            raise ValueError("trade plan is required for trade")
        return self


class ReplaySession(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    started_at_market_time: int
    replay_time: int
    ended_at_market_time: int | None = None
    status: Literal["active", "ended"] = "active"
    mode: Literal["free_replay", "reconstruct_real_trade", "review_bot_candidate"] = "free_replay"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SimulatedTrade(BaseModel):
    simulated_trade_id: str = Field(default_factory=lambda: str(uuid4()))
    annotation_id: str
    session_id: str
    symbol: str
    side: HumanSide
    entry_price: float
    stop_loss: float
    take_profit: float
    created_at_market_time: int
    status: Literal["pending", "open", "stopped", "target", "manual_exit"] = "pending"
    entry_time: int | None = None
    exit_time: int | None = None
    exit_price: float | None = None
    realized_r: float | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
