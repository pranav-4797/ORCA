import { store } from '../../store/appState';
import {
  OrcaExceedanceWindow,
  OrcaVizSeries,
} from '../../services/orcaApiService';

/**
 * Hourly sea-state charts for the answered query (/viz/{s}/series):
 * one compact SVG panel per metric (wave height, wind gusts) with the
 * Hazard Agent's unsafe threshold drawn in, exceedance spans shaded red,
 * and predicted tide extremes listed as chips.
 */
export class VizChart {
  private element: HTMLElement;

  public constructor() {
    this.element = document.createElement('div');
    this.element.className = 'viz-chart-widget';
    store.subscribe(() => this.render());
    this.render();
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const data: OrcaVizSeries | null = store.vizSeries;
    if (!data || !data.series || !data.series.times?.length) {
      this.element.innerHTML = `
        <div class="widget-section-header">
          <span class="label-caps">SEA-STATE SERIES</span>
          <span class="data-mono-sm" style="color:var(--text-tertiary);">NO DATA</span>
        </div>
        <div class="viz-chart-empty">Hourly wave &amp; gust series appear here after a query.</div>
      `;
      return;
    }

    const s = data.series;
    const windows = data.exceedance_windows ?? [];
    const tides = data.tides ?? [];

    const waveChart = this.metricChart({
      label: 'WAVE HEIGHT',
      times: s.times,
      values: s.wave_height_m ?? [],
      unit: 'm',
      color: '#38bdf8',
      threshold: this.thresholdFor(windows, 'wave_height_m'),
      windows: windows.filter((w) => w.metric === 'wave_height_m'),
      timesAll: s.times,
    });

    const gustChart = this.metricChart({
      label: 'WIND GUSTS',
      times: s.times,
      values: s.wind_gust_kmh ?? [],
      unit: 'km/h',
      color: '#f59e0b',
      threshold: this.thresholdFor(windows, 'wind_gust_kmh'),
      windows: windows.filter((w) => w.metric === 'wind_gust_kmh'),
      timesAll: s.times,
    });

    const tideChips = tides
      .slice(0, 4)
      .map(
        (t) =>
          `<span class="tide-chip ${t.kind}">${t.kind === 'high' ? '\u2191' : '\u2193'} ` +
          `${t.time_local.slice(11, 16)} · ${t.height_m} m</span>`,
      )
      .join('');

    this.element.innerHTML = `
      <div class="widget-section-header">
        <span class="label-caps">SEA-STATE SERIES (48 H)</span>
        <span class="data-mono-sm" style="color:var(--text-tertiary);">NEXT 48 H</span>
      </div>
      ${waveChart}
      ${gustChart}
      ${tides.length ? `<div class="tide-chip-row">${tideChips}</div>` : ''}
    `;
  }

  private thresholdFor(windows: OrcaExceedanceWindow[], metric: string): number | null {
    const hit = windows.find((w) => w.metric === metric);
    return hit ? hit.threshold : null;
  }

  private metricChart(opts: {
    label: string;
    times: string[];
    values: number[];
    unit: string;
    color: string;
    threshold: number | null;
    windows: OrcaExceedanceWindow[];
    timesAll: string[];
  }): string {
    const { label, times, values, unit, color, threshold } = opts;
    const W = 240;
    const H = 64;
    const PADX = 4;

    if (!values.length) return '';

    // Values arrive hourly from "now"; chart only the future window.
    const nowIdx = Math.max(0, values.length - 49);
    const v = values.slice(nowIdx);
    const t = times.slice(nowIdx);

    const maxV = Math.max(...v, threshold ?? 0) * 1.15 || 1;
    const x = (i: number) => PADX + (i / Math.max(v.length - 1, 1)) * (W - 2 * PADX);
    const y = (val: number) => H - 10 - (val / maxV) * (H - 18);

    const pts = v.map((val, i) => `${x(i).toFixed(1)},${y(val).toFixed(1)}`).join(' ');
    const areaPts = `${PADX},${H - 10} ${pts} ${(W - PADX).toFixed(1)},${H - 10}`;

    // Shade exceedance windows by mapping their ISO start/end onto indices.
    let spans = '';
    for (const win of opts.windows) {
      const si = t.findIndex((ts) => ts >= win.start);
      let ei = -1;
      for (let k = t.length - 1; k >= 0; k--) {
        if (t[k] <= win.end) {
          ei = k;
          break;
        }
      }
      if (si < 0 && ei < 0) continue;
      const sIdx = si < 0 ? 0 : si;
      const eIdx = ei < 0 ? t.length - 1 : ei;
      if (eIdx <= sIdx) continue;
      spans +=
        `<rect x="${x(sIdx).toFixed(1)}" y="6" width="${(x(eIdx) - x(sIdx)).toFixed(1)}" ` +
        `height="${H - 16}" fill="#ef4444" opacity="0.12"/>`;
    }

    const thrLine =
      threshold !== null
        ? `<line x1="${PADX}" y1="${y(threshold).toFixed(1)}" x2="${W - PADX}" ` +
          `y2="${y(threshold).toFixed(1)}" stroke="#ef4444" stroke-width="1" ` +
          `stroke-dasharray="4 3" opacity="0.8"/>` +
          `<text x="${W - PADX}" y="${(y(threshold) - 3).toFixed(1)}" font-size="8" ` +
          `fill="#ef4444" text-anchor="end">${threshold}${unit}</text>`
        : '';

    // First/last time ticks.
    const tickStart = t[0]?.slice(11, 16) ?? '';
    const tickEnd = t[t.length - 1]?.slice(11, 16) ?? '';
    const peakNow = v[0] != null ? `${v[0]}${unit}` : '--';

    return `
      <div class="metric-chart">
        <div class="metric-chart-header">
          <span class="label-caps">${label}</span>
          <span class="data-mono-sm" style="color:${color};font-weight:700;">now ${peakNow}</span>
        </div>
        <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="metric-chart-svg">
          <polygon points="${areaPts}" fill="${color}" opacity="0.12"/>
          ${spans}
          <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6"/>
          ${thrLine}
        </svg>
        <div class="metric-chart-axis">
          <span>${tickStart}</span><span>+48 h</span>
        </div>
      </div>
    `;
  }
}
