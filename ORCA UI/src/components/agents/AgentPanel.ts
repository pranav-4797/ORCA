import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';
import { AgentActivity } from './AgentActivity';
import { AgentSelector } from './AgentSelector';
import { OceanMap } from '../map/OceanMap';
import { VizChart } from '../map/VizChart';
import { showToast } from '../ui/Toast';
import { OrcaApiService } from '../../services/orcaApiService';

export class AgentPanel {
  private element: HTMLElement;
  private agentActivity: AgentActivity;
  private agentSelector: AgentSelector;
  private oceanMap: OceanMap;
  private vizChart: VizChart;

  constructor() {
    this.element = document.createElement('aside');
    this.element.className = 'agent-panel';
    this.agentActivity = new AgentActivity();
    this.agentSelector = new AgentSelector();
    this.oceanMap = new OceanMap();
    this.vizChart = new VizChart();
    this.render();
    store.subscribe(() => this.render());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const isVisible = store.agentPanelOpen;
    const isMobileDrawer = store.mobileAgentDrawerOpen;
    const activeAgent = store.getActiveAgent();

    this.element.className = `agent-panel ${isVisible ? '' : 'hidden'} ${isMobileDrawer ? 'drawer-open' : ''}`;

    this.element.innerHTML = `
      <div class="agent-panel-header">
        <div class="agent-panel-title">
          <span style="color:var(--primary);">${ICONS.compass}</span>
          <span class="label-caps" style="font-weight:700;">TELEMETRY &amp; ADVISORY</span>
        </div>
        <button class="icon-btn" id="btn-close-agent-panel" title="Close Panel" aria-label="Close Panel">
          ${ICONS.x}
        </button>
      </div>

      <div class="agent-panel-content">
        <!-- Operational picture: live map + hourly series for the last answer -->
        <div id="map-container"></div>

        <!-- Live AIS Vessel Telemetry Widget — STATIC DEMO placeholders, not live query state -->
        <div class="orca-telemetry-widget" data-demo-widget="ais-telemetry" title="Static demo telemetry — live ocean state appears in message HUD after query">
          <div class="widget-section-header">
            <span class="label-caps">LIVE AIS TELEMETRY — DEMO</span>
            <span class="status-pill safe">
              <span class="dot"></span>
              <span class="data-mono-bold">ACTIVE</span>
            </span>
          </div>

          <div class="telemetry-data-grid">
            <div class="data-cell">
              <span class="cell-label">MMSI / IMO</span>
              <span class="cell-val-mono">419001234 / 9432810</span>
            </div>
            <div class="data-cell">
              <span class="cell-label">CURRENT POSITION</span>
              <span class="cell-val-mono">18°55.20'N, 72°50.15'E</span>
            </div>
            <div class="data-cell">
              <span class="cell-label">SOG (SPEED)</span>
              <span class="cell-val-mono">14.2 KTS</span>
            </div>
            <div class="data-cell">
              <span class="cell-label">COG (HEADING)</span>
              <span class="cell-val-mono">218° (SW)</span>
            </div>
            <div class="data-cell">
              <span class="cell-label">VESSEL DRAFT</span>
              <span class="cell-val-mono">12.4m</span>
            </div>
            <div class="data-cell">
              <span class="cell-label">DYNAMIC UKC</span>
              <span class="cell-val-mono" style="color:var(--status-safe);font-weight:700;">+4.6m (SAFE)</span>
            </div>
          </div>
        </div>

        <!-- Environmental & Oceanographic Sensor Ingestion — STATIC DEMO -->
        <div class="orca-telemetry-widget" data-demo-widget="ocean-sensors" title="Static demo — see message verdict for live data">
          <div class="widget-section-header">
            <span class="label-caps">INCOIS / IMD OCEAN SENSORS — DEMO</span>
            <span class="data-mono-sm" style="color:var(--text-tertiary);">STATIC DEMO</span>
          </div>

          <div class="telemetry-data-grid">
            <div class="data-cell">
              <span class="cell-label">SEA SURFACE TEMP (SST)</span>
              <span class="cell-val-mono">27.8°C</span>
            </div>
            <div class="data-cell">
              <span class="cell-label">SIGNIFICANT WAVE (SWH)</span>
              <span class="cell-val-mono">1.1m (SLIGHT)</span>
            </div>
            <div class="data-cell">
              <span class="cell-label">BAROMETRIC PRESSURE</span>
              <span class="cell-val-mono">1012.4 hPa</span>
            </div>
            <div class="data-cell">
              <span class="cell-label">TIDAL CYCLE</span>
              <span class="cell-val-mono">RISING FLOOD (+3.2m)</span>
            </div>
          </div>
        </div>

        <!-- Fleet Convergence Forecast — Innovation #1 -->
        <div class="orca-telemetry-widget" id="fleet-convergence-widget" style="border-left:3px solid var(--primary);">
          <div class="widget-section-header">
            <span class="label-caps" style="display:flex;align-items:center;gap:6px;">${ICONS.sparkles} FLEET CONVERGENCE FORECAST</span>
            <span class="status-pill info" id="fleet-status-pill">
              <span class="dot"></span>
              <span class="data-mono-bold" id="fleet-status-text">CHECKING</span>
            </span>
          </div>
          <div style="font-size:11px;color:var(--text-secondary);margin-bottom:8px;line-height:1.4;">
            ORCA detects when its own recommendations concentrate fleet &amp; adjusts toward less-crowded, similarly suitable zones. <span style="color:var(--text-tertiary);">Safety &amp; legal always override.</span>
          </div>
          <div class="fleet-demo-controls" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;">
            <button class="cap-badge fleet-demo-btn" data-level="" style="cursor:pointer;${!OrcaApiService.getFleetDemoLevel() ? 'background:var(--primary);color:#fff;' : ''}">Normal</button>
            <button class="cap-badge fleet-demo-btn" data-level="low" style="cursor:pointer;${OrcaApiService.getFleetDemoLevel()==='low' ? 'background:var(--primary);color:#fff;' : ''}">Low (2)</button>
            <button class="cap-badge fleet-demo-btn" data-level="medium" style="cursor:pointer;${OrcaApiService.getFleetDemoLevel()==='medium' ? 'background:var(--primary);color:#fff;' : ''}">Medium (5)</button>
            <button class="cap-badge fleet-demo-btn" data-level="high" style="cursor:pointer;${OrcaApiService.getFleetDemoLevel()==='high' ? 'background:var(--primary);color:#fff;' : ''}">High (10)</button>
            <button class="cap-badge fleet-demo-btn" data-level="severe" style="cursor:pointer;${OrcaApiService.getFleetDemoLevel()==='severe' ? 'background:var(--primary);color:#fff;' : ''}">Severe (20+)</button>
          </div>
          <div style="display:flex;gap:4px;">
            <button class="icon-btn" id="btn-fleet-clear" title="Clear simulated fleet" style="font-size:11px;padding:4px 8px;width:auto;height:auto;">Clear Simulation</button>
            <button class="icon-btn" id="btn-fleet-refresh" title="Refresh fleet status" style="font-size:11px;padding:4px 8px;width:auto;height:auto;">↻ Refresh</button>
          </div>
          <div id="fleet-status-detail" style="font-size:11px;color:var(--text-tertiary);margin-top:6px;max-height:60px;overflow-y:auto;"></div>
          <div style="font-size:10px;color:var(--text-tertiary);margin-top:4px;">Window 6h • Radius 15km • Target 8 vessels • Penalty max 50% • <em>DEMO — SIMULATED Fleet Activity</em> when highlighted</div>
        </div>

        <!-- Active Advisory Persona Info -->
        <div style="padding:var(--space-3);background:var(--bg-card);border:1px solid var(--border-default);border-radius:var(--radius-md);">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <div style="width:30px;height:30px;border-radius:var(--radius-sm);background:${activeAgent.avatarBg};color:${activeAgent.avatarColor};display:flex;align-items:center;justify-content:center;">
              ${ICONS[activeAgent.icon] || ICONS.compass}
            </div>
            <div>
              <div style="font-weight:600;font-size:var(--text-sm);color:var(--text-primary);">${activeAgent.name}</div>
              <div class="data-mono-sm" style="color:var(--text-tertiary);">${activeAgent.role}</div>
            </div>
          </div>
          <p style="font-size:12px;color:var(--text-secondary);line-height:1.45;margin-bottom:8px;">${activeAgent.description}</p>
          <div style="display:flex;flex-wrap:wrap;gap:4px;">
            ${activeAgent.capabilities.map(cap => `<span class="cap-badge">${cap}</span>`).join('')}
          </div>
        </div>

        <!-- Execution Steps Activity Container -->
        <div id="activity-container"></div>

        <!-- Advisory Modules List -->
        <div id="selector-container"></div>
      </div>
    `;

    const mapContainer = this.element.querySelector('#map-container');
    if (mapContainer) {
      const section = document.createElement('div');
      section.className = 'orca-map-section';
      if (!store.mapPanelOpen) section.classList.add('collapsed');

      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'icon-btn map-toggle-btn';
      toggleBtn.title = store.mapPanelOpen ? 'Collapse map & charts' : 'Expand map & charts';
      toggleBtn.innerHTML = store.mapPanelOpen ? ICONS.chevronDown : ICONS.chevronRight;
      toggleBtn.addEventListener('click', () => {
        store.toggleMapPanel();
        return;
      });
      const headRow = document.createElement('div');
      headRow.className = 'map-section-head';
      headRow.innerHTML = `<span class="label-caps" style="color:var(--primary);display:flex;align-items:center;gap:6px;">${ICONS.compass} OPERATIONAL PICTURE</span>`;
      headRow.appendChild(toggleBtn);
      section.appendChild(headRow);

      if (store.mapPanelOpen) {
        const body = document.createElement('div');
        body.appendChild(this.oceanMap.getElement());
        body.appendChild(this.vizChart.getElement());
        section.appendChild(body);
      }
      mapContainer.appendChild(section);
    }

    const activityContainer = this.element.querySelector('#activity-container');
    if (activityContainer) {
      activityContainer.appendChild(this.agentActivity.getElement());
    }

    const selectorContainer = this.element.querySelector('#selector-container');
    if (selectorContainer) {
      selectorContainer.appendChild(this.agentSelector.getElement());
    }

    this.attachEvents();
  }

