import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';
import { AgentActivity } from './AgentActivity';
import { AgentSelector } from './AgentSelector';
import { showToast } from '../ui/Toast';
import { OrcaApiService } from '../../services/orcaApiService';

export class AgentPanel {
  private element: HTMLElement;
  private agentActivity: AgentActivity;
  private agentSelector: AgentSelector;
  private oceanMap: any = null;
  private vizChart: any = null;
  private sarMonitor: any = null;
  private mapsLoading = false;
  private mapsLoadPromise: Promise<void> | null = null;

  constructor() {
    this.element = document.createElement('aside');
    this.element.className = 'agent-panel';
    this.agentActivity = new AgentActivity();
    this.agentSelector = new AgentSelector();
    // Lazy-load heavy map/chart components on demand (Task 11)
    // Do not instantiate OceanMap/VizChart here — they pull in leaflet (~150kB) and are not needed for initial paint
    this.render();
    store.subscribe(() => this.render());
  }

  private async ensureMapsLoaded(): Promise<void> {
    if (this.oceanMap && this.vizChart) return;
    if (this.mapsLoadPromise) return this.mapsLoadPromise;
    this.mapsLoading = true;
    this.mapsLoadPromise = (async () => {
      const [{ OceanMap }, { VizChart }] = await Promise.all([
        import('../map/OceanMap'),
        import('../map/VizChart'),
      ]);
      this.oceanMap = new OceanMap();
      this.vizChart = new VizChart();
      this.mapsLoading = false;
    })();
    return this.mapsLoadPromise;
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
        <div id="map-container">
          ${!store.vizGeojson ? `
            <div class="empty-telemetry-panel-card">
              <div class="empty-telemetry-icon">🛰️</div>
              <div class="empty-telemetry-title">Operations Map &amp; Telemetry</div>
              <div class="empty-telemetry-desc">
                Live INCOIS PFZ lines, wave/wind forecast charts, and boundary geofences will render dynamically here after you ask a question.
              </div>
            </div>
          ` : ''}
        </div>

        <!-- SAR Boundary Monitor — Innovation #3 (Authority) -->
        <div id="sar-monitor-container"></div>

        <!-- Advanced Simulation & Stress Test Controls (Collapsed by default to eliminate clutter) -->
        <details class="simulation-accordion" style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:var(--radius-sm);padding:8px 12px;margin-bottom:12px;">
          <summary style="font-size:12px;font-weight:700;letter-spacing:0.04em;color:var(--text-secondary);cursor:pointer;user-select:none;text-transform:uppercase;display:flex;align-items:center;justify-content:space-between;">
            <span>⚙️ Simulation &amp; Stress Tests</span>
            <span style="font-size:10px;opacity:0.7;">Click to Expand</span>
          </summary>

          <div style="margin-top:12px;display:flex;flex-direction:column;gap:12px;">
            <!-- Fleet Convergence Forecast — Innovation #1 -->
            <div class="orca-telemetry-widget" id="fleet-convergence-widget" style="border-left:3px solid var(--primary);margin:0;">
              <div class="widget-section-header">
                <span class="label-caps" style="display:flex;align-items:center;gap:6px;">${ICONS.sparkles} FLEET CONVERGENCE</span>
                <span class="status-pill info" id="fleet-status-pill">
                  <span class="dot"></span>
                  <span class="data-mono-bold" id="fleet-status-text">CHECKING</span>
                </span>
              </div>
              <div style="font-size:11px;color:var(--text-secondary);margin-bottom:8px;line-height:1.4;">
                Crowding-adjusted PFZ recommendations.
              </div>
              <div class="fleet-demo-controls" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;">
                <button class="cap-badge fleet-demo-btn" data-level="" style="cursor:pointer;${!OrcaApiService.getFleetDemoLevel() ? 'background:var(--primary);color:#fff;' : ''}">Normal</button>
                <button class="cap-badge fleet-demo-btn" data-level="low" style="cursor:pointer;${OrcaApiService.getFleetDemoLevel()==='low' ? 'background:var(--primary);color:#fff;' : ''}">Low (2)</button>
                <button class="cap-badge fleet-demo-btn" data-level="medium" style="cursor:pointer;${OrcaApiService.getFleetDemoLevel()==='medium' ? 'background:var(--primary);color:#fff;' : ''}">Medium (5)</button>
                <button class="cap-badge fleet-demo-btn" data-level="high" style="cursor:pointer;${OrcaApiService.getFleetDemoLevel()==='high' ? 'background:var(--primary);color:#fff;' : ''}">High (10)</button>
                <button class="cap-badge fleet-demo-btn" data-level="severe" style="cursor:pointer;${OrcaApiService.getFleetDemoLevel()==='severe' ? 'background:var(--primary);color:#fff;' : ''}">Severe (20+)</button>
              </div>
              <div style="display:flex;gap:4px;">
                <button class="icon-btn" id="btn-fleet-clear" title="Clear simulated fleet" style="font-size:11px;padding:4px 8px;width:auto;height:auto;">Clear</button>
                <button class="icon-btn" id="btn-fleet-refresh" title="Refresh fleet status" style="font-size:11px;padding:4px 8px;width:auto;height:auto;">↻ Refresh</button>
              </div>
              <div id="fleet-status-detail" style="font-size:11px;color:var(--text-tertiary);margin-top:6px;max-height:60px;overflow-y:auto;"></div>
            </div>

            <!-- Wind Validation — Innovation #4 (Satellite–Model Divergence) -->
            <div class="orca-telemetry-widget" id="wind-validation-widget" style="border-left:3px solid #0ea5e9;margin:0;">
              <div class="widget-section-header">
                <span class="label-caps" style="display:flex;align-items:center;gap:6px;">🌬️ SATELLITE WIND DIVERGENCE</span>
                <span class="status-pill info" id="wind-status-pill">
                  <span class="dot"></span>
                  <span class="data-mono-bold" id="wind-status-text">CHECKING</span>
                </span>
              </div>
              <div style="font-size:11px;color:var(--text-secondary);margin-bottom:8px;line-height:1.4;">
                Compares forecast model with MOSDAC satellite scatterometer.
              </div>
              <div class="wind-demo-controls" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px;">
                <button class="cap-badge wind-demo-btn" data-scenario="" style="cursor:pointer;${!OrcaApiService.getWindDemoScenario() ? 'background:var(--primary);color:#fff;' : ''}">Normal</button>
                <button class="cap-badge wind-demo-btn" data-scenario="match" style="cursor:pointer;${OrcaApiService.getWindDemoScenario()==='match' ? 'background:var(--primary);color:#fff;' : ''}">Match</button>
                <button class="cap-badge wind-demo-btn" data-scenario="moderate" style="cursor:pointer;${OrcaApiService.getWindDemoScenario()==='moderate' ? 'background:var(--primary);color:#fff;' : ''}">Moderate</button>
                <button class="cap-badge wind-demo-btn" data-scenario="high_divergence" style="cursor:pointer;${OrcaApiService.getWindDemoScenario()==='high_divergence' ? 'background:var(--primary);color:#fff;' : ''}">High</button>
              </div>
              <div style="display:flex;gap:4px;">
                <button class="icon-btn" id="btn-wind-clear" title="Clear wind demo" style="font-size:11px;padding:4px 8px;width:auto;height:auto;">Clear</button>
                <button class="icon-btn" id="btn-wind-refresh" title="Refresh satellite wind status" style="font-size:11px;padding:4px 8px;width:auto;height:auto;">↻ Refresh</button>
              </div>
              <div id="wind-status-detail" style="font-size:11px;color:var(--text-tertiary);margin-top:6px;max-height:60px;overflow-y:auto;"></div>
            </div>
          </div>
        </details>


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

    const sarContainer = this.element.querySelector('#sar-monitor-container');
    if (sarContainer) {
      if (!this.sarMonitor) {
        import('../sar/SARBoundaryMonitor').then(({ SARBoundaryMonitor }) => {
          this.sarMonitor = new SARBoundaryMonitor();
          const cont = this.element.querySelector('#sar-monitor-container');
          if (cont && this.sarMonitor) {
            cont.appendChild(this.sarMonitor.getElement());
          }
        }).catch(() => {
          const fallback = document.createElement('div');
          fallback.textContent = 'SAR Boundary Monitor unavailable';
          fallback.style.fontSize = '11px';
          fallback.style.color = 'var(--text-tertiary)';
          sarContainer.appendChild(fallback);
        });
      } else {
        sarContainer.appendChild(this.sarMonitor.getElement());
      }
    }

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
        if (this.oceanMap && this.vizChart) {
          body.appendChild(this.oceanMap.getElement());
          body.appendChild(this.vizChart.getElement());
        } else {
          const placeholder = document.createElement('div');
          placeholder.className = 'viz-chart-empty';
          placeholder.textContent = 'Loading operational picture…';
          body.appendChild(placeholder);
          this.ensureMapsLoaded().then(() => {
            if (store.mapPanelOpen) this.render();
          });
        }
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
    // Wind validation demo controls
    const windBtns = this.element.querySelectorAll('.wind-demo-btn');
    windBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const sc = (btn as HTMLElement).getAttribute('data-scenario') || '';
        OrcaApiService.setWindDemoScenario(sc || null);
        const label = sc ? `Wind demo set to ${sc} — next safety/PFZ query will show validation${sc==='high_divergence'?' ⚠ HIGH':sc==='match'?' (MATCH)':''}` : 'Cleared wind demo — back to Normal (live check only)';
        showToast(label, sc ? 'info' : 'success');
        this.render();
      });
    });
    this.element.querySelector('#btn-wind-clear')?.addEventListener('click', () => {
      OrcaApiService.setWindDemoScenario(null);
      showToast('Cleared wind demo', 'success');
      this.render();
    });
    this.element.querySelector('#btn-wind-refresh')?.addEventListener('click', () => this.refreshWindStatus());
    // Auto-refresh statuses once per render
    this.refreshFleetStatus();
    this.refreshWindStatus();
  }

  private async refreshWindStatus(): Promise<void> {
    const statusText = this.element.querySelector('#wind-status-text') as HTMLElement | null;
    const detail = this.element.querySelector('#wind-status-detail') as HTMLElement | null;
    const badge = this.element.querySelector('#wind-real-badge') as HTMLElement | null;
    if (!statusText) return;
    try {
      const s = await OrcaApiService.getSatelliteWindStatus();
      const activated = !!s.real_provider_activated;
      const demo = OrcaApiService.getWindDemoScenario();
      if (demo) statusText.textContent = `${demo.toUpperCase()} (DEMO)`;
      else statusText.textContent = activated ? 'REAL ACTIVE' : 'DEMO ONLY';
      if (detail) {
        const m = s.moderate_threshold_kmh ?? 9;
        const h = s.high_threshold_kmh ?? 15;
        detail.textContent = `${s.real_provider} — activated=${activated} • thresholds ${m}/${h} km/h • TTL ${s.obs_ttl_s}s • max ${s.max_spatial_km}km/${s.max_age_min}min`;
      }
      if (badge) badge.textContent = activated ? 'REAL SATELLITE DATA' : 'DEMO — SIMULATED SATELLITE DATA';
      const pill = this.element.querySelector('#wind-status-pill') as HTMLElement | null;
      if (pill) pill.className = `status-pill ${demo ? (demo==='high_divergence'?'critical':'info') : activated ? 'safe' : 'info'}`;
    } catch {
      if (statusText) statusText.textContent = 'UNAVAILABLE';
      if (detail) detail.textContent = 'Wind validation unavailable';
    }
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
