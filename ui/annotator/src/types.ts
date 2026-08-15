export type Timeframe = '15m' | '1h' | '4h';
export type Point = { timestamp: number; price: number };
export type OverlayLine = { p1: Point; p2: Point };
export type Triangle = { structure_id: string; timeframe: Timeframe; role: string; geometry: { upper_line: OverlayLine; lower_line: OverlayLine; snap_mode: 'free'|'weak'|'strong' } };
export const toTimestamp = (value: number): number => value > 1_000_000_000_000 ? value : value * 1000;
export const noFuturePoint = (point: Point, replayTime: number) => point.timestamp <= replayTime;
