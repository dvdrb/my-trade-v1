import {
  dispose,
  init,
  OverlayMode,
  PolygonType,
  registerOverlay,
  type Chart,
  type KLineData,
  type OverlayEvent,
} from "klinecharts";
import type {
  OverlayLine,
  Point,
  PriceLevel,
  HumanTrendline,
  StrongPoint,
  TradePlan,
  Triangle,
} from "../types";
import {
  canonicalTrianglePoint,
  createTriangleTimeAxis,
  hasThreeTriangleCoordinates,
  overlayPointForTriangle,
  type TriangleTimeAxis,
} from "./triangleProjection";
import { restoreOverlayLock } from "./restoreLock";

type SnapMode = "free" | "weak" | "strong";
type DrawLine = (line: OverlayLine) => void;
const mode = (snap: SnapMode): OverlayMode =>
  snap === "strong"
    ? OverlayMode.StrongMagnet
    : snap === "weak"
      ? OverlayMode.WeakMagnet
      : OverlayMode.Normal;
const toPoint = (
  point: Partial<{ timestamp: number; value: number }>,
  fallbackTimestamp?: number,
): Point | null =>
  point.value !== undefined && (point.timestamp !== undefined || fallbackTimestamp !== undefined)
    ? { timestamp: point.timestamp ?? fallbackTimestamp!, price: point.value }
    : null;
const toLine = (event: OverlayEvent): OverlayLine | null => {
  const points = event.overlay.points
    .map((point) => toPoint(point))
    .filter((point): point is Point => point !== null);
  return points.length === 2 ? { p1: points[0], p2: points[1] } : null;
};
const humanTriangleOverlay = "humanTriangle";
const humanStrongPointOverlay = "humanStrongPoint";
const traceTriangle = (stage: string, value: unknown) =>
  new URLSearchParams(window.location.search).has("triangleTrace") &&
  console.debug(`[humanTriangle] ${stage} ${JSON.stringify(value)}`);

registerOverlay({
  name: humanTriangleOverlay,
  // KLineChart finishes when points.length reaches totalStep - 1. Four therefore
  // represents a three-click interactive triangle, and three restored points are static.
  totalStep: 4,
  needDefaultPointFigure: true,
  createPointFigures: ({ coordinates }) => {
    traceTriangle("createPointFigures coordinates", coordinates);
    return hasThreeTriangleCoordinates(coordinates)
      ? [{
        type: "polygon",
        attrs: { coordinates },
        styles: {
          style: PolygonType.StrokeFill,
          color: "rgba(114, 232, 180, 0.08)",
          borderColor: "#72e8b4",
          borderSize: 2,
        },
        // The default point figures are the only drag handles; the triangle body stays passive.
        ignoreEvent: true,
      }]
      : [];
  },
});

registerOverlay({
  name: humanStrongPointOverlay,
  // KLineChart completes one-click overlays when totalStep is two.
  totalStep: 2,
  needDefaultPointFigure: true,
  createPointFigures: ({ coordinates }) => coordinates.length === 1
    ? [{
      type: "circle",
      attrs: { x: coordinates[0].x, y: coordinates[0].y, r: 5 },
      styles: { style: PolygonType.StrokeFill, color: "rgba(241, 197, 114, 0.3)", borderColor: "#f1c572", borderSize: 2 },
      ignoreEvent: true,
    }]
    : [],
});