  private attachEvents(): void {
    this.element.querySelector('#btn-close-agent-panel')?.addEventListener('click', () => {
      const isMobile = window.innerWidth < 1280;
      if (isMobile) {
        store.toggleMobileAgentDrawer(false);
      } else {
        store.toggleAgentPanel(false);
      }
    });

    // Fleet Convergence demo controls
    const fleetBtns = this.element.querySelectorAll('.fleet-demo-btn');
    fleetBtns.forEach(btn => {
      btn.addEventListener('click', async () => {
        const level = (btn as HTMLElement).getAttribute('data-level') || '';
        OrcaApiService.setFleetDemoLevel(level || null);
        if (level) {
          // Try to simulate fleet around last PFZ if available, else just set level for next query
          const sessionId = store.getActiveChat()?.id || store.activeChatId;
          let lat: number | undefined, lon: number | undefined;
          // Try to get from last viz geojson
          const gj = (store as any).vizGeojson;
          if (gj?.features) {
            const pfz = gj.features.find((f:any)=>f.properties?.kind==='pfz_primary' || f.properties?.kind==='fleet_recommended');
            if (pfz?.geometry?.coordinates) {
              lon = pfz.geometry.coordinates[0];
              lat = pfz.geometry.coordinates[1];
            }
          }
          try {
            if (lat != null && lon != null) {
              await OrcaApiService.simulateFleet(level, lat, lon, sessionId || undefined);
              showToast(`Simulated ${level} fleet (${level==='low'?2:level==='medium'?5:level==='high'?10:20} vessels) — next PFZ query will show crowding`, 'info');
            } else {
              showToast(`Fleet demo set to ${level || 'Normal'} — next PFZ query near your location will show convergence`, 'info');
            }
          } catch {
            showToast(`Fleet demo set to ${level} (backend simulate failed, will still affect next query)`, 'info');
          }
        } else {
          try { await OrcaApiService.clearFleet(true); } catch {}
          showToast('Cleared simulated fleet — back to Normal', 'success');
        }
        this.render();
      });
    });
    this.element.querySelector('#btn-fleet-clear')?.addEventListener('click', async () => {
      OrcaApiService.setFleetDemoLevel(null);
      try { await OrcaApiService.clearFleet(true); showToast('Cleared simulated fleet', 'success'); } catch { showToast('Cleared local demo', 'success'); }
      this.render();
    });
    this.element.querySelector('#btn-fleet-refresh')?.addEventListener('click', () => {
      this.refreshFleetStatus();
    });
    // Auto-refresh fleet status once per render
    this.refreshFleetStatus();
  }

