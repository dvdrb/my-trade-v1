from __future__ import annotations

from app.config.settings import AppConfig
from app.core.types import Candle, Decision, Side, Signal, TrendDirection
from app.strategy.breakout import detect_breakout
from app.strategy.candidates import TriangleCandidate, find_triangle_candidates
from app.strategy.context import MarketContext
from app.strategy.nesting import find_nested_triangle_setups, score_nested_relationship
from app.strategy.pivots import detect_pivots
from app.strategy.risk import RiskPlan, calculate_risk_plan
from app.strategy.scoring import _breakout_quality, _risk_quality, risk_percent_for_score
from app.strategy.trend import ema_trend, structure_trend
from app.strategy.zones import build_zones, nearest_resistance, nearest_support


def evaluate_nested_mtf(context: MarketContext, config: AppConfig, equity: float) -> Signal:
    entry = context.entry_candles
    if len(entry) < config.strategy.triangle.min_candles + config.strategy.pivots.right + 2:
        return Signal(context.symbol, context.entry_timeframe, Decision.NO_SETUP, reasons=["not enough entry candles"], strategy_version=config.strategy.version)
    entry_pivots = detect_pivots(entry, config.strategy.pivots.left, config.strategy.pivots.right)
    local_pivots = detect_pivots(context.local_candles, config.strategy.pivots.left, config.strategy.pivots.right)
    regime_pivots = detect_pivots(context.regime_candles, config.strategy.pivots.left, config.strategy.pivots.right)
    entry_candidates = _candidates(entry_pivots, entry, config)
    local_candidates = _candidates(local_pivots, context.local_candles, config)
    regime_candidates = _candidates(regime_pivots, context.regime_candles, config)
    funnel = {
        "regime_triangles_found": len(regime_candidates), "local_triangles_found": len(local_candidates),
        "entry_triangles_found": len(entry_candidates), "nested_setups_found": 0,
        "regime_nested_setups_found": 0, "local_nested_setups_found": 0,
        "entry_breakouts_found": 0, "scored_nested_setups": 0, "accepted_signals": 0,
        "rejected_by_absolute_risk": 0, "rejected_by_score": 0,
        "rejected_by_mtf_zone": 0,
        "entry_breakouts_with_4h_parent": 0, "entry_breakouts_with_1h_parent": 0,
        "entry_breakouts_with_both_parents": 0, "entry_breakouts_with_1h_only": 0,
        "entry_breakouts_with_4h_only": 0, "entry_breakouts_without_parent": 0,
        "4h_parent_found_but_zone_blocked": 0, "4h_parent_found_but_lower_score": 0,
        "4h_parent_found_but_not_nested": 0, "no_4h_parent_found": 0,
        "blocked_mtf_zone_setups": 0, "blocked_mtf_zone_by_side": {},
        "blocked_mtf_zone_by_timeframe": {}, "blocked_mtf_zone_by_parent_alignment": {},
        "blocked_mtf_zone_by_child_triangle_type": {}, "blocked_mtf_zone_by_score_bucket": {},
        "blocked_mtf_zone_details": [],
    }
    if not entry_candidates:
        return _empty(context, config, "no entry triangle candidates", funnel)
    local_nested = find_nested_triangle_setups(local_candidates, entry_candidates, context.local_candles, entry, config.strategy.triangle.line_tolerance_percent)
    regime_nested = find_nested_triangle_setups(
        regime_candidates,
        entry_candidates,
        context.regime_candles,
        entry,
        config.strategy.scoring.nested_regime_tolerance_percent,
    )
    funnel["local_nested_setups_found"] = len(local_nested)
    funnel["regime_nested_setups_found"] = len(regime_nested)
    funnel["nested_setups_found"] = len({id(child) for _, child in local_nested + regime_nested})
    if not local_nested and not regime_nested:
        return _empty(context, config, "no nested parent context", funnel)

    local_by_child = {id(child): parent for parent, child in local_nested}
    regime_by_child = {id(child): parent for parent, child in regime_nested}
    local_zones = build_zones(local_pivots, config.strategy.zones.tolerance_percent, config.strategy.zones.min_touches)
    regime_zones = build_zones(regime_pivots, config.strategy.zones.tolerance_percent, config.strategy.zones.min_touches)
    entry_zones = build_zones(entry_pivots, config.strategy.zones.tolerance_percent, config.strategy.zones.min_touches)
    results: list[tuple[float, TriangleCandidate, Side, RiskPlan, dict[str, object], list[str]]] = []
    current_index = len(entry) - 1
    for child in entry_candidates:
        side = detect_breakout(entry[-1], child.triangle, current_index, config.strategy.triangle.breakout_buffer_percent, config.strategy.breakout.min_body_percent, config.strategy.triangle.line_tolerance_percent)
        if side is None:
            continue
        funnel["entry_breakouts_found"] += 1
        parent_1h, parent_4h = local_by_child.get(id(child)), regime_by_child.get(id(child))
        alignment = _parent_alignment(parent_4h, parent_1h)
        _record_parent_diagnostics(funnel, parent_4h, parent_1h, bool(regime_candidates))
        if parent_1h is None and parent_4h is None:
            continue
        risk = calculate_risk_plan(side, entry[-1].close, entry_pivots, child.triangle, current_index, equity, config.risk.risk_per_trade_percent, config.risk.absolute_min_reward_risk, config.risk.target_reward_risk)
        if risk is None:
            funnel["rejected_by_absolute_risk"] += 1
            continue
        funnel["scored_nested_setups"] += 1
        score, metadata, reasons = _nested_score(parent_4h, parent_1h, child, context, entry_pivots, regime_pivots, local_pivots, entry_zones, local_zones, regime_zones, side, risk, config)
        if _should_hard_reject_zone(metadata, config):
            funnel["rejected_by_mtf_zone"] += 1
            _record_zone_block(funnel, metadata, side, alignment, child.triangle_type)
            if parent_4h:
                funnel["4h_parent_found_but_zone_blocked"] += 1
            continue
        results.append((score, child, side, risk, metadata, reasons))
    if not results:
        reason = "blocked by MTF opposite zone" if funnel["rejected_by_mtf_zone"] else "no risk-valid nested breakouts"
        return _empty(context, config, reason, funnel, Decision.REJECTED if funnel["entry_breakouts_found"] else Decision.NO_SETUP)
    results.sort(key=lambda item: item[0], reverse=True)
    score, child, side, risk, metadata, reasons = results[0]
    if not metadata["parent_4h_triangle_type"] and any(item[4]["parent_4h_triangle_type"] for item in results[1:]):
        funnel["4h_parent_found_but_lower_score"] += 1
    metadata.update(funnel)
    if score < config.strategy.scoring.min_trade_score or risk_percent_for_score(score, config) is None:
        funnel["rejected_by_score"] += 1
        metadata.update(funnel)
        return Signal(context.symbol, context.entry_timeframe, Decision.REJECTED, side, score, ["nested score below minimum"], risk.entry_price, risk.stop_loss, risk.take_profit, risk.reward_risk, config.strategy.version, child.triangle_type, entry[-1].open_time, metadata=metadata)
    risk_percent = risk_percent_for_score(score, config)
    assert risk_percent is not None
    sized = calculate_risk_plan(side, entry[-1].close, entry_pivots, child.triangle, current_index, equity, risk_percent, config.risk.absolute_min_reward_risk, config.risk.target_reward_risk)
    assert sized is not None
    metadata["accepted_signals"] = 1
    return Signal(context.symbol, context.entry_timeframe, Decision.ACCEPTED, side, score, reasons, sized.entry_price, sized.stop_loss, sized.take_profit, sized.reward_risk, config.strategy.version, child.triangle_type, entry[-1].open_time, sized.position_size, equity * risk_percent, metadata)


