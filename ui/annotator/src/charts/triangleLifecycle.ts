import type { Point } from "../types";

export const hasThreeTriangleCoordinates = (coordinates: readonly unknown[]) => coordinates.length === 3;

// Keep React's restore pass outside KLineChart's final-click call stack.
export const completeTriangleAfterNativeDraw = (
  vertices: [Point, Point, Point],
  complete: (vertices: [Point, Point, Point]) => void,
) => queueMicrotask(() => complete(vertices));
