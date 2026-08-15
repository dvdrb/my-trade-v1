import { init, dispose, type Chart, type KLineData } from 'klinecharts';
import type { OverlayLine, Point, Triangle } from '../types';

// This is the only KLineChart-specific module. Domain data uses market coordinates.
export class KLineChartAdapter {
  private chart: Chart;
  constructor(element: HTMLElement) { this.chart = init(element)!; this.chart.setStyles({ grid: { show: true, horizontal: { show: true }, vertical: { show: true } } }); }
  setCandles(candles: KLineData[]) { this.chart.applyNewData(candles); }
  setTriangles(triangles: Triangle[]) { this.chart.removeOverlay(); triangles.forEach((triangle) => this.chart.createOverlay({
    name: 'segment', groupId: triangle.structure_id, points: [triangle.geometry.upper_line.p1, triangle.geometry.upper_line.p2],
    styles: { line: { color: '#72e8b4', size: 2 } }
  })); }
  domainLine(points: Array<{ timestamp: number; value: number }>): OverlayLine { return { p1: { timestamp: points[0].timestamp, price: points[0].value }, p2: { timestamp: points[1].timestamp, price: points[1].value } }; }
  snapshot(): string { return this.chart.getConvertPictureUrl(true, 'png', '#111817') ?? ''; }
  destroy() { dispose(this.chart); }
}