def _candidates(pivots, candles: list[Candle], config: AppConfig) -> list[TriangleCandidate]:
    return find_triangle_candidates(pivots, len(candles) - 1, config.strategy.triangle.min_candles, config.strategy.triangle.max_candles, config.strategy.triangle.flat_tolerance_percent, config.strategy.triangle.max_candidates, candles, config.strategy.triangle.line_tolerance_percent, config.strategy.triangle.max_wick_violation_percent, config.strategy.triangle.max_close_violation_percent, config.strategy.triangle.max_allowed_close_violations, config.strategy.triangle.max_allowed_wick_violations)


def _trend(candles: list[Candle], pivots, config: AppConfig) -> TrendDirection:
    return ema_trend(candles, config.strategy.trend.ema_fast, config.strategy.trend.ema_slow) if len(candles) >= config.strategy.trend.ema_slow else structure_trend(pivots)


def _nested_score(parent_4h, parent_1h, child, context, entry_pivots, regime_pivots, local_pivots, entry_zones, local_zones, regime_zones, side, risk, config):
    desired = TrendDirection.BULLISH if side == Side.LONG else TrendDirection.BEARISH
    entry_trend, local_trend, regime_trend = _trend(context.entry_candles, entry_pivots, config), _trend(context.local_candles, local_pivots, config), _trend(context.regime_candles, regime_pivots, config)
    score_4h = 20.0 if parent_4h and regime_trend in (desired, TrendDirection.NEUTRAL) else 0.0
    score_1h = 15.0 if parent_1h and local_trend in (desired, TrendDirection.NEUTRAL) else 0.0
    relationship_parent = parent_1h or parent_4h
    relationship_candles = context.local_candles if parent_1h else context.regime_candles
    relationship_tolerance = config.strategy.triangle.line_tolerance_percent if parent_1h else config.strategy.scoring.nested_regime_tolerance_percent
    score_nested, nested_context = score_nested_relationship(relationship_parent, child, relationship_candles, context.entry_candles, side, relationship_tolerance)
    entry_quality, _, _ = _breakout_quality(child, context.entry_candles[-1], side, config.strategy.triangle.breakout_buffer_percent)
    score_breakout = entry_quality / 20 * 15
    score_zones, zone_context, zone_blocks = _mtf_zone_score(regime_zones, local_zones, entry_zones, side, risk)
    score_risk_raw, _, _ = _risk_quality(risk, config)
    score_risk = score_risk_raw / 20 * 10
    total = score_4h + score_1h + score_nested + score_breakout + score_zones + score_risk
    alignment = "both" if parent_4h and parent_1h else "4h_only" if parent_4h else "1h_only"
    metadata = {"score_total": total, "score_parent_4h_structure": score_4h, "score_parent_1h_structure": score_1h, "score_nested_triangle": score_nested, "score_entry_breakout": score_breakout, "score_mtf_zones": score_zones, "score_risk_quality": score_risk, "parent_4h_triangle_type": parent_4h.triangle_type if parent_4h else None, "parent_1h_triangle_type": parent_1h.triangle_type if parent_1h else None, "child_triangle_type": child.triangle_type, "nested_context": nested_context, "parent_timeframe_alignment": alignment, "entry_trend_direction": entry_trend.value, "local_trend_direction": local_trend.value, "regime_trend_direction": regime_trend.value, "mtf_zone_context": zone_context, "mtf_opposite_zone_before_target": bool(zone_blocks), "mtf_zone_blocks": zone_blocks}
    return total, metadata, ["nested MTF breakout", nested_context, zone_context]


