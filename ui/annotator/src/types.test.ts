import { describe, expect, it } from 'vitest';
import { noFuturePoint, toTimestamp, triangleVerticesAreReplaySafe, type Annotation } from './types';
import { createTriangle, forTimeframe, updateLevelCoordinates, updateTriangleVertices, withMarketState } from './draft';

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

  it('rejects a future triangle vertex before it can be saved', () => {
    expect(triangleVerticesAreReplaySafe([{ timestamp: 10, price: 1 }, { timestamp: 20, price: 2 }, { timestamp: 21, price: 3 }], 20)).toBe(false);
  });

  it('isolates structures and levels to their chart timeframe', () => {
    const geometry = { vertices: [{ timestamp: 1, price: 2 }, { timestamp: 1, price: 1 }, { timestamp: 2, price: 1.5 }] as [{ timestamp: number, price: number }, { timestamp: number, price: number }, { timestamp: number, price: number }], snap_mode: 'free' as const };
    const annotation: Annotation = { annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 1, market_state: 'maybe_setup', side: 'long', structures: [
      { structure_id: '4', timeframe: '4h', role: 'macro_parent', geometry },
      { structure_id: '15', timeframe: '15m', role: 'entry', geometry },
    ], levels: [{ level_id: '1', timeframe: '1h', kind: 'support', start: { timestamp: 1, price: 1 } }] };
    expect(forTimeframe(annotation, '4h').structures.map((item) => item.structure_id)).toEqual(['4']);
    expect(forTimeframe(annotation, '4h').levels).toEqual([]);
  });

  it('clears stale direction and plan when recording Nothing Here', () => {
    const annotation: Annotation = { annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 1, market_state: 'trade', side: 'long', structures: [], levels: [], trade_plan: { entry_price: 100, stop_loss: 95, take_profit: 110 } };
    expect(withMarketState(annotation, 'no_structure')).toMatchObject({ side: null, trade_plan: null });
  });

  it('round-trips both strong-zone corners after a drag or resize', () => {
    const annotation: Annotation = { annotation_id: 'a', session_id: 's', symbol: 'BTC', decision_time: 1, market_state: 'maybe_setup', side: null, structures: [], levels: [{ level_id: 'zone', timeframe: '1h', kind: 'strong_zone', start: { timestamp: 10, price: 100 }, end: { timestamp: 20, price: 90 } }] };
    const start = { timestamp: 12, price: 105 }, end = { timestamp: 27, price: 88 };
    const saved = { ...annotation, levels: updateLevelCoordinates(annotation.levels, 'zone', start, end) };
    const reloaded = JSON.parse(JSON.stringify(saved)) as Annotation;
    expect(forTimeframe(reloaded, '1h').levels[0]).toMatchObject({ start, end });
  });
});
