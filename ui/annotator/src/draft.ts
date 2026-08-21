import type { Annotation, HumanTrendline, Point, StrongPoint, Timeframe, Triangle, TriangleGeometry } from "./types";

export const forTimeframe = (draft: Annotation, timeframe: Timeframe): Annotation => ({
  ...draft,
  structures: draft.structures.filter((item) => item.timeframe === timeframe),
  trendlines: draft.trendlines.filter((item) => item.timeframe === timeframe),
  strong_points: draft.strong_points.filter((item) => item.timeframe === timeframe),
  levels: draft.levels.filter((item) => item.timeframe === timeframe),
});

export const withMarketState = (draft: Annotation, market_state: Annotation["market_state"]): Annotation => ({
  ...draft,
  market_state,
  ...(market_state === "no_structure" || market_state === "valid_triangle_no_trade" ? { side: null, trade_plan: null } : {}),
});

export const updateLevelCoordinates = (
  levels: Annotation["levels"], levelId: string, start: Point, end?: Point,
): Annotation["levels"] => levels.map((level) =>
  level.level_id !== levelId
    ? level
    : level.kind === "strong_zone" && end
      ? { ...level, start, end }
      : { ...level, start },
);

export const createTriangle = (
  structure_id: string, timeframe: Timeframe, role: string,
  vertices: [Point, Point, Point], snap_mode: TriangleGeometry["snap_mode"],
): Triangle & { geometry: TriangleGeometry } => ({ structure_id, timeframe, role, geometry: { vertices, snap_mode } });

export const updateTriangleVertices = (
  structures: Triangle[], structureId: string, vertices: [Point, Point, Point],
): Triangle[] => structures.map((structure) =>
  structure.structure_id === structureId && "vertices" in structure.geometry
    ? { ...structure, geometry: { ...structure.geometry, vertices } }
    : structure,
);

export const createTrendline = (
  trendline_id: string, timeframe: Timeframe, p1: Point, p2: Point,
  snap_mode: HumanTrendline["snap_mode"],
): HumanTrendline => ({ trendline_id, timeframe, p1, p2, snap_mode });

export const updateTrendline = (
  trendlines: HumanTrendline[], trendlineId: string, p1: Point, p2: Point,
): HumanTrendline[] => trendlines.map((trendline) =>
  trendline.trendline_id === trendlineId ? { ...trendline, p1, p2 } : trendline,
);

export const createStrongPoint = (
  strong_point_id: string, timeframe: Timeframe, point: Point,
  snap_mode: StrongPoint["snap_mode"],
): StrongPoint => ({ strong_point_id, timeframe, point, snap_mode });

export const updateStrongPoint = (
  points: StrongPoint[], pointId: string, point: Point,
): StrongPoint[] => points.map((item) => item.strong_point_id === pointId ? { ...item, point } : item);
