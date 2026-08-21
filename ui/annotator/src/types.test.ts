import { describe, expect, it } from 'vitest';
import { noFuturePoint, toTimestamp, type Annotation } from './types';
import { forTimeframe, withMarketState } from './draft';

describe('chart annotation domain boundaries', () => {
  it('normalizes seconds to timestamp milliseconds', () => {
    expect(toTimestamp(1_700_000_000)).toBe(1_700_000_000_000);
  });

  it('does not permit a future overlay coordinate', () => {
    expect(noFuturePoint({ timestamp: 100, price: 42 }, 100)).toBe(true);
    expect(noFuturePoint({ timestamp: 101, price: 42 }, 100)).toBe(false);
  });

  it('isolates structures and levels to their chart timeframe', () => {
    const geometry = { upper_line: { p1: { timestamp: 1, price: 2 }, p2: { timestamp: 2, price: 2 } }, lower_line: { p1: { timestamp: 1, price: 1 }, p2: { timestamp: 2, price: 1 } }, snap_mode: 'free' as const };
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
});
