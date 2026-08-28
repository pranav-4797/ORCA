import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';

export class AuthModal {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'modal-backdrop';
    this.element.id = 'auth-modal-backdrop';
    this.render();
    store.subscribe(() => this.updateVisibility());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private updateVisibility(): void {
    if (store.authModalOpen && !store.currentUser) {
      this.element.classList.add('active');
      this.render();
    } else {
      this.element.classList.remove('active');
    }
  }

  private render(): void {
    this.element.innerHTML = `
      <div class="modal-container auth-modal-card" style="max-width: 460px;">
        <div class="modal-header">
          <div style="font-weight:700;font-size:14px;color:var(--primary);display:flex;align-items:center;gap:8px;letter-spacing:0.04em;text-transform:uppercase;">
            <span>${ICONS.shield || '⚓'}</span>
            <span>Maritime Authentication</span>
          </div>
          <button class="icon-btn" id="btn-close-auth-modal" title="Close" aria-label="Close Authentication Modal">
            ${ICONS.x}
          </button>
        </div>

        <div class="modal-body auth-modal-body">
          <div class="auth-hero-graphic">
            <div class="auth-radar-ring">
              <span class="auth-radar-center">${ICONS.compass || '🧭'}</span>
            </div>
          </div>

          <h3 class="auth-modal-heading">Save &amp; Protect Your Mission Briefings</h3>
          <p class="auth-modal-subtext">
            Sign in to automatically sync all your coastal navigation advisories, oceanographic telemetry, and custom waypoint routes across devices.
          </p>

          <div class="auth-benefits-list">
            <div class="auth-benefit-item">
              <span class="benefit-icon">☁️</span>
              <div class="benefit-text">
                <strong>Cloud Session Access:</strong> Return anytime after days and resume your exact marine briefings.
              </div>
            </div>
            <div class="auth-benefit-item">
              <span class="benefit-icon">🛰️</span>
              <div class="benefit-text">
                <strong>INCOIS &amp; IMD Alerts:</strong> Receive personalized high-tide &amp; cyclone warning alerts.
              </div>
            </div>
            <div class="auth-benefit-item">
              <span class="benefit-icon">🚢</span>
              <div class="benefit-text">
                <strong>Vessel Profiling:</strong> Save vessel draft, speed, and preferred fishing zones.
              </div>
            </div>
          </div>

          <button class="btn-google-login-large" id="btn-modal-google-signin">
            <svg width="18" height="18" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
            </svg>
            <span>Sign in with Google</span>
          </button>
        </div>

        <div class="modal-footer" style="justify-content:center;">
          <button class="btn-guest-continue" id="btn-modal-guest-continue">
            Continue as Guest (Temporary Session)
          </button>
        </div>
      </div>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    // Backdrop click dismisses
    this.element.addEventListener('click', (e) => {
      if (e.target === this.element) {
        store.toggleAuthModal(false);
      }
    });

    // Close button
    this.element.querySelector('#btn-close-auth-modal')?.addEventListener('click', () => {
      store.toggleAuthModal(false);
    });

    // Google Sign in
    this.element.querySelector('#btn-modal-google-signin')?.addEventListener('click', async () => {
      await store.loginWithGoogle();
      if (store.currentUser) {
        store.toggleAuthModal(false);
      }
    });

    // Continue as guest
    this.element.querySelector('#btn-modal-guest-continue')?.addEventListener('click', () => {
      store.toggleAuthModal(false);
    });
  }
}
