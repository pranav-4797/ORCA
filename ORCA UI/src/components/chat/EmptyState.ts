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
            <span class="emblem-icon">⚓</span>
          </div>
        </div>

        <h1 class="hero-clean-title">ORCA Marine Intelligence</h1>
        <p class="hero-clean-subtitle">
          Collaborative multi-agent maritime reasoning powered by INCOIS &amp; IMD
        </p>

        <!-- Active Operational Role Banner (Compact) -->
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
            <span>Change</span>
            <span>➔</span>
          </button>
        </div>

        <!-- Visual Quick Action Cards (1-Click Marine Queries) -->
        <div class="hero-actions-container">
          <div class="hero-actions-title">
            <span>⚡ Quick Actions</span>
          </div>

          <div class="hero-action-cards-grid">
            <button class="hero-action-card action-pfz" data-prompt="Where are the nearest official INCOIS PFZ fishing zones from Mumbai?">
              <div class="action-card-top">
                <span class="action-card-icon" style="background:rgba(14, 124, 134, 0.15); color:var(--primary);">🐟</span>
                <span class="action-card-badge">INCOIS LIVE</span>
              </div>
              <div class="action-card-title">Live Fishing Zones (PFZ)</div>
              <div class="action-card-desc">Find nearest high-catch thermal fronts with distance, bearing &amp; depth</div>
              <div class="action-card-cta">Ask PFZ ➔</div>
            </button>

            <button class="hero-action-card action-safety" data-prompt="Is it safe to sail today from Ratnagiri harbour? Check waves and wind.">
              <div class="action-card-top">
                <span class="action-card-icon" style="background:rgba(34, 197, 94, 0.15); color:var(--status-safe);">🛡️</span>
                <span class="action-card-badge">SAFETY CHECK</span>
              </div>
              <div class="action-card-title">Sea State &amp; Cyclone Verdict</div>
              <div class="action-card-desc">Real-time waves, wind gusts, tides &amp; IMD storm alerts for your vessel</div>
              <div class="action-card-cta">Check Safety ➔</div>
            </button>

            <button class="hero-action-card action-route" data-prompt="Plan a safe weather-aware route from Porbandar to Okha avoiding shallow waters.">
              <div class="action-card-top">
                <span class="action-card-icon" style="background:rgba(245, 158, 11, 0.15); color:#f59e0b);">🧭</span>
                <span class="action-card-badge">NAVIGATION</span>
              </div>
              <div class="action-card-title">Safe Route &amp; Geofencing</div>
              <div class="action-card-desc">A* weather-aware route avoiding international border limits &amp; shallow shoals</div>
              <div class="action-card-cta">Plan Route ➔</div>
            </button>

            <button class="hero-action-card action-forecast" data-prompt="Show 48-hour marine weather and wave forecast for Goa coast.">
              <div class="action-card-top">
                <span class="action-card-icon" style="background:rgba(59, 130, 246, 0.15); color:#3b82f6);">🌊</span>
                <span class="action-card-badge">48H FORECAST</span>
              </div>
              <div class="action-card-title">48-Hour Wave &amp; Wind Forecast</div>
              <div class="action-card-desc">Hourly wave period, swell directions, exceedance windows &amp; tides</div>
              <div class="action-card-cta">View Forecast ➔</div>
            </button>
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

    // Visual Quick Action Cards
    const actionCards = this.element.querySelectorAll('.hero-action-card');
    actionCards.forEach(card => {
      card.addEventListener('click', () => {
        const promptText = card.getAttribute('data-prompt');
        if (promptText) {
          store.sendMessage(promptText);
        }
      });
    });
  }
}
