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

  // Persistent DOM fix: track initialization and last panel state
  private _initialized = false;
  private _lastMapPanelOpen: boolean | null = null;
  private _mapContainer: HTMLElement | null = null;
  private _mapSection: HTMLElement | null = null;
  private _mapBody: HTMLElement | null = null;
  private _mapHeadRow: HTMLElement | null = null;
  private _mapToggleBtn: HTMLElement | null = null;
  private _headerEl: HTMLElement | null = null;
  private _contentEl: HTMLElement | null = null;
  private _sarContainer: HTMLElement | null = null;
  private _activityContainer: HTMLElement | null = null;
  private _selectorContainer: HTMLElement | null = null;
  private _personaContainer: HTMLElement | null = null;
  private _simulationAccordion: HTMLElement | null = null;

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

  private _buildSkeleton(): void {
    // Build once: header chrome + persistent content containers. Map children stay alive.
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
        <!-- SAR Boundary Monitor — Innovation #3 (Authority) -->
        <div id="sar-monitor-container"></div>
        <!-- Advanced Simulation & Stress Test Controls (Collapsed by default to eliminate clutter) -->
        <details class="simulation-accordion" style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:var(--radius-sm);padding:8px 12px;margin-bottom:12px;">
          <summary style="font-size:12px;font-weight:700;letter-spacing:0.04em;color:var(--text-secondary);cursor:pointer;user-select:none;text-transform:uppercase;display:flex;align-items:center;justify-content:space-between;">
            <span>⚙️ Simulation &amp; Stress Tests</span>
            <span style="font-size:10px;opacity:0.7;">Click to Expand</span>
          </summary>
          <div style="margin-top:12px;display:flex;flex-direction:column;gap:12px;">
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
        <div id="persona-container" style="padding:var(--space-3);background:var(--bg-card);border:1px solid var(--border-default);border-radius:var(--radius-md);"></div>
        <div id="activity-container"></div>
        <div id="selector-container"></div>
      </div>
    `;
    this._headerEl = this.element.querySelector('.agent-panel-header') as HTMLElement;
    this._contentEl = this.element.querySelector('.agent-panel-content') as HTMLElement;
    this._mapContainer = this.element.querySelector('#map-container') as HTMLElement;
    this._sarContainer = this.element.querySelector('#sar-monitor-container') as HTMLElement;
    this._activityContainer = this.element.querySelector('#activity-container') as HTMLElement;
    this._selectorContainer = this.element.querySelector('#selector-container') as HTMLElement;
    this._personaContainer = this.element.querySelector('#persona-container') as HTMLElement;
    this._simulationAccordion = this.element.querySelector('.simulation-accordion') as HTMLElement;

    // Create persistent map section once
    this._mapSection = document.createElement('div');
    this._mapSection.className = 'orca-map-section';
    this._mapHeadRow = document.createElement('div');
    this._mapHeadRow.className = 'map-section-head';
    this._mapHeadRow.innerHTML = `<span class="label-caps" style="color:var(--primary);display:flex;align-items:center;gap:6px;">${ICONS.compass} OPERATIONAL PICTURE</span>`;
    this._mapToggleBtn = document.createElement('button');
    this._mapToggleBtn.className = 'icon-btn map-toggle-btn';
    this._mapToggleBtn.addEventListener('click', () => {
      store.toggleMapPanel();
    });
    this._mapHeadRow.appendChild(this._mapToggleBtn);
    this._mapSection.appendChild(this._mapHeadRow);

    this._mapBody = document.createElement('div');
    this._mapBody.className = 'map-body';
    // Placeholder will be managed in _syncMapPanel
    this._mapSection.appendChild(this._mapBody);
    this._mapContainer.appendChild(this._mapSection);

    // Attach persistent activity/selector once
    if (this._activityContainer && !this._activityContainer.contains(this.agentActivity.getElement())) {
      this._activityContainer.appendChild(this.agentActivity.getElement());
    }
    if (this._selectorContainer && !this._selectorContainer.contains(this.agentSelector.getElement())) {
      this._selectorContainer.appendChild(this.agentSelector.getElement());
    }

    // Header close button delegation (bound once)
    this._headerEl?.querySelector('#btn-close-agent-panel')?.addEventListener('click', () => {
      const isMobile = window.innerWidth < 1280;
      if (isMobile) {
        store.toggleMobileAgentDrawer(false);
      } else {
        store.toggleAgentPanel(false);
      }
    });

    // Init SAR monitor once
    this._initSarMonitor();

    this._initialized = true;
  }

  private _initSarMonitor(): void {
    if (!this._sarContainer) return;
    if (this.sarMonitor) {
      if (!this._sarContainer.contains(this.sarMonitor.getElement())) {
        this._sarContainer.appendChild(this.sarMonitor.getElement());
      }
      return;
    }
    import('../sar/SARBoundaryMonitor').then(({ SARBoundaryMonitor }) => {
      this.sarMonitor = new SARBoundaryMonitor();
      const cont = this.element.querySelector('#sar-monitor-container');
      if (cont && this.sarMonitor && !cont.contains(this.sarMonitor.getElement())) {
        cont.appendChild(this.sarMonitor.getElement());
      }
    }).catch(() => {
      if (this._sarContainer && !this._sarContainer.querySelector('.sar-fallback')) {
        const fallback = document.createElement('div');
        fallback.className = 'sar-fallback';
        fallback.textContent = 'SAR Boundary Monitor unavailable';
        fallback.style.fontSize = '11px';
        fallback.style.color = 'var(--text-tertiary)';
        this._sarContainer.appendChild(fallback);
      }
    });
  }

  private _syncMapPanel(): void {
    if (!this._mapSection || !this._mapBody || !this._mapContainer || !this._mapHeadRow || !this._mapToggleBtn) return;

    const shouldOpen = !!store.mapPanelOpen;
    const wasOpen = this._lastMapPanelOpen;

    // Update toggle chrome via innerHTML only for the button (header chrome)
    (this._mapToggleBtn as HTMLElement).title = shouldOpen ? 'Collapse map & charts' : 'Expand map & charts';
    (this._mapToggleBtn as HTMLElement).innerHTML = shouldOpen ? ICONS.chevronDown : ICONS.chevronRight;

    // Update collapsed class on section (chrome)
    if (shouldOpen) this._mapSection.classList.remove('collapsed');
    else this._mapSection.classList.add('collapsed');

    // Persistent children: only move DOM when transition, not on unrelated store updates
    const needsTransition = wasOpen !== shouldOpen;

    if (needsTransition) {
      if (shouldOpen) {
        // Opening: ensure body is in section and map/chart are inside body
        if (!this._mapSection.contains(this._mapBody)) {
          this._mapSection.appendChild(this._mapBody);
        }
        // Ensure map/chart elements are inside body (check contains before append)
        if (this.oceanMap && this.vizChart) {
          const oceanEl = this.oceanMap.getElement();
          const vizEl = this.vizChart.getElement();
          if (oceanEl && !this._mapBody.contains(oceanEl)) {
            // Remove placeholder if present
            const ph = this._mapBody.querySelector('.viz-chart-empty');
            if (ph) ph.remove();
            this._mapBody.appendChild(oceanEl);
          }
          if (vizEl && !this._mapBody.contains(vizEl)) {
            this._mapBody.appendChild(vizEl);
          }
          // Refresh after panel is visible (double rAF + timeout in refreshLayout handles transition)
          try { (this.oceanMap as any)?.refreshLayout?.(); } catch {}
        } else {
          // Not yet loaded — show placeholder if not already there
          if (!this._mapBody.querySelector('.viz-chart-empty')) {
            const placeholder = document.createElement('div');
            placeholder.className = 'viz-chart-empty';
            placeholder.textContent = 'Loading operational picture…';
            // Clear any existing children that are not the placeholder
            // Keep body contains logic: only add placeholder if body empty
            if (this._mapBody.children.length === 0) this._mapBody.appendChild(placeholder);
          }
          void this.ensureMapsLoaded().then(() => {
            if (store.mapPanelOpen) {
              // Now that maps are loaded, ensure they are mounted without full rerender
              const oEl = this.oceanMap?.getElement();
              const vEl = this.vizChart?.getElement();
              if (oEl && this._mapBody && !this._mapBody.contains(oEl)) {
                const ph = this._mapBody.querySelector('.viz-chart-empty');
                if (ph) ph.remove();
                this._mapBody.appendChild(oEl);
              }
              if (vEl && this._mapBody && !this._mapBody.contains(vEl)) {
                this._mapBody.appendChild(vEl);
              }
              try { (this.oceanMap as any)?.refreshLayout?.(); } catch {}
            }
          });
        }
      } else {
        // Closing: keep map elements attached but hidden via collapsed class
        // Do NOT detach to avoid Leaflet size race — just hide via CSS
        // Optionally we could detach body, but spec says only move when transition
        // We keep body in DOM hidden; no remove needed
      }
      this._lastMapPanelOpen = shouldOpen;
    } else {
      // No transition: ensure map elements still correctly placed if this is first render after lazy load
      if (shouldOpen && this.oceanMap && this.vizChart && this._mapBody) {
        const oEl = this.oceanMap.getElement();
        const vEl = this.vizChart.getElement();
        // Only append if not already children — prevents churn
        if (oEl && !this._mapBody.contains(oEl)) {
          const ph = this._mapBody.querySelector('.viz-chart-empty');
          if (ph) ph.remove();
          this._mapBody.appendChild(oEl);
        }
        if (vEl && !this._mapBody.contains(vEl)) {
          this._mapBody.appendChild(vEl);
        }
        // If vizGeojson just arrived while panel was already open, OceanMap's own onState will fitBounds,
        // but we ensure size is valid (panel didn't detach)
        // No refreshLayout needed here unless size changed
      }
    }

    // Empty state handling: show placeholder when no viz, without destroying map
    if (this._mapBody) {
      const hasViz = !!store.vizGeojson;
      let emptyCard = this._mapContainer?.querySelector('.empty-telemetry-panel-card') as HTMLElement | null;
      if (!hasViz) {
        if (!emptyCard) {
          emptyCard = document.createElement('div');
          emptyCard.className = 'empty-telemetry-panel-card';
          emptyCard.innerHTML = `
              <div class="empty-telemetry-icon">🛰️</div>
              <div class="empty-telemetry-title">Operations Map &amp; Telemetry</div>
              <div class="empty-telemetry-desc">
                Live INCOIS PFZ lines, wave/wind forecast charts, and boundary geofences will render dynamically here after you ask a question.
              </div>
          `;
          // Insert before mapSection so it shows when empty, but keep mapSection still in DOM hidden via collapsed? Actually keep both.
          // Spec wants map to open on first response, so empty card should be hidden once viz arrives.
          this._mapContainer.insertBefore(emptyCard, this._mapSection);
        }
        emptyCard.style.display = '';
        // When empty, mapSection may still be visible but will show no data — keep it
      } else {
        if (emptyCard) emptyCard.style.display = 'none';
      }
    }
  }

  private _updatePersona(activeAgent: any): void {
    if (!this._personaContainer) return;
    // Rebuild only this container's innerHTML (isolated, not wiping map)
    this._personaContainer.innerHTML = `
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
        ${activeAgent.capabilities.map((cap: string) => `<span class="cap-badge">${cap}</span>`).join('')}
      </div>
    `;
  }

  private render(): void {
    const isVisible = store.agentPanelOpen;
    const isMobileDrawer = store.mobileAgentDrawerOpen;
    const activeAgent = store.getActiveAgent();

    this.element.className = `agent-panel ${isVisible ? '' : 'hidden'} ${isMobileDrawer ? 'drawer-open' : ''}`;

    if (!this._initialized) {
      this._buildSkeleton();
    }

    // Update persona (isolated)
    this._updatePersona(activeAgent);

    // Sync persistent map panel (only moves DOM on transition)
    this._syncMapPanel();

    // Sync SAR monitor (ensure not re-added each time unnecessarily)
    this._initSarMonitor();

    // Ensure activity/selector stay mounted (check contains before append)
    if (this._activityContainer && !this._activityContainer.contains(this.agentActivity.getElement())) {
      this._activityContainer.appendChild(this.agentActivity.getElement());
    }
    if (this._selectorContainer && !this._selectorContainer.contains(this.agentSelector.getElement())) {
      this._selectorContainer.appendChild(this.agentSelector.getElement());
    }

    // Attach events for dynamic controls that are rebuilt (fleet/wind)
    // We keep simulation accordion static after skeleton, but need to wire buttons
    // Use a lightweight re-wire that doesn't duplicate listeners on map
    this.attachEvents();
  }

  private attachEvents(): void {
    // Close button is bound once in _buildSkeleton, but if we ever rebuild header, re-bind safely
    // For fleet/wind buttons inside simulation accordion, they are part of skeleton innerHTML that was built once,
    // but active state changes require re-render of button styles. Instead of rebuilding whole accordion,
    // we update button styles via query and ensure listeners are added once via delegation.

    // Use single delegated listener for fleet/wind to avoid duplicate per-render bindings
    // If already bound, skip
    if ((this as any)._eventsBound) return;
    (this as any)._eventsBound = true;

    this.element.addEventListener('click', async (e) => {
      const target = e.target as HTMLElement;
      // Fleet demo buttons
      const fleetBtn = target.closest('.fleet-demo-btn') as HTMLElement | null;
      if (fleetBtn) {
        const level = fleetBtn.getAttribute('data-level') || '';
        OrcaApiService.setFleetDemoLevel(level || null);
        if (level) {
          const sessionId = store.getActiveChat()?.id || store.activeChatId;
          let lat: number | undefined, lon: number | undefined;
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
        // Update button active styles without full rerender
        this.element.querySelectorAll('.fleet-demo-btn').forEach(b => {
          const l = (b as HTMLElement).getAttribute('data-level') || '';
          const isActive = l === (OrcaApiService.getFleetDemoLevel() || '');
          (b as HTMLElement).style.background = isActive ? 'var(--primary)' : '';
          (b as HTMLElement).style.color = isActive ? '#fff' : '';
        });
        this.refreshFleetStatus();
        return;
      }
      const windBtn = target.closest('.wind-demo-btn') as HTMLElement | null;
      if (windBtn) {
        const sc = windBtn.getAttribute('data-scenario') || '';
        OrcaApiService.setWindDemoScenario(sc || null);
        const label = sc ? `Wind demo set to ${sc} — next safety/PFZ query will show validation${sc==='high_divergence'?' ⚠ HIGH':sc==='match'?' (MATCH)':''}` : 'Cleared wind demo — back to Normal (live check only)';
        showToast(label, sc ? 'info' : 'success');
        this.element.querySelectorAll('.wind-demo-btn').forEach(b => {
          const s = (b as HTMLElement).getAttribute('data-scenario') || '';
          const isActive = s === (OrcaApiService.getWindDemoScenario() || '');
          (b as HTMLElement).style.background = isActive ? 'var(--primary)' : '';
          (b as HTMLElement).style.color = isActive ? '#fff' : '';
        });
        this.refreshWindStatus();
        return;
      }
      if (target.closest('#btn-fleet-clear')) {
        OrcaApiService.setFleetDemoLevel(null);
        try { await OrcaApiService.clearFleet(true); showToast('Cleared simulated fleet', 'success'); } catch { showToast('Cleared local demo', 'success'); }
        this.element.querySelectorAll('.fleet-demo-btn').forEach(b => {
          const l = (b as HTMLElement).getAttribute('data-level') || '';
          const isActive = l === '';
          (b as HTMLElement).style.background = isActive ? 'var(--primary)' : '';
          (b as HTMLElement).style.color = isActive ? '#fff' : '';
        });
        this.refreshFleetStatus();
        return;
      }
      if (target.closest('#btn-fleet-refresh')) {
        this.refreshFleetStatus();
        return;
      }
      if (target.closest('#btn-wind-clear')) {
        OrcaApiService.setWindDemoScenario(null);
        showToast('Cleared wind demo', 'success');
        this.element.querySelectorAll('.wind-demo-btn').forEach(b => {
          const s = (b as HTMLElement).getAttribute('data-scenario') || '';
          const isActive = s === '';
          (b as HTMLElement).style.background = isActive ? 'var(--primary)' : '';
          (b as HTMLElement).style.color = isActive ? '#fff' : '';
        });
        this.refreshWindStatus();
        return;
      }
      if (target.closest('#btn-wind-refresh')) {
        this.refreshWindStatus();
        return;
      }
      if (target.closest('#btn-close-agent-panel')) {
        const isMobile = window.innerWidth < 1280;
        if (isMobile) store.toggleMobileAgentDrawer(false);
        else store.toggleAgentPanel(false);
        return;
      }
    });

    // Auto-refresh statuses once per render (but not on every store update to avoid flood)
    // Use a throttled refresh
    if (!(this as any)._lastStatusRefresh || Date.now() - (this as any)._lastStatusRefresh > 5000) {
      (this as any)._lastStatusRefresh = Date.now();
      this.refreshFleetStatus();
      this.refreshWindStatus();
    }
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