def _mtf_zone_score(regime_zones, local_zones, entry_zones, side: Side, risk: RiskPlan) -> tuple[float, str, list[dict[str, object]]]:
    score, contexts, blocks = 8.0, [], []
    for label, zones, weight in (("4h", regime_zones, 6.0), ("1h", local_zones, 4.0), ("15m", entry_zones, 2.0)):
        favorable = nearest_support(zones, risk.entry_price) if side == Side.LONG else nearest_resistance(zones, risk.entry_price)
        opposite = nearest_resistance(zones, risk.entry_price) if side == Side.LONG else nearest_support(zones, risk.entry_price)
        if favorable:
            score += weight
            contexts.append(f"{label} favorable zone")
        if opposite:
            distance = (opposite.low - risk.entry_price) if side == Side.LONG else (risk.entry_price - opposite.high)
            if distance / max(abs(risk.entry_price - risk.stop_loss), 1e-9) < risk.reward_risk:
                score -= weight
                contexts.append(f"{label} opposite zone before target")
                risk_distance = max(abs(risk.entry_price - risk.stop_loss), 1e-9)
                blocks.append({"timeframe": label, "zone_kind": opposite.kind, "distance_to_entry_r": distance / risk_distance, "distance_to_target_r": (abs(risk.take_profit - opposite.low) if side == Side.LONG else abs(opposite.high - risk.take_profit)) / risk_distance})
    return max(0.0, min(20.0, score)), "; ".join(contexts) or "no nearby MTF zones", blocks


