export type Timeframe = "15m" | "1h" | "4h";
export type Point = { timestamp: number; price: number };
export type OverlayLine = { p1: Point; p2: Point };
export type TriangleGeometry = {
  vertices: [Point, Point, Point];
  snap_mode: "free" | "weak" | "strong";
};
export type LegacyTriangleGeometry = {
  upper_line: OverlayLine;
  lower_line: OverlayLine;
  snap_mode: "free" | "weak" | "strong";
};
export type Triangle = {
  structure_id: string;
  timeframe: Timeframe;
  role: string;
  geometry: TriangleGeometry | LegacyTriangleGeometry;
};
export type HumanTrendline = {
  trendline_id: string;
  timeframe: Timeframe;
  p1: Point;
  p2: Point;
  snap_mode: "free" | "weak" | "strong";
};
export type StrongPoint = {
  strong_point_id: string;
  timeframe: Timeframe;
  point: Point;
  snap_mode: "free" | "weak" | "strong";
};
export type PriceLevel = {
  level_id: string;
  timeframe: Timeframe;
  kind: "support" | "resistance" | "strong_level" | "strong_zone";
  start: Point;
  end?: Point | null;
  note?: string | null;
};
export type TradePlan = {
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  sl_reason?: string | null;
  tp_reason?: string | null;
};
export type Annotation = {
  annotation_id: string;
  session_id: string;
  symbol: string;
  decision_time: number;
  market_state:
    "no_structure" | "valid_triangle_no_trade" | "maybe_setup" | "trade";
  side?: "long" | "short" | null;
  confidence?: number | null;
  structures: Triangle[];
  trendlines: HumanTrendline[];
  strong_points: StrongPoint[];
  levels: PriceLevel[];
  trade_plan?: TradePlan | null;
  notes?: string | null;
};
export const toTimestamp = (value: number): number =>
  value > 1_000_000_000_000 ? value : value * 1000;
export const noFuturePoint = (point: Point, replayTime: number) =>
  point.timestamp <= replayTime;
export const triangleVerticesAreReplaySafe = (vertices: [Point, Point, Point], replayTime: number) =>
  // A vertex can be a trader's geometric projection into blank chart space. This
  // does not grant access to a future candle, outcome, or market observation.
  vertices.every((point) => Number.isFinite(point.timestamp) && point.price > 0);
export const isHumanTriangle = (geometry: Triangle["geometry"]): geometry is TriangleGeometry =>
  "vertices" in geometry;
