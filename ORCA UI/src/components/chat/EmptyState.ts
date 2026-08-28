import { PROMPT_STARTERS } from '../../data/promptStarters';
import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';

export class EmptyState {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'orca-workspace-hero animate-fade-in';
    this.render();
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    this.element.innerHTML = `
      <!-- Hero Navigation Query Prompt -->
      <div class="hero-query-section">
        <h2 class="hero-main-title">How can I assist your navigation?</h2>

        <div class="quick-inquiry-pills">
          ${PROMPT_STARTERS.map(starter => `
            <button class="inquiry-pill-btn" data-prompt="${encodeURIComponent(starter.prompt)}" data-agent-id="${starter.agentId}">
              <span class="pill-icon">${ICONS[starter.icon] || ICONS.shield}</span>
              <span class="pill-text">${starter.title}</span>
            </button>
          `).join('')}
        </div>
      </div>

      <!-- Primary Operational Indicators (from DESIGN.md & code (7).html) -->
      <div class="operational-telemetry-grid">
        <!-- Safety Status Card -->
        <div class="telemetry-card">
          <div class="telemetry-card-header">
            <div class="telemetry-title">
              <span class="card-icon">${ICONS.shield}</span>
              <span class="label-caps">SAFETY STATUS</span>
            </div>
            <div class="status-pill safe">
              <span class="dot"></span>
              <span class="data-mono-bold">ALL CLEAR</span>
            </div>
          </div>
          <div class="telemetry-main-val">Safe to Sail</div>
          <div class="telemetry-meta">No severe gale or navigational hazard warnings active for Indian coastal waters</div>
        </div>

        <!-- Wind & Sea State Card -->
        <div class="telemetry-card">
          <div class="telemetry-card-header">
            <div class="telemetry-title">
              <span class="card-icon">${ICONS.compass}</span>
              <span class="label-caps">WIND & SEA STATE</span>
            </div>
            <div class="status-pill info">
              <span class="dot"></span>
              <span class="data-mono-bold">BF 4</span>
            </div>
          </div>
          <div class="telemetry-main-val">12 KTS <span class="unit-mono">WNW</span></div>
          <div class="telemetry-meta">Significant Wave Height: <strong>1.1m</strong> • Swell Period: <strong>6.8s</strong></div>
        </div>

        <!-- Potential Fishing Zone (PFZ) Card -->
        <div class="telemetry-card">
          <div class="telemetry-card-header">
            <div class="telemetry-title">
              <span class="card-icon">${ICONS.sparkles}</span>
              <span class="label-caps">FISHING ZONE (PFZ)</span>
            </div>
            <div class="status-pill safe">
              <span class="dot"></span>
              <span class="data-mono-bold">ACTIVE</span>
            </div>
          </div>
          <div class="telemetry-main-val">18.4 NM <span class="unit-mono">SW</span></div>
          <div class="telemetry-meta">High Chlorophyll-a frontal boundary • SST: <strong>27.8°C</strong></div>
        </div>
      </div>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    const pills = this.element.querySelectorAll('.inquiry-pill-btn');
    pills.forEach(pill => {
      pill.addEventListener('click', () => {
        const promptText = decodeURIComponent(pill.getAttribute('data-prompt') || '');
        const agentId = pill.getAttribute('data-agent-id');
        if (agentId) {
          store.selectAgent(agentId);
        }
        if (promptText) {
          store.sendMessage(promptText);
        }
      });
    });
  }
}