def _parent_alignment(parent_4h: TriangleCandidate | None, parent_1h: TriangleCandidate | None) -> str:
    return "both" if parent_4h and parent_1h else "4h_only" if parent_4h else "1h_only" if parent_1h else "none"


def _increment(counter: dict[str, object], key: str) -> None:
    counter[key] = int(counter.get(key, 0)) + 1


def _record_parent_diagnostics(funnel: dict[str, object], parent_4h: TriangleCandidate | None, parent_1h: TriangleCandidate | None, regime_candidates_exist: bool) -> None:
    if parent_4h:
        funnel["entry_breakouts_with_4h_parent"] = int(funnel["entry_breakouts_with_4h_parent"]) + 1
    if parent_1h:
        funnel["entry_breakouts_with_1h_parent"] = int(funnel["entry_breakouts_with_1h_parent"]) + 1
    alignment = _parent_alignment(parent_4h, parent_1h)
    if alignment == "both":
        funnel["entry_breakouts_with_both_parents"] = int(funnel["entry_breakouts_with_both_parents"]) + 1
    elif alignment == "1h_only":
        funnel["entry_breakouts_with_1h_only"] = int(funnel["entry_breakouts_with_1h_only"]) + 1
    elif alignment == "4h_only":
        funnel["entry_breakouts_with_4h_only"] = int(funnel["entry_breakouts_with_4h_only"]) + 1
    else:
        funnel["entry_breakouts_without_parent"] = int(funnel["entry_breakouts_without_parent"]) + 1
    if parent_4h is None:
        key = "4h_parent_found_but_not_nested" if regime_candidates_exist else "no_4h_parent_found"
        funnel[key] = int(funnel[key]) + 1


def _record_zone_block(funnel: dict[str, object], metadata: dict[str, object], side: Side, alignment: str, child_type: str) -> None:
    funnel["blocked_mtf_zone_setups"] = int(funnel["blocked_mtf_zone_setups"]) + 1
    _increment(funnel["blocked_mtf_zone_by_side"], side.value)  # type: ignore[arg-type]
    _increment(funnel["blocked_mtf_zone_by_parent_alignment"], alignment)  # type: ignore[arg-type]
    _increment(funnel["blocked_mtf_zone_by_child_triangle_type"], child_type)  # type: ignore[arg-type]
    _increment(funnel["blocked_mtf_zone_by_score_bucket"], _score_bucket(float(metadata["score_total"])))  # type: ignore[arg-type]
    for block in metadata["mtf_zone_blocks"]:  # type: ignore[union-attr]
        _increment(funnel["blocked_mtf_zone_by_timeframe"], str(block["timeframe"]))  # type: ignore[arg-type]
        funnel["blocked_mtf_zone_details"].append({**block, "side": side.value, "parent_timeframe_alignment": alignment, "child_triangle_type": child_type})  # type: ignore[union-attr]


def _score_bucket(score: float) -> str:
    return "80_100" if score >= 80 else "70_79" if score >= 70 else "60_69" if score >= 60 else "50_59" if score >= 50 else "40_49" if score >= 40 else "0_39"


def _should_hard_reject_zone(metadata: dict[str, object], config: AppConfig) -> bool:
    return config.strategy.scoring.mtf_zone_as_hard_filter and bool(metadata["mtf_opposite_zone_before_target"])


def _empty(context, config, reason, funnel, decision=Decision.NO_SETUP):
    return Signal(context.symbol, context.entry_timeframe, decision, reasons=[reason], strategy_version=config.strategy.version, open_time=context.entry_candles[-1].open_time if context.entry_candles else None, metadata=funnel)
