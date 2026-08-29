import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';
import { PROMPT_STARTERS } from '../../data/promptStarters';

export class EmptyState {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'orca-workspace-hero animate-fade-in';
    this.render();
    store.subscribe(() => this.render());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const role = store.userCategory;
    const roleIcon = role?.badgeEmoji || '⚓';
    const roleName = role?.roleName || 'General Mariner';
    const roleTagline = role?.tagline || 'Coastal Weather, Beach Safety & Maritime Inquiries';

    this.element.innerHTML = `
      <!-- Hero Introduction -->
      <div class="orca-clean-hero">
        <div class="hero-brand-emblem">
          <div class="emblem-radar-glow">
            <span class="emblem-icon">🧭</span>
          </div>
        </div>

        <h1 class="hero-clean-title">Welcome to ORCA</h1>
        <p class="hero-clean-subtitle">
          AI-Powered Marine Intelligence &amp; Multi-Agent Coastal Reasoning
        </p>

        <!-- Active Operational Role Banner -->
        <div class="hero-role-badge-card" id="hero-role-card" title="Click to change your operational role">
          <div class="role-badge-left">
            <span class="role-icon">${roleIcon}</span>
            <div class="role-text-meta">
              <div class="role-badge-title">
                <span>Active Profile:</span>
                <strong>${roleName}</strong>
              </div>
              <div class="role-badge-desc">${roleTagline}</div>
            </div>
          </div>
          <button class="btn-hero-change-role" id="btn-hero-change-role">
            <span>Switch Role</span>
            <span>➔</span>
          </button>
        </div>

        <!-- 3 Core Capabilities (What ORCA Does) -->
        <div class="orca-capabilities-grid">
          <div class="capability-item">
            <div class="capability-icon-wrap" style="color:var(--status-safe); background:rgba(34, 197, 94, 0.1);">
              <span>🛡️</span>
            </div>
            <div class="capability-text">
              <h4>Safety &amp; Cyclone Verdicts</h4>
              <p>Real-time wave, wind gust, tide, and IMD storm hazard assessments calibrated for your craft.</p>
            </div>
          </div>

          <div class="capability-item">
            <div class="capability-icon-wrap" style="color:var(--primary); background:rgba(14, 124, 134, 0.12);">
              <span>🐟</span>
            </div>
            <div class="capability-text">
              <h4>Official INCOIS PFZ Advisories</h4>
              <p>Live satellite thermal ocean fronts and fish aggregation zones with distance &amp; compass bearing.</p>
            </div>
          </div>

          <div class="capability-item">
            <div class="capability-icon-wrap" style="color:#f59e0b; background:rgba(245, 158, 11, 0.12);">
              <span>🗺️</span>
            </div>
            <div class="capability-text">
              <h4>Coastal Routing &amp; SAR</h4>
              <p>Territorial border geofencing (IMBL/Sir Creek), Search &amp; Rescue drift tracking, and bathymetry.</p>
            </div>
          </div>
        </div>

        <!-- Quick Start Inquiries -->
        <div class="hero-starters-section">
          <div class="starters-header-label">
            <span>✨</span>
            <span>Suggested Questions to Start:</span>
          </div>

          <div class="quick-inquiry-pills">
            ${PROMPT_STARTERS.map(starter => `
              <button class="inquiry-pill-btn" data-prompt="${encodeURIComponent(starter.prompt)}" data-agent-id="${starter.agentId}">
                <span class="pill-icon">${ICONS[starter.icon] || '🧭'}</span>
                <div class="pill-text-col">
                  <span class="pill-text">${starter.title}</span>
                  <span class="pill-desc">${starter.description}</span>
                </div>
              </button>
            `).join('')}
          </div>
        </div>
      </div>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    // Switch Role Button
    this.element.querySelector('#btn-hero-change-role')?.addEventListener('click', (e) => {
      e.stopPropagation();
      store.toggleCategoryModal(true);
    });

    this.element.querySelector('#hero-role-card')?.addEventListener('click', () => {
      store.toggleCategoryModal(true);
    });

    // Prompt Starter Pills
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
