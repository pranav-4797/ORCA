import { store } from '../../store/appState';
import { USER_CATEGORIES, UserCategoryConfig, UserCategoryKey } from '../../types/userCategory';
import { ICONS } from '../../utils/icons';
import { showToast } from '../ui/Toast';

export class RoleSelectionPage {
  private element: HTMLElement;
  private selectedCategoryKey: UserCategoryKey = 'general_user';
  private isSaving: boolean = false;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'orca-role-page';
    if (store.userCategory?.category) {
      this.selectedCategoryKey = store.userCategory.category;
    }
    this.render();
    store.subscribe(() => {
      if (store.userCategory?.category && !this.selectedCategoryKey) {
        this.selectedCategoryKey = store.userCategory.category;
      }
      this.render();
    });
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const lang = store.activeLanguage || 'en';
    const user = store.currentUser;
    const currentCategory = USER_CATEGORIES.find(c => c.key === this.selectedCategoryKey) || USER_CATEGORIES[0];
    const canCancel = !!store.userCategory;

    this.element.innerHTML = `
      <!-- Background Nautical Overlay -->
      <div class="login-nautical-bg"></div>

      <!-- Role Page Header -->
      <header class="role-top-bar">
        <div class="role-top-brand">
          <div class="role-brand-logo">
            <span class="brand-anchor-icon">⚓</span>
            <div class="brand-text-col">
              <span class="brand-main-title">ORCA</span>
              <span class="brand-sub-title">Role Calibration</span>
            </div>
          </div>
          <div class="role-step-pill">
            <span>STEP 2 OF 2 • MARITIME CLASSIFICATION</span>
          </div>
        </div>

        <div class="role-top-actions">
          <!-- Officer Identity Pill -->
          ${user ? `
            <div class="role-officer-pill" title="Signed in as ${user.email}">
              ${user.photoURL ? `
                <img src="${user.photoURL}" alt="Avatar" class="officer-pill-avatar" />
              ` : `
                <div class="officer-pill-avatar-fallback">${(user.displayName || user.email || 'OP').slice(0, 2).toUpperCase()}</div>
              `}
              <div class="officer-pill-meta">
                <span class="officer-pill-name">${user.displayName || 'Watch Officer'}</span>
                <span class="officer-pill-email">${user.email}</span>
              </div>
              <button class="btn-role-signout" id="btn-role-signout" title="Sign out / Switch Account">
                <span>Sign Out</span>
              </button>
            </div>
          ` : ''}
        </div>
      </header>

      <!-- Main Role Selection Stage -->
      <main class="role-main-stage">
        <div class="role-container">
          
          <!-- Hero Section -->
          <div class="role-hero-header">
            <div class="role-pre-badge">
              <span class="pulse-dot-cyan"></span>
              <span>OPERATIONAL PROFILE CONFIGURATION</span>
            </div>
            <h1 class="role-page-heading">
              Select Your Maritime Operational Role
            </h1>
            <p class="role-page-subtitle">
              ORCA automatically calibrates safety floors (wave height &amp; wind limits), INCOIS PFZ alerts, SAR border geofences, and multi-agent synthesis based on your vessel classification.
            </p>
          </div>

          <!-- Role Cards Grid -->
          <div class="role-cards-grid" role="radiogroup" aria-label="Select your maritime operational category">
            ${USER_CATEGORIES.map(cat => this.renderRoleCard(cat, cat.key === this.selectedCategoryKey)).join('')}
          </div>

          <!-- Selected Role Detail & Live Calibration Preview -->
          <div class="role-detail-panel">
            <div class="detail-panel-header">
              <div class="detail-icon-wrap">${currentCategory.icon}</div>
              <div class="detail-meta">
                <div class="detail-title-row">
                  <h2 class="detail-role-title">${currentCategory.name}</h2>
                  <span class="detail-vessel-badge">${currentCategory.vesselLabel}</span>
                </div>
                <p class="detail-tagline">${currentCategory.tagline}</p>
              </div>
            </div>

            <div class="detail-body-grid">
              <div class="detail-desc-col">
                <h3 class="detail-section-title">Operational Scope &amp; Safety Thresholds</h3>
                <p class="detail-description">${currentCategory.description}</p>
                <div class="detail-focus-tags">
                  ${currentCategory.focusBadges.map(b => `<span class="focus-tag-chip">✓ ${b}</span>`).join('')}
                </div>
              </div>

              <div class="detail-specs-col">
                <h3 class="detail-section-title">Vessel &amp; Agent Configuration</h3>
                <div class="specs-list">
                  <div class="spec-row">
                    <span class="spec-label">Vessel Class</span>
                    <span class="spec-val">${currentCategory.vesselClass.replace(/_/g, ' ').toUpperCase()}</span>
                  </div>
                  <div class="spec-row">
                    <span class="spec-label">Wave Height Floor</span>
                    <span class="spec-val highlight">${currentCategory.key === 'fisherman' ? '< 2.5m (Strict)' : currentCategory.key === 'trawler' ? '< 3.5m' : 'Calibrated'}</span>
                  </div>
                  <div class="spec-row">
                    <span class="spec-label">Primary Agent Priority</span>
                    <span class="spec-val">${currentCategory.key === 'fisherman' ? 'PFZ + Hazard' : currentCategory.key === 'coastal_guard' ? 'Geospatial + Hazard' : currentCategory.key === 'marine_scientist' ? 'Trend + Ocean-State' : 'Ocean-State + Routing'}</span>
                  </div>
                  <div class="spec-row">
                    <span class="spec-label">INCOIS Data Feeds</span>
                    <span class="spec-val">OSF SST, WW3 Waves, OceanSat-2</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Confirm / Cancel Actions -->
            <div class="role-action-bar">
              ${canCancel ? `
                <button class="btn-cancel-role" id="btn-cancel-role-switch">
                  <span>Cancel &amp; Return to Console</span>
                </button>
              ` : ''}
              <button class="btn-confirm-role-launch" id="btn-confirm-role-launch" ${this.isSaving ? 'disabled' : ''}>
                ${this.isSaving ? `
                  <div class="login-spinner"></div>
                  <span>Calibrating System Profile...</span>
                ` : `
                  <span>Confirm Profile &amp; Launch Command Console</span>
                  <span class="btn-arrow">➔</span>
                `}
              </button>
            </div>
          </div>

        </div>
      </main>

      <!-- Tactical Footer -->
      <footer class="role-footer-bar">
        <span>ORCA Maritime Intelligence • Deterministic Multi-Agent Verification • INCOIS / ISRO Compliant</span>
      </footer>
    `;

