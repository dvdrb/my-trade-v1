import { describe, expect, it } from 'vitest';
import { noFuturePoint, toTimestamp } from './types';

describe('chart annotation domain boundaries', () => {
  it('normalizes seconds to timestamp milliseconds', () => {
    expect(toTimestamp(1_700_000_000)).toBe(1_700_000_000_000);
  });

  it('does not permit a future overlay coordinate', () => {
    expect(noFuturePoint({ timestamp: 100, price: 42 }, 100)).toBe(true);
    expect(noFuturePoint({ timestamp: 101, price: 42 }, 100)).toBe(false);
  });
});