  private async refreshFleetStatus(): Promise<void> {
    const statusText = this.element.querySelector('#fleet-status-text') as HTMLElement | null;
    const detail = this.element.querySelector('#fleet-status-detail') as HTMLElement | null;
    if (!statusText) return;
    try {
      const s = await OrcaApiService.getFleetStatus();
      const total = s.total_recent ?? 0;
      const real = s.real_count ?? 0;
      const sim = s.simulated_count ?? 0;
      const mode = sim > 0 && real === 0 ? 'SIMULATED' : sim > 0 ? 'MIXED' : real > 0 ? 'REAL' : 'EMPTY';
      statusText.textContent = total > 0 ? `${total} recent (${mode})` : 'NO DATA';
      if (detail) {
        const recent = (s.recent || []).slice(0,4).map((r:any)=>`${r.zone_lat.toFixed(2)},${r.zone_lon.toFixed(2)} ${r.is_simulated?'SIM':''}`).join(' • ') || 'No recent fleet activity — recommendations will show raw suitability';
        detail.textContent = `Real ${real} • Simulated ${sim} • Window ${s.window_hours}h • ${recent}`;
      }
      const pill = this.element.querySelector('#fleet-status-pill') as HTMLElement | null;
      if (pill) {
        pill.className = `status-pill ${total>0 ? (mode==='SIMULATED'?'info':'safe') : 'info'}`;
      }
    } catch {
      if (statusText) statusText.textContent = 'UNAVAILABLE';
      if (detail) detail.textContent = 'Fleet data unavailable — showing raw suitability';
    }
  }
}
