import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';
import { AgentActivity } from './AgentActivity';
import { AgentSelector } from './AgentSelector';
import { OceanMap } from '../map/OceanMap';
import { VizChart } from '../map/VizChart';
import { showToast } from '../ui/Toast';

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
  }
}
