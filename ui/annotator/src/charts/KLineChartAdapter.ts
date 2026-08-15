import {
  dispose,
  init,
  OverlayMode,
  type Chart,
  type KLineData,
  type OverlayEvent,
} from "klinecharts";
import type {
  OverlayLine,
  Point,
  PriceLevel,
  TradePlan,
  Triangle,
} from "../types";

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
    .map(toPoint)
    .filter((point): point is Point => point !== null);
  return points.length === 2 ? { p1: points[0], p2: points[1] } : null;
};

// This module is the KLineChart boundary. Nothing outside it stores overlay IDs or pixels.
export class KLineChartAdapter {
  private chart: Chart;
  private lastTimestamp: number | undefined;
  private overlayIds = new Map<string, string[]>();
  constructor(element: HTMLElement) {
    this.chart = init(element)!;
    this.chart.setStyles({
      grid: {
        show: true,
        horizontal: { show: true },
        vertical: { show: true },
      },
    });
  }
  setCandles(candles: KLineData[]) {
    this.lastTimestamp = candles.at(-1)?.timestamp;
    this.chart.applyNewData(candles);
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
    levels: PriceLevel[],
    plan: TradePlan | null,
    side: "long" | "short" | null,
    onStructureEdit: (
      id: string,
      line: "upper" | "lower",
      value: OverlayLine,
    ) => void,
    onLevelEdit: (id: string, point: Point) => void,
    onPlanEdit: (
      key: "entry_price" | "stop_loss" | "take_profit",
      price: number,
    ) => void,
  ) {
    this.clear();
    for (const structure of structures)
      (["upper", "lower"] as const).forEach((which) => {
        const line =
          which === "upper"
            ? structure.geometry.upper_line
            : structure.geometry.lower_line;
        const id = this.chart.createOverlay({
          name: "straightLine",
          groupId: structure.structure_id,
          lock: false,
          mode: mode(structure.geometry.snap_mode),
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
    for (const level of levels) {
      const id = this.chart.createOverlay({
        name: level.end ? "straightLine" : "horizontalStraightLine",
        groupId: level.level_id,
        lock: false,
        points: level.end
          ? [
              { timestamp: level.start.timestamp, value: level.start.price },
              { timestamp: level.end.timestamp, value: level.end.price },
            ]
          : [{ timestamp: level.start.timestamp, value: level.start.price }],
        styles: { line: { color: "#8db4e6", size: 1 } },
        onPressedMoveEnd: (event) => {
          const p = toPoint(event.overlay.points[0], this.lastTimestamp);
          if (p) onLevelEdit(level.level_id, p);
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
          lock: false,
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
    return this.chart.getConvertPictureUrl(true, "png", "#111817") ?? "";
  }
  destroy() {
    dispose(this.chart);
  }
}
