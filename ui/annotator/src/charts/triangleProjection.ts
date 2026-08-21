import type { Point } from "../types";

type ChartPoint = Partial<{ timestamp: number; dataIndex: number; value: number }>;

export type TriangleTimeAxis = {
  timestamps: readonly number[];
  firstDataIndex: number;
  lastDataIndex: number;
  firstTimestamp: number;
  lastTimestamp: number;
  timeframeDuration: number;
};

export const hasThreeTriangleCoordinates = (coordinates: readonly unknown[]) => coordinates.length === 3;

export const createTriangleTimeAxis = (timestamps: readonly number[]): TriangleTimeAxis | null => {
  if (timestamps.length < 2) return null;
  const firstTimestamp = timestamps[0], lastTimestamp = timestamps.at(-1)!;
  const timeframeDuration = timestamps.at(-1)! - timestamps.at(-2)!;
  if (timeframeDuration <= 0) return null;
  return { timestamps, firstDataIndex: 0, lastDataIndex: timestamps.length - 1, firstTimestamp, lastTimestamp, timeframeDuration };
};

export const timestampForDataIndex = (axis: TriangleTimeAxis, dataIndex: number): number => {
  if (dataIndex >= axis.firstDataIndex && dataIndex <= axis.lastDataIndex)
    return axis.timestamps[dataIndex];
  if (dataIndex > axis.lastDataIndex)
    return axis.lastTimestamp + (dataIndex - axis.lastDataIndex) * axis.timeframeDuration;
  return axis.firstTimestamp + (dataIndex - axis.firstDataIndex) * axis.timeframeDuration;
};

export const dataIndexForTimestamp = (axis: TriangleTimeAxis, timestamp: number): number => {
  const exact = axis.timestamps.indexOf(timestamp);
  if (exact >= 0) return exact;
  if (timestamp > axis.lastTimestamp)
    return axis.lastDataIndex + Math.round((timestamp - axis.lastTimestamp) / axis.timeframeDuration);
  return axis.firstDataIndex + Math.round((timestamp - axis.firstTimestamp) / axis.timeframeDuration);
};

export const canonicalTrianglePoint = (point: ChartPoint, axis: TriangleTimeAxis): Point | null => {
  if (point.value === undefined) return null;
  // KLineChart deliberately omits timestamp in right-side blank space. dataIndex is
  // therefore authoritative whenever it exists, including for normal candle points.
  if (point.dataIndex !== undefined)
    return { timestamp: timestampForDataIndex(axis, point.dataIndex), price: point.value };
  return point.timestamp === undefined ? null : { timestamp: point.timestamp, price: point.value };
};

export const overlayPointForTriangle = (axis: TriangleTimeAxis, vertex: Point) => ({
  // KLineChart v9 resolves timestamp before dataIndex while painting. Supplying the
  // ephemeral dataIndex alone is what preserves an extrapolated point's X position;
  // the canonical timestamp remains in the annotation and is deterministically used here.
  dataIndex: dataIndexForTimestamp(axis, vertex.timestamp),
  value: vertex.price,
});