    this.attachEvents();
  }

  private renderRoleCard(cat: UserCategoryConfig, isSelected: boolean): string {
    return `
      <div class="role-card-item ${isSelected ? 'selected' : ''}" 
           data-key="${cat.key}" 
           role="radio" 
           aria-checked="${isSelected}" 
           tabindex="0">
        <div class="role-card-top-row">
          <span class="role-card-icon">${cat.icon}</span>
          <div class="role-card-indicator"></div>
        </div>
        <div class="role-card-info">
          <h3 class="role-card-title">${cat.shortName}</h3>
          <span class="role-card-tagline">${cat.tagline}</span>
        </div>
        <div class="role-card-vessel-badge">
          <span>${cat.vesselClass.replace(/_/g, ' ')}</span>
        </div>
      </div>
    `;
  }

  private attachEvents(): void {
    // Role card selection
    this.element.querySelectorAll('.role-card-item').forEach(card => {
      card.addEventListener('click', () => {
        const key = card.getAttribute('data-key') as UserCategoryKey;
        if (key && key !== this.selectedCategoryKey) {
          this.selectedCategoryKey = key;
          this.render();
        }
      });
    });

    // Sign out
    this.element.querySelector('#btn-role-signout')?.addEventListener('click', () => {
      store.logout();
    });

    // Cancel role switch (if user was already logged in with a role)
    this.element.querySelector('#btn-cancel-role-switch')?.addEventListener('click', () => {
      store.openRoleSelection(false);
    });

    // Confirm Role & Launch Console
    this.element.querySelector('#btn-confirm-role-launch')?.addEventListener('click', async () => {
      if (this.isSaving) return;
      this.isSaving = true;
      this.render();

      try {
        const selected = USER_CATEGORIES.find(c => c.key === this.selectedCategoryKey) || USER_CATEGORIES[0];
        await store.setUserCategory(selected);
      } catch (err) {
        console.error('Role confirmation error:', err);
        showToast('Error saving operational role', 'error');
      } finally {
        this.isSaving = false;
      }
    });
  }
}
