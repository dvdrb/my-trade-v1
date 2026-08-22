import { describe, expect, it } from 'vitest';
import { noFuturePoint, toTimestamp, triangleVerticesAreReplaySafe, type Annotation } from './types';
import { canMutateDraft, createStrongPoint, createTrendline, createTriangle, forTimeframe, normalizeStoredDraft, planIsDirectional, redoDraftHistory, snapshotForCapture, undoDraftHistory, updateLevelCoordinates, updateStrongPoint, updateTrendline, updateTriangleVertices, withMarketState } from './draft';
import { canonicalTrianglePoint, createTriangleTimeAxis, dataIndexForTimestamp, hasThreeTriangleCoordinates, overlayPointForTriangle, timestampForDataIndex } from './charts/triangleProjection';
import { restoreOverlayLock } from './charts/restoreLock';

describe('chart annotation domain boundaries', () => {
  it('normalizes seconds to timestamp milliseconds', () => {
    expect(toTimestamp(1_700_000_000)).toBe(1_700_000_000_000);
  });

  it('does not permit a future overlay coordinate', () => {
    expect(noFuturePoint({ timestamp: 100, price: 42 }, 100)).toBe(true);
    expect(noFuturePoint({ timestamp: 101, price: 42 }, 100)).toBe(false);
  });

  it('creates exactly one canonical triangle from three clicked vertices', () => {
    const vertices = [{ timestamp: 1, price: 110 }, { timestamp: 2, price: 90 }, { timestamp: 3, price: 100 }] as const;
    const triangle = createTriangle('triangle', '4h', 'macro_parent', [...vertices], 'weak');
    expect([triangle]).toHaveLength(1);
    expect(triangle.geometry).toMatchObject({ vertices, snap_mode: 'weak' });
  });

  it('serializes and reloads all three triangle vertices exactly', () => {
    const triangle = createTriangle('triangle', '1h', 'local_parent', [{ timestamp: 10, price: 110 }, { timestamp: 20, price: 90 }, { timestamp: 30, price: 100 }], 'free');
    const reloaded = JSON.parse(JSON.stringify(triangle));
    expect(reloaded.geometry.vertices).toEqual(triangle.geometry.vertices);
  });

  it('updates only the dragged triangle vertex with its market coordinates', () => {
    const original = createTriangle('triangle', '15m', 'entry', [{ timestamp: 1, price: 110 }, { timestamp: 2, price: 90 }, { timestamp: 3, price: 100 }], 'strong');
    for (const index of [0, 1, 2]) {
      const vertices = [...original.geometry.vertices] as typeof original.geometry.vertices;
      vertices[index] = { timestamp: index + 20, price: index + 200 };
      const changed = updateTriangleVertices([original], original.structure_id, vertices)[0];
      expect('vertices' in changed.geometry && changed.geometry.vertices[index]).toEqual(vertices[index]);
      expect('vertices' in changed.geometry && changed.geometry.vertices.filter((_, item) => item !== index)).toEqual(original.geometry.vertices.filter((_, item) => item !== index));
    }
  });

  it('keeps projection geometry distinct from future candle data', () => {
    expect(triangleVerticesAreReplaySafe([{ timestamp: 10, price: 1 }, { timestamp: 20, price: 2 }, { timestamp: 21, price: 3 }], 20)).toBe(true);
  });

  it('renders only a finished three-coordinate triangle and never a fourth dynamic point', () => {
    expect(hasThreeTriangleCoordinates([{ x: 1, y: 1 }, { x: 2, y: 2 }, { x: 3, y: 3 }])).toBe(true);
    expect(hasThreeTriangleCoordinates([{ x: 1, y: 1 }, { x: 2, y: 2 }, { x: 3, y: 3 }, { x: 4, y: 4 }])).toBe(false);
  });

  it('round-trips loaded, nearby, and projected data indexes without pixels', () => {
    const axis = createTriangleTimeAxis([1_000, 2_000, 3_000, 4_000]);
    expect(axis).not.toBeNull();
    const timeAxis = axis!;
    expect(timestampForDataIndex(timeAxis, 2)).toBe(3_000);
    expect(timestampForDataIndex(timeAxis, 6)).toBe(7_000);
    expect(timestampForDataIndex(timeAxis, -2)).toBe(-1_000);
    expect(canonicalTrianglePoint({ timestamp: 999_999, dataIndex: 6, value: 101 }, timeAxis)).toEqual({ timestamp: 7_000, price: 101 });
    expect(dataIndexForTimestamp(timeAxis, 7_000)).toBe(6);
    expect(overlayPointForTriangle(timeAxis, { timestamp: 7_000, price: 101 })).toEqual({ dataIndex: 6, value: 101 });
  });

  it('creates and edits one trendline and one strong point without changing their semantic type', () => {
    const line = createTrendline('line', '1h', { timestamp: 1, price: 10 }, { timestamp: 5, price: 12 }, 'strong');
    const point = createStrongPoint('point', '15m', { timestamp: 3, price: 11 }, 'weak');
    expect([line]).toHaveLength(1);
    expect([point]).toHaveLength(1);
    expect(updateTrendline([line], 'line', { timestamp: 2, price: 10.5 }, line.p2)[0]).toMatchObject({ trendline_id: 'line', p1: { timestamp: 2, price: 10.5 } });
    expect(updateStrongPoint([point], 'point', { timestamp: 4, price: 11.5 })[0]).toMatchObject({ strong_point_id: 'point', point: { timestamp: 4, price: 11.5 } });
  });

  it('isolates structures and levels to their chart timeframe', () => {
    const geometry = { vertices: [{ timestamp: 1, price: 2 }, { timestamp: 1, price: 1 }, { timestamp: 2, price: 1.5 }] as [{ timestamp: number, price: number }, { timestamp: number, price: number }, { timestamp: number, price: number }], snap_mode: 'free' as const };
    const annotation: Annotation = { annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 1, market_state: 'maybe_setup', side: 'long', structures: [
      { structure_id: '4', timeframe: '4h', role: 'macro_parent', geometry },
      { structure_id: '15', timeframe: '15m', role: 'entry', geometry },
    ], trendlines: [createTrendline('line', '1h', { timestamp: 1, price: 1 }, { timestamp: 2, price: 2 }, 'free')], strong_points: [createStrongPoint('point', '15m', { timestamp: 1, price: 1 }, 'weak')], levels: [{ level_id: '1', timeframe: '1h', kind: 'support', start: { timestamp: 1, price: 1 } }] };
    expect(forTimeframe(annotation, '4h').structures.map((item) => item.structure_id)).toEqual(['4']);
    expect(forTimeframe(annotation, '4h').levels).toEqual([]);
    expect(forTimeframe(annotation, '4h').trendlines).toEqual([]);
    expect(forTimeframe(annotation, '15m').strong_points).toHaveLength(1);
  });

  it('clears stale direction and plan when recording Nothing Here', () => {
    const annotation: Annotation = { annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 1, market_state: 'trade', side: 'long', structures: [], trendlines: [], strong_points: [], levels: [], trade_plan: { entry_price: 100, stop_loss: 95, take_profit: 110 } };
    expect(withMarketState(annotation, 'no_structure')).toMatchObject({ side: null, trade_plan: null });
  });

  it('round-trips both strong-zone corners after a drag or resize', () => {
    const annotation: Annotation = { annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 1, market_state: 'maybe_setup', side: null, structures: [], trendlines: [], strong_points: [], levels: [{ level_id: 'zone', timeframe: '1h', kind: 'strong_zone', start: { timestamp: 10, price: 100 }, end: { timestamp: 20, price: 90 } }] };
    const start = { timestamp: 12, price: 105 }, end = { timestamp: 27, price: 88 };
    const saved = { ...annotation, levels: updateLevelCoordinates(annotation.levels, 'zone', start, end) };
    const reloaded = JSON.parse(JSON.stringify(saved)) as Annotation;
    expect(forTimeframe(reloaded, '1h').levels[0]).toMatchObject({ start, end });
  });

  it('normalizes an older local draft without v3 drawing arrays', () => {
    const restored = normalizeStoredDraft({ annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 1, market_state: 'no_structure' }, { session_id: 's', symbol: 'BTC', replay_time: 2 });
    expect(restored?.annotation).toMatchObject({ decision_time: 2, structures: [], trendlines: [], strong_points: [], levels: [], notes: '' });
    expect(restored?.decisionSelected).toBe(false);
  });

  it('preserves a coherent decision lock and rejects a stale one', () => {
    const annotation: Annotation = { annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 5, market_state: 'no_structure', structures: [], trendlines: [], strong_points: [], levels: [] };
    expect(normalizeStoredDraft({ annotation, decisionSelected: true, decisionLockedAt: 5 }, { session_id: 's', symbol: 'BTC', replay_time: 5 })?.decisionLockedAt).toBe(5);
    expect(normalizeStoredDraft({ annotation, decisionSelected: true, decisionLockedAt: 4 }, { session_id: 's', symbol: 'BTC', replay_time: 5 })).toBeNull();
  });

  it('validates directional plans before recording', () => {
    const long: Annotation = { annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 1, market_state: 'trade', side: 'long', structures: [], trendlines: [], strong_points: [], levels: [], trade_plan: { entry_price: 100, stop_loss: 95, take_profit: 110 } };
    expect(planIsDirectional(long)).toBe(true);
    expect(planIsDirectional({ ...long, trade_plan: { entry_price: 100, stop_loss: 105, take_profit: 110 } })).toBe(false);
  });

  it('blocks every draft mutation while a record operation owns the chart', () => {
    expect(canMutateDraft('record')).toBe(false);
    expect(canMutateDraft('timeframe')).toBe(false);
    expect(canMutateDraft(null)).toBe(true);
  });

  it('keeps captured screenshot geometry equal to the record payload despite later edits', () => {
    const annotation: Annotation = { annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 1, market_state: 'valid_triangle_no_trade', structures: [createTriangle('triangle', '15m', 'entry', [{ timestamp: 1, price: 110 }, { timestamp: 2, price: 90 }, { timestamp: 3, price: 100 }], 'free')], trendlines: [], strong_points: [], levels: [] };
    const captured = snapshotForCapture(annotation);
    annotation.structures[0].geometry = { vertices: [{ timestamp: 9, price: 1 }, { timestamp: 10, price: 2 }, { timestamp: 11, price: 3 }], snap_mode: 'free' };
    expect(captured.structures[0].geometry).toMatchObject({ vertices: [{ timestamp: 1, price: 110 }, { timestamp: 2, price: 90 }, { timestamp: 3, price: 100 }] });
  });

  it('undoes and redoes the first decision selection with its original lock', () => {
    const fresh: Annotation = { annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 50, market_state: 'no_structure', structures: [], trendlines: [], strong_points: [], levels: [] };
    const selected: Annotation = { ...fresh, market_state: 'trade' };
    const history = [{ annotation: fresh, decisionSelected: false, decisionLockedAt: null }];
    const redo: typeof history = [];
    const undone = undoDraftHistory(history, redo, { annotation: selected, decisionSelected: true, decisionLockedAt: 50 });
    expect(undone).toEqual({ annotation: fresh, decisionSelected: false, decisionLockedAt: null });
    const redone = redoDraftHistory(history, redo, undone!);
    expect(redone).toEqual({ annotation: selected, decisionSelected: true, decisionLockedAt: 50 });
  });

  it('creates editable overlays for normal restores and locked overlays for capture restores', () => {
    expect(restoreOverlayLock(true)).toBe(false);
    expect(restoreOverlayLock(false)).toBe(true);
  });

  it('preserves projected screenshot geometry while capture overlays are physically locked', () => {
    const geometry = createTriangle('projected', '15m', 'entry', [{ timestamp: 1, price: 110 }, { timestamp: 3, price: 90 }, { timestamp: 8, price: 100 }], 'free').geometry;
    const captured = structuredClone(geometry);
    expect(restoreOverlayLock(false)).toBe(true);
    expect(captured).toEqual(geometry);
    expect(restoreOverlayLock(true)).toBe(false);
  });
});
