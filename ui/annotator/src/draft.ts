import type { Annotation, Point, Timeframe } from "./types";

export const forTimeframe = (draft: Annotation, timeframe: Timeframe): Annotation => ({
  ...draft,
  structures: draft.structures.filter((item) => item.timeframe === timeframe),
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
