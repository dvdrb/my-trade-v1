import type { Annotation, HumanTrendline, Point, StrongPoint, Timeframe, Triangle, TriangleGeometry } from "./types";

export type DraftSession = { session_id: string; symbol: string; replay_time: number };
export type StoredDraft = { annotation: Annotation; decisionSelected: boolean; decisionLockedAt: number | null };

export const canMutateDraft = (operation: string | null): boolean => operation === null;

export const snapshotForCapture = (annotation: Annotation): Annotation => structuredClone(annotation);

export const undoDraftHistory = (history: StoredDraft[], redo: StoredDraft[], current: StoredDraft): StoredDraft | null => {
  const previous = history.at(-1);
  if (!previous) return null;
  history.splice(-1, 1);
  redo.push(current);
  return previous;
};

export const redoDraftHistory = (history: StoredDraft[], redo: StoredDraft[], current: StoredDraft): StoredDraft | null => {
  const next = redo.at(-1);
  if (!next) return null;
  redo.splice(-1, 1);
  history.push(current);
  return next;
};

/** Restore only local state that cannot silently change an already chosen decision. */
export const normalizeStoredDraft = (value: unknown, session: DraftSession): StoredDraft | null => {
  if (!value || typeof value !== "object") return null;
  const record = value as Partial<StoredDraft> & Partial<Annotation>;
  const raw = record.annotation && typeof record.annotation === "object" ? record.annotation : record;
  if (raw.session_id !== session.session_id || raw.symbol !== session.symbol) return null;
  const decisionSelected = record.decisionSelected === true;
  const decisionLockedAt = record.decisionLockedAt ?? null;
  if (decisionSelected && decisionLockedAt !== session.replay_time) return null;
  if (!decisionSelected && decisionLockedAt !== null) return null;
  if (!raw.annotation_id || typeof raw.market_state !== "string") return null;
  return {
    annotation: {
      ...raw as Annotation,
      decision_time: session.replay_time,
      structures: Array.isArray(raw.structures) ? raw.structures : [],
      trendlines: Array.isArray(raw.trendlines) ? raw.trendlines : [],
      strong_points: Array.isArray(raw.strong_points) ? raw.strong_points : [],
      levels: Array.isArray(raw.levels) ? raw.levels : [],
      notes: typeof raw.notes === "string" ? raw.notes : "",
    },
    decisionSelected,
    decisionLockedAt: decisionSelected ? decisionLockedAt : null,
  };
};

export const planIsDirectional = (draft: Annotation): boolean => {
  const plan = draft.trade_plan;
  if (!plan || !draft.side) return false;
  return draft.side === "long"
    ? plan.stop_loss < plan.entry_price && plan.entry_price < plan.take_profit
    : plan.take_profit < plan.entry_price && plan.entry_price < plan.stop_loss;
};

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
