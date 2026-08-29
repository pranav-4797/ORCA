import * as L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { store } from '../../store/appState';

/**
 * Operational sea map -- renders the /viz/{session} GeoJSON FeatureCollection
 * produced with every answer, overlaid on the OFFICIAL INCOIS PFZ live layer
 * (/api/pfz/live):
 *   query_point    blue dot          pfz_primary   green zone + ring
 *   pfz_alternate  pale green        route         dashed cyan LineString
 *   boundary_flag  red flag          cap_hazard    IMD warning polygon
 *   pfz_landing    purple dot (centre whose advisory fired)
 *   pfz_line       yellow dashed LineString (official digitized PFZ geometry)
 *   landing_centre pink/grey dot (landing centre, issued or not)
 *
 * The component owns its DOM imperatively (Leaflet dies under innerHTML
 * re-renders): the AgentPanel may re-parent this element freely, we only
 * invalidate size on re-attach and swap the vector layer on new data.
 */
export class OceanMap {
  private element: HTMLElement;
  private map: L.Map | null = null;
  private layer: L.FeatureGroup | null = null;
  private lastGeojson: any = null;
  private lastPfzToken: string = '';
  private queryPoint: { lat: number; lon: number } | null = null;

  private readonly COLORS: Record<string, { color: string; fill: string }> = {
    query_point: { color: '#38bdf8', fill: '#38bdf8' },
    pfz_primary: { color: '#22c55e', fill: '#22c55e' },
    pfz_alternate: { color: '#86efac', fill: '#86efac' },
    fleet_recommended: { color: '#16a34a', fill: '#16a34a' },
    fleet_candidate: { color: '#f59e0b', fill: '#f59e0b' },
    fleet_change: { color: '#a855f7', fill: '#a855f7' },
    pfz_landing: { color: '#e879f9', fill: '#e879f9' },
    pfz_line: { color: '#facc15', fill: 'none' },
    landing_centre: { color: '#64748b', fill: '#64748b' },
    landing_centre_issued: { color: '#f472b6', fill: '#f472b6' },
    wind_divergence: { color: '#ef4444', fill: '#ef4444' },
    route: { color: '#22d3ee', fill: 'none' },
    boundary_flag: { color: '#f87171', fill: '#f87171' },
    cap_hazard: { color: '#fbbf24', fill: '#f59e0b' },
    sar_known: { color: '#22c55e', fill: '#22c55e' },
    sar_unknown: { color: '#f59e0b', fill: '#f59e0b' },
    sar_unknown_high: { color: '#ef4444', fill: '#ef4444' },
    sar_low_confidence: { color: '#94a3b8', fill: '#94a3b8' },
    sar_other: { color: '#64748b', fill: '#64748b' },
    imbl_line: { color: '#f87171', fill: 'none' },
  };

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'ocean-map-widget';
    this.element.innerHTML = `
      <div class="widget-section-header">
        <span class="label-caps">OPERATIONS MAP</span>
        <span class="data-mono-sm" id="ocean-map-status" style="color:var(--text-tertiary);">NO FIX</span>
      </div>
      <div class="ocean-map-canvas" id="ocean-map-canvas"></div>
      <div class="ocean-map-legend" id="ocean-map-legend"></div>
    `;
    store.subscribe(() => this.onState());
    // First paint happens after the element is in the DOM (see onState).
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private onState(): void {
    this.ensureMap();
    const statusEl = this.element.querySelector('#ocean-map-status');
    const geojson = store.vizGeojson;
    const pfzToken =
      `${store.pfzLive?.fetched_at ?? ''}|${store.pfzLive?.forecast_date ?? ''}`;

    if ((!geojson || !geojson.features || geojson.features.length === 0) &&
        !store.pfzLive) {
      if (statusEl) statusEl.textContent = store.vizSessionId ? 'NO MAP DATA' : 'ASK A QUESTION';
      return;
    }
    if (geojson === this.lastGeojson && pfzToken === this.lastPfzToken) {
      // Same data, but the panel may have re-parented us -- resize only.
      this.map?.invalidateSize();
      return;
    }
    this.lastGeojson = geojson;
    this.lastPfzToken = pfzToken;
    if (statusEl) statusEl.textContent =
      `${geojson?.session_id?.slice(0, 8) ?? ''}${store.pfzLive ? ' · PFZ ' + (store.pfzLive.valid_upto || 'live') : ''}`;
    this.renderFeatures(geojson);
    this.renderLegend(geojson);
    this.map?.invalidateSize();
  }

