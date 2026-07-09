from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class MarketConfig(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTC"])
    timeframe: str = "1h"
    warmup_candles: int = 300


class PivotConfig(BaseModel):
    left: int = 3
    right: int = 3


class TrendConfig(BaseModel):
    ema_fast: int = 50
    ema_slow: int = 200
    require_alignment: bool = True
    require_ema_slope: bool = False
    ema_slope_lookback: int = 12


class TriangleConfig(BaseModel):
    min_candles: int = 10
    max_candles: int = 80
    breakout_buffer_percent: float = 0.0015
    flat_tolerance_percent: float = 0.003
    max_candidates: int = 20
    tolerance_mode: str = "percent"
    line_tolerance_percent: float = 0.0
    max_wick_violation_percent: float = 1.0
    max_close_violation_percent: float = 1.0
    max_allowed_close_violations: int = 1_000_000
    max_allowed_wick_violations: int = 1_000_000
    line_tolerance_atr: float = 0.25
    max_wick_violation_atr: float = 0.50
    max_close_violation_atr: float = 0.25


class ScoringWeights(BaseModel):
    triangle_quality: float = 20.0
    breakout_quality: float = 20.0
    trend_quality: float = 20.0
    zone_quality: float = 20.0
    risk_quality: float = 20.0


class ScoringConfig(BaseModel):
    use_scoring_model: bool = False
    min_trade_score: float = 50.0
    trend_as_hard_filter: bool = True
    zone_as_hard_filter: bool = True
    weights: ScoringWeights = Field(default_factory=ScoringWeights)


class BreakoutConfig(BaseModel):
    min_body_percent: float = 0.25


class ZoneConfig(BaseModel):
    tolerance_percent: float = 0.003
    min_touches: int = 2
    avoid_opposite_zone_within_r: float = 1.5


class StrategyConfig(BaseModel):
    version: str = "triangle-trend-zones-v1"
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    pivots: PivotConfig = Field(default_factory=PivotConfig)
    trend: TrendConfig = Field(default_factory=TrendConfig)
    triangle: TriangleConfig = Field(default_factory=TriangleConfig)
    breakout: BreakoutConfig = Field(default_factory=BreakoutConfig)
    zones: ZoneConfig = Field(default_factory=ZoneConfig)


class RiskConfig(BaseModel):
    starting_balance: float = 1000.0
    risk_per_trade_percent: float = 0.005
    min_reward_risk: float = 2.0
    absolute_min_reward_risk: float = 2.0
    target_reward_risk: float = 2.0
    fee_percent: float = 0.0005
    slippage_percent: float = 0.0005
    score_risk_tiers: list[dict[str, float]] = Field(default_factory=list)


class PaperConfig(BaseModel):
    enabled: bool = True


class AppConfig(BaseModel):
    mode: Literal["paper"] = "paper"
    market: MarketConfig = Field(default_factory=MarketConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")


def _resolve_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_env(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2) or ""
        return os.getenv(name, default)

    return _ENV_PATTERN.sub(replace, value)


def load_config(path: str | Path = "app/config/strategy.yaml") -> AppConfig:
    load_dotenv()
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return AppConfig.model_validate(_resolve_env(data))
