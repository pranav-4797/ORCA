import * as L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { store } from '../../store/appState';

/**
 * Operational sea map -- renders the /viz/{session} GeoJSON FeatureCollection
 * produced with every answer:
 *   query_point    blue dot          pfz_primary   green zone + ring
 *   pfz_alternate  pale green        route         dashed cyan LineString
 *   boundary_flag  red flag          cap_hazard    IMD warning polygon
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

  private readonly COLORS: Record<string, { color: string; fill: string }> = {
    query_point: { color: '#38bdf8', fill: '#38bdf8' },
    pfz_primary: { color: '#22c55e', fill: '#22c55e' },
    pfz_alternate: { color: '#86efac', fill: '#86efac' },
    route: { color: '#22d3ee', fill: 'none' },
    boundary_flag: { color: '#f87171', fill: '#f87171' },
    cap_hazard: { color: '#fbbf24', fill: '#f59e0b' },
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

    if (!geojson || !geojson.features || geojson.features.length === 0) {
      if (statusEl) statusEl.textContent = store.vizSessionId ? 'NO MAP DATA' : 'ASK A QUESTION';
      return;
    }
    if (geojson === this.lastGeojson) {
      // Same data, but the panel may have re-parented us -- resize only.
      this.map?.invalidateSize();
      return;
    }
    this.lastGeojson = geojson;
    if (statusEl) statusEl.textContent = `${geojson.session_id?.slice(0, 8) ?? ''}`;
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

    for (const f of geojson.features ?? []) {
      const kind: string = f.properties?.kind ?? '';
      const c = this.COLORS[kind] ?? { color: '#94a3b8', fill: '#94a3b8' };
      const geom = f.geometry;
      if (!geom) continue;

      let shape: L.Layer | null = null;
      if (geom.type === 'Point') {
        const [lon, lat] = geom.coordinates;
        shape = L.circleMarker([lat, lon], {
          radius: kind === 'query_point' ? 8 : 6,
          color: c.color,
          fillColor: c.fill,
          fillOpacity: 0.85,
          weight: 2,
        });
        if (kind.startsWith('pfz')) {
          // ~12 km visual ring around the recommended zone centre.
          this.layer.addLayer(
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
        const latlngs = (geom.coordinates as [number, number][]).map(
          ([lon, lat]) => [lat, lon] as [number, number],
        );
        shape = L.polyline(latlngs, {
          color: c.color,
          weight: 3,
          dashArray: '6 6',
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
        shape.bindPopup(this.popupHtml(f.properties ?? {}));
        this.layer.addLayer(shape);
      }
    }

    try {
      this.map.fitBounds(this.layer.getBounds().pad(0.25), { animate: false });
    } catch {
      /* no layers */
    }
  }

  private popupHtml(p: any): string {
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
      (geojson.features ?? []).map((f: any) => f.properties?.kind),
    );
    const labels: Record<string, string> = {
      query_point: 'Query point',
      pfz_primary: 'Fishing zone',
      pfz_alternate: 'Alternate',
      route: 'Safe route',
      boundary_flag: 'Boundary flag',
      cap_hazard: 'IMD warning',
    };
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