  private ensureMap(): void {
    if (this.map) {
      this.map.invalidateSize();
      return;
    }
    const canvas = this.element.querySelector('#ocean-map-canvas') as HTMLElement | null;
    if (!canvas || !canvas.isConnected) return; // not mounted yet

    this.map = L.map(canvas, {
      center: [16.0, 74.5],          // Indian west-coast default until data arrives
      zoom: 7,
      zoomControl: true,
      attributionControl: false,
      scrollWheelZoom: false,        // panel scrolls; enable on click
    });
    canvas.addEventListener('click', () => this.map?.scrollWheelZoom.enable());
    this.map.on('mouseout', () => this.map?.scrollWheelZoom.disable());

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18,
      subdomains: 'abc',
    }).addTo(this.map);

    this.layer = L.featureGroup().addTo(this.map);
  }

  private renderFeatures(geojson: any): void {
    if (!this.map || !this.layer) return;
    this.layer.clearLayers();

    const boundsFeatures: any[] = [];

    // Official INCOIS PFZ live layer (zone lines + landing centres) is
    // background context across the whole coast -- drawn, but excluded from
    // fitBounds so the view stays focused on the answered query.
    const pfz = store.pfzLive;
    if (pfz) {
      for (const f of pfz.pfz_lines?.features ?? []) {
        boundsFeatures.push({
          ...f,
          properties: { ...(f.properties || {}), kind: 'pfz_line' },
        });
      }
      for (const f of pfz.landing_centres?.features ?? []) {
        const issued = f.properties?.forecast === 'Y' ||
          f.properties?.pfz_issued === true;
        boundsFeatures.push({
          ...f,
          properties: {
            ...(f.properties || {}),
            kind: issued ? 'landing_centre_issued' : 'landing_centre',
          },
        });
      }
    }

    this.renderShapes([...boundsFeatures, ...(geojson?.features ?? [])],
      (f: any) => this.isBackgroundKind(f.properties?.kind));

    // Fit the view to the query's own features (not the coast-wide PFZ feed).
    try {
      const queryFeatures = (geojson?.features ?? []).map((f: any) => {
        const geom = f?.geometry;
        if (!geom) return null as any;
        if (geom.type === 'Point') {
          const [lon, lat] = geom.coordinates;
          return L.latLng(lat, lon);
        }
        if (geom.type === 'LineString') {
          return (geom.coordinates as [number, number][]).map(
            ([lon, lat]) => L.latLng(lat, lon),
          );
        }
        return null as any;
      }).filter((ll: any) => ll != null).flat();
      if (queryFeatures.length > 0) {
        this.map.fitBounds(L.latLngBounds(queryFeatures).pad(0.35), { animate: false });
      }
    } catch {
      /* no query features -- keep current view */
    }
  }

  private isBackgroundKind(kind: string): boolean {
    return kind === 'pfz_line' || kind === 'landing_centre' ||
      kind === 'landing_centre_issued';
  }

  private renderShapes(features: any[], isBackground: (f: any) => boolean): void {
    if (!this.layer) return;
    this.queryPoint = null;
    for (const f of features) {
      const kind: string = f.properties?.kind ?? '';
      if (kind === 'query_point' && f.geometry?.type === 'Point') {
        const [qlon, qlat] = f.geometry.coordinates;
        this.queryPoint = { lat: qlat, lon: qlon };
      }
    }
    for (const f of features) {
      const kind: string = f.properties?.kind ?? '';
      const c = this.COLORS[kind] ?? { color: '#94a3b8', fill: '#94a3b8' };
      const geom = f.geometry;
      if (!geom) continue;

      let shape: L.Layer | null = null;
      if (geom.type === 'Point') {
        const [lon, lat] = geom.coordinates;
        const isPfz = kind.startsWith('pfz') && !this.isBackgroundKind(kind);
        const isSar = kind.startsWith('sar_');
        const isBackground = this.isBackgroundKind(kind);
        shape = L.circleMarker([lat, lon], {
          radius: kind === 'query_point' ? 8
            : isPfz ? 6
            : isBackground ? 3
            : isSar ? 7
            : kind === 'wind_divergence' ? 6
            : 5,
          color: c.color,
          fillColor: c.fill,
          fillOpacity: isSar ? 0.95 : isBackground ? 0.7 : 0.85,
          weight: isSar ? 2.5 : isBackground ? 1 : 2,
        });
        if (kind === 'wind_divergence') {
          this.layer.addLayer(
            L.circle([lat, lon], {
              radius: 9000,
              color: '#ef4444',
              weight: 1.5,
              fillOpacity: 0.12,
              dashArray: '6 6',
            }),
          );
        } else if (kind === 'sar_unknown_high') {
          // Pulsing ring for high-priority unknown
          this.layer.addLayer(
            L.circle([lat, lon], {
              radius: 8000,
              color: '#ef4444',
              weight: 1.5,
              fillOpacity: 0.12,
              dashArray: '6 6',
            }),
          );
        } else if (isPfz) {
          this.layer!.addLayer(
            L.circle([lat, lon], {
              radius: 12000,
              color: c.color,
              weight: 1,
              fillOpacity: 0.08,
              dashArray: '4 4',
            }),
          );
        }
      } else if (geom.type === 'LineString') {
        const isImbl = kind === 'imbl_line';
        const isPfzLine = kind === 'pfz_line';
        const latlngs = (geom.coordinates as [number, number][]).map(
          ([lon, lat]) => [lat, lon] as [number, number],
        );
        shape = L.polyline(latlngs, {
          color: isImbl ? '#f87171' : c.color,
          weight: isPfzLine ? 1.5 : isImbl ? 2.5 : 3,
          dashArray: isPfzLine ? '3 5' : isImbl ? '8 6' : '6 6',
          opacity: isImbl ? 0.9 : isPfzLine ? 0.85 : 0.85,
        });
      } else if (geom.type === 'Polygon') {
        const rings = (geom.coordinates as [number, number][][]).map((ring) =>
          ring.map(([lon, lat]) => [lat, lon] as [number, number]),
        );
        shape = L.polygon(rings, {
          color: c.color,
          fillColor: c.fill,
          fillOpacity: 0.25,
          weight: 2,
        });
      }

      if (shape) {
        shape.bindPopup(this.popupHtml(f.properties ?? {}, kind, f.geometry));
        this.layer.addLayer(shape);
      }
    }
  }

  private geoDistKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const R = 6371;
    const p1 = (lat1 * Math.PI) / 180, p2 = (lat2 * Math.PI) / 180;
    const dp = p2 - p1, dl = ((lon2 - lon1) * Math.PI) / 180;
    const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  private geoBearingDeg(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const p1 = (lat1 * Math.PI) / 180, p2 = (lat2 * Math.PI) / 180;
    const dl = ((lon2 - lon1) * Math.PI) / 180;
    const y = Math.sin(dl) * Math.cos(p2);
    const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
    return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
  }

  private compassWord(deg: number): string {
    const points = ['North', 'North-East', 'East', 'South-East',
      'South', 'South-West', 'West', 'North-West'];
    return points[Math.round(deg / 45) % 8];
  }

  private coordLabel(lat: number, lon: number): string {
    const ns = lat < 0 ? 'S' : 'N';
    const ew = lon < 0 ? 'W' : 'E';
    return `${Math.abs(lat).toFixed(4)}° ${ns}, ${Math.abs(lon).toFixed(4)}° ${ew}`;
  }

  private popupHtml(p: any, kind?: string, geometry?: any): string {
    const row = (k: string, v: any) =>
      `<div style="font-size:11px;line-height:1.6;"><b>${k}</b>: ${String(v)}</div>`;

    if (kind === 'pfz_landing') {
      const zlat = p?.pfz_lat ?? null;
      const zlon = p?.pfz_lon ?? null;
      let dist: number | null = p?.distance_from_user_km ?? null;
      let bear: number | null = p?.bearing_from_user_deg ?? null;
      if ((dist == null || bear == null) && zlat != null && zlon != null && this.queryPoint) {
        const computed = this.geoDistKm(this.queryPoint.lat, this.queryPoint.lon, zlat, zlon);
        dist = dist ?? computed;
        bear = bear ?? this.geoBearingDeg(this.queryPoint.lat, this.queryPoint.lon, zlat, zlon);
      }
      const rows: string[] = [];
      if (p?.name) rows.push(row('Landing Centre', `${p.name}${p.state ? `, ${p.state}` : ''}`));
      if (dist != null) rows.push(row('Distance from you', `${dist.toFixed(1)} km`));
      if (bear != null) rows.push(row('Bearing', `${Math.round(bear)}° (${this.compassWord(bear)})`));
      if (p?.advisory_depth_m != null) rows.push(row('Water depth', `${p.advisory_depth_m} m`));
      if (zlat != null && zlon != null) rows.push(row('Coordinates', this.coordLabel(zlat, zlon)));
      rows.push(row('Source', '🛡️ Official INCOIS PFZ'));
      return `<div style="max-width:240px;">${rows.join('')}</div>`;
    }

    if (kind === 'pfz_primary') {
      const rows: string[] = [];
      if (p?.distance_km != null) rows.push(row('Distance from you', `${Number(p.distance_km).toFixed(1)} km`));
      if (p?.bearing_deg != null) {
        const b = Number(p.bearing_deg);
        rows.push(row('Bearing', `${Math.round(b)}° (${this.compassWord(b)})`));
      }
      if (geometry?.type === 'Point') {
        rows.push(row('Coordinates', this.coordLabel(geometry.coordinates[1], geometry.coordinates[0])));
      }
      rows.push(row('Source', '🛡️ Official INCOIS PFZ'));
      return `<div style="max-width:240px;">${rows.join('')}</div>`;
    }

    const rows = Object.entries(p)
      .filter(([, v]) => v !== null && v !== undefined && v !== '')
      .map(
        ([k, v]) =>
          `<div style="font-size:11px;line-height:1.5;"><b>${k}</b>: ${String(v).slice(0, 80)}</div>`,
      )
      .join('');
    return `<div style="max-width:220px;">${rows || 'ORCA feature'}</div>`;
  }

  private renderLegend(geojson: any): void {
    const legend = this.element.querySelector('#ocean-map-legend');
    if (!legend) return;
    const kinds = new Set<string>(
      (geojson?.features ?? []).map((f: any) => f.properties?.kind),
    );
    if (store.pfzLive) {
      kinds.add('pfz_line');
      kinds.add('landing_centre_issued');
      kinds.add('landing_centre');
    }
    const labels: Record<string, string> = {
      query_point: 'Query point',
      pfz_primary: 'Fishing zone',
      pfz_alternate: 'Alternate',
      fleet_recommended: 'Fleet ✓ Recommended',
      fleet_candidate: 'Fleet candidate',
      fleet_change: 'Fleet switch',
      wind_divergence: 'Wind divergence',
      route: 'Safe route',
      boundary_flag: 'Boundary flag',
      cap_hazard: 'IMD warning',
      sar_known: 'SAR Known vessel',
      sar_unknown: 'SAR Unknown vessel',
      sar_unknown_high: 'SAR Unknown HIGH',
      sar_low_confidence: 'SAR Low conf.',
      sar_other: 'SAR other',
      imbl_line: 'Maritime boundary',
    };
    if (store.pfzLive) {
      labels.pfz_line = 'INCOIS PFZ line';
      labels.landing_centre_issued = 'Landing centre · advisory';
      labels.landing_centre = 'Landing centre';
    }
    if (geojson?.features?.some?.((f: any) => f.properties?.kind === 'pfz_landing')) {
      labels.pfz_landing = 'Advisory centre';
    }
    legend.innerHTML = [...kinds]
      .filter((k) => labels[k])
      .map((k) => {
        const c = this.COLORS[k];
        return (
          `<span class="legend-item"><span class="legend-dot" ` +
          `style="background:${k === 'cap_hazard' ? c.fill : c.color};"></span>` +
          `${labels[k]}</span>`
        );
      })
      .join('');
  }
}