// This module is the KLineChart boundary. Nothing outside it stores overlay IDs or pixels.
export class KLineChartAdapter {
  private chart: Chart;
  private element: HTMLElement;
  private lastTimestamp: number | undefined;
  private triangleTimeAxis: TriangleTimeAxis | null = null;
  private overlayIds = new Map<string, string[]>();
  constructor(element: HTMLElement) {
    this.element = element;
    this.chart = init(element)!;
    this.chart.setStyles({
      grid: {
        show: true,
        horizontal: { show: true },
        vertical: { show: true },
      },
    });
  }
  setCandles(candles: KLineData[]): Promise<void> {
    this.lastTimestamp = candles.at(-1)?.timestamp;
    this.triangleTimeAxis = createTriangleTimeAxis(candles.map((candle) => candle.timestamp));
    return new Promise((resolve) => this.chart.applyNewData(candles, false, resolve));
  }
  private saveOverlay(key: string, id: string | null | Array<string | null>) {
    const items = Array.isArray(id)
      ? id.filter((value): value is string => Boolean(value))
      : id
        ? [id]
        : [];
    this.overlayIds.set(key, items);
  }
  private remove(key: string) {
    for (const id of this.overlayIds.get(key) ?? [])
      this.chart.removeOverlay(id);
    this.overlayIds.delete(key);
  }
  clear() {
    for (const key of [...this.overlayIds.keys()]) this.remove(key);
  }
  drawSegment(label: string, snap: SnapMode, complete: DrawLine) {
    const id = this.chart.createOverlay({
      name: "straightLine",
      groupId: `draft-${label}`,
      mode: mode(snap),
      onDrawEnd: (event) => {
        const line = toLine(event);
        if (line) complete(line);
        return true;
      },
    });
    this.saveOverlay(`draft-${label}`, id);
  }
  drawTriangle(snap: SnapMode, complete: (vertices: [Point, Point, Point]) => void) {
    const id = this.chart.createOverlay({
      name: humanTriangleOverlay,
      groupId: "draft-triangle",
      mode: mode(snap),
      onDrawing: (event) => {
        traceTriangle("drawing points", event.overlay.points);
        return true;
      },
      onDrawEnd: (event) => {
        traceTriangle("onDrawEnd points", event.overlay.points);
        const vertices = this.triangleVertices(event);
        if (vertices) {
          traceTriangle("complete vertices", vertices);
          complete(vertices);
        }
        return Boolean(vertices);
      },
    });
    this.saveOverlay("draft-triangle", id);
  }
  drawTrendline(snap: SnapMode, complete: (p1: Point, p2: Point) => void) {
    const id = this.chart.createOverlay({
      name: "straightLine",
      groupId: "draft-trendline",
      mode: mode(snap),
      onDrawEnd: (event) => {
        const points = this.marketPoints(event, 2);
        if (points) complete(points[0], points[1]);
        return Boolean(points);
      },
    });
    this.saveOverlay("draft-trendline", id);
  }
  drawStrongPoint(snap: SnapMode, complete: (point: Point) => void) {
    const id = this.chart.createOverlay({
      name: humanStrongPointOverlay,
      groupId: "draft-strong-point",
      mode: mode(snap),
      onDrawEnd: (event) => {
        const points = this.marketPoints(event, 1, false);
        if (points) complete(points[0]);
        return Boolean(points);
      },
    });
    this.saveOverlay("draft-strong-point", id);
  }
  private marketPoints(event: OverlayEvent, count: number, projected = true): Point[] | null {
    const axis = this.triangleTimeAxis;
    if (!axis) return null;
    const points = event.overlay.points
      .map((point) => canonicalTrianglePoint(point, axis))
      .filter((point): point is Point => point !== null);
    if (points.length !== count || (!projected && points.some((point) => point.timestamp > axis.lastTimestamp))) return null;
    return points;
  }
  private triangleVertices(event: OverlayEvent): [Point, Point, Point] | null {
    traceTriangle("before canonical conversion", event.overlay.points);
    const vertices = this.marketPoints(event, 3);
    if (!vertices) return null;
    const [first, second, third] = vertices;
    if (!first || !second || !third) return null;
    traceTriangle("canonical stored geometry", vertices);
    return [first, second, third];
  }
  drawHorizontal(
    label: string,
    snap: SnapMode,
    complete: (point: Point) => void,
  ) {
    const id = this.chart.createOverlay({
      name: "horizontalStraightLine",
      groupId: `draft-${label}`,
      mode: mode(snap),
      onDrawEnd: (event) => {
        // Horizontal plan/level lines may be placed in the chart's right-side
        // whitespace. Their price is exact; anchor their time at the latest
        // visible candle rather than dropping a valid human placement.
        const point = toPoint(event.overlay.points[0], this.lastTimestamp);
        if (point) complete(point);
        return true;
      },
    });
    this.saveOverlay(`draft-${label}`, id);
  }
  restore(
    structures: Triangle[],
    trendlines: HumanTrendline[],
    strongPoints: StrongPoint[],
    levels: PriceLevel[],
    plan: TradePlan | null,
    side: "long" | "short" | null,
    interactive: boolean,
    onTriangleEdit: (id: string, vertices: [Point, Point, Point]) => void,
    onTrendlineEdit: (id: string, p1: Point, p2: Point) => void,
    onStrongPointEdit: (id: string, point: Point) => void,
    onStructureEdit: (
      id: string,
      line: "upper" | "lower",
      value: OverlayLine,
    ) => void,
    onLevelEdit: (id: string, start: Point, end?: Point) => void,
    onPlanEdit: (
      key: "entry_price" | "stop_loss" | "take_profit",
      price: number,
    ) => void,
  ) {
    this.clear();
    for (const structure of structures) {
      const geometry = structure.geometry;
      if ("vertices" in geometry) {
        const axis = this.triangleTimeAxis;
        if (!axis) continue;
        traceTriangle("restore canonical input", geometry.vertices);
        const points = geometry.vertices.map((vertex) => overlayPointForTriangle(axis, vertex));
        traceTriangle("restore KLineChart overlay.points", points);
        const id = this.chart.createOverlay({
          name: humanTriangleOverlay,
          groupId: structure.structure_id,
          lock: restoreOverlayLock(interactive),
          mode: mode(geometry.snap_mode),
          points,
          onPressedMoveEnd: (event) => {
            const vertices = this.triangleVertices(event);
            if (vertices) onTriangleEdit(structure.structure_id, vertices);
            return true;
          },
        });
        this.saveOverlay(structure.structure_id, id);
        continue;
      }
      (["upper", "lower"] as const).forEach((which) => {
        const line =
          which === "upper"
            ? geometry.upper_line
            : geometry.lower_line;
        const id = this.chart.createOverlay({
          name: "straightLine",
          groupId: structure.structure_id,
          lock: restoreOverlayLock(interactive),
          mode: mode(geometry.snap_mode),
          points: [
            { timestamp: line.p1.timestamp, value: line.p1.price },
            { timestamp: line.p2.timestamp, value: line.p2.price },
          ],
          styles: {
            line: { color: which === "upper" ? "#72e8b4" : "#f1c572", size: 2 },
          },
          onPressedMoveEnd: (event) => {
            const changed = toLine(event);
            if (changed)
              onStructureEdit(structure.structure_id, which, changed);
            return true;
          },
        });
        this.saveOverlay(`${structure.structure_id}-${which}`, id);
      });
    }
    for (const trendline of trendlines) {
      const axis = this.triangleTimeAxis;
      if (!axis) continue;
      const id = this.chart.createOverlay({
        name: "straightLine", groupId: trendline.trendline_id, lock: restoreOverlayLock(interactive), mode: mode(trendline.snap_mode),
        points: [overlayPointForTriangle(axis, trendline.p1), overlayPointForTriangle(axis, trendline.p2)],
        styles: { line: { color: "#f1c572", size: 2 } },
        onPressedMoveEnd: (event) => {
          const points = this.marketPoints(event, 2);
          if (points) onTrendlineEdit(trendline.trendline_id, points[0], points[1]);
          return true;
        },
      });
      this.saveOverlay(trendline.trendline_id, id);
    }
    for (const strongPoint of strongPoints) {
      const axis = this.triangleTimeAxis;
      if (!axis) continue;
      const id = this.chart.createOverlay({
        name: humanStrongPointOverlay, groupId: strongPoint.strong_point_id, lock: restoreOverlayLock(interactive), mode: mode(strongPoint.snap_mode),
        points: [overlayPointForTriangle(axis, strongPoint.point)],
        onPressedMoveEnd: (event) => {
          const points = this.marketPoints(event, 1, false);
          if (points) onStrongPointEdit(strongPoint.strong_point_id, points[0]);
          return true;
        },
      });
      this.saveOverlay(strongPoint.strong_point_id, id);
    }
    for (const level of levels) {
      const id = this.chart.createOverlay({
        // A strong zone is an actual price/time rectangle, not a disguised level line.
        name: level.kind === "strong_zone" ? "rect" : level.end ? "straightLine" : "horizontalStraightLine",
        groupId: level.level_id,
        lock: restoreOverlayLock(interactive),
        points: level.end
          ? [
              { timestamp: level.start.timestamp, value: level.start.price },
              { timestamp: level.end.timestamp, value: level.end.price },
            ]
          : [{ timestamp: level.start.timestamp, value: level.start.price }],
        styles: level.kind === "strong_zone"
          ? { rect: { style: PolygonType.Fill, color: "rgba(141, 180, 230, 0.16)", borderColor: "#8db4e6", borderSize: 1 } }
          : { line: { color: "#8db4e6", size: 1 } },
        onPressedMoveEnd: (event) => {
          const start = toPoint(event.overlay.points[0], this.lastTimestamp);
          const end = level.kind === "strong_zone"
            ? toPoint(event.overlay.points[1], this.lastTimestamp) ?? undefined
            : undefined;
          if (start && (level.kind !== "strong_zone" || end)) onLevelEdit(level.level_id, start, end);
          return true;
        },
      });
      this.saveOverlay(level.level_id, id);
    }
    if (plan && side) {
      const colors: Record<
        "entry_price" | "stop_loss" | "take_profit",
        string
      > = {
        entry_price: "#d6f07b",
        stop_loss: "#ef7777",
        take_profit: "#63d5a3",
      };
      (Object.keys(colors) as Array<keyof typeof colors>).forEach((key) => {
        const id = this.chart.createOverlay({
          name: "horizontalStraightLine",
          groupId: `plan-${key}`,
          lock: restoreOverlayLock(interactive),
          points: [{ timestamp: 0, value: plan[key] }],
          styles: { line: { color: colors[key], size: 2 } },
          onPressedMoveEnd: (event) => {
            const p = toPoint(event.overlay.points[0], this.lastTimestamp);
            if (p) onPlanEdit(key, p.price);
            return true;
          },
        });
        this.saveOverlay(`plan-${key}`, id);
      });
    }
  }
  snapshot(): string {
    const rendered = this.chart.getConvertPictureUrl(true, "png", "#111817");
    if (rendered.startsWith("data:image/png;base64,")) return rendered;
    // KLineChart's composed-canvas exporter can be unavailable in some browser
    // renderers. Compose its visible canvases as a deterministic local fallback.
    const width = this.element.clientWidth, height = this.element.clientHeight;
    if (!width || !height) return "";
    const picture = document.createElement("canvas");
    picture.width = width; picture.height = height;
    const context = picture.getContext("2d");
    if (!context) return "";
    context.fillStyle = "#111817"; context.fillRect(0, 0, width, height);
    const root = this.element.getBoundingClientRect();
    for (const canvas of Array.from(this.element.querySelectorAll("canvas"))) {
      const bounds = canvas.getBoundingClientRect();
      if (bounds.width && bounds.height) context.drawImage(canvas, bounds.left - root.left, bounds.top - root.top, bounds.width, bounds.height);
    }
    return picture.toDataURL("image/png");
  }
  snapshotAfterRender(): Promise<string> {
    return new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve(this.snapshot())));
    });
  }
  destroy() {
    dispose(this.chart);
  }
}
