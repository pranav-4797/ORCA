import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';
import { showToast } from '../ui/Toast';

export class LoginPage {
  private element: HTMLElement;
  private isSigningIn: boolean = false;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'orca-login-page';
    this.render();
    store.subscribe(() => this.render());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const lang = store.activeLanguage || 'en';

    this.element.innerHTML = `
      <!-- Background Nautical Overlay -->
      <div class="login-nautical-bg"></div>

      <!-- Top Tactical Header Strip -->
      <header class="login-top-bar">
        <div class="login-top-brand">
          <div class="login-brand-logo">
            <span class="brand-anchor-icon">⚓</span>
            <div class="brand-text-col">
              <span class="brand-main-title">ORCA</span>
              <span class="brand-sub-title">Marine Intelligence</span>
            </div>
          </div>
        </div>

        <div class="login-top-actions">
          <!-- Language Selector -->
          <div class="login-lang-picker">
            <button class="login-lang-btn ${lang === 'en' ? 'active' : ''}" data-lang="en">EN</button>
            <button class="login-lang-btn ${lang === 'mr' ? 'active' : ''}" data-lang="mr">मराठी</button>
            <button class="login-lang-btn ${lang === 'hi' ? 'active' : ''}" data-lang="hi">हिन्दी</button>
          </div>

          <!-- Theme Toggle -->
          <button class="icon-btn login-theme-toggle" id="btn-login-theme-toggle" title="Toggle Theme">
            ${isDark ? ICONS.sun : ICONS.moon}
          </button>
        </div>
      </header>

      <!-- Center Hero Stage -->
      <main class="login-main-stage">
        <div class="login-content-grid">
          
          <!-- Left Col: Clean Professional Mission Summary -->
          <div class="login-hero-info">
            <div class="login-hero-tag">
              <span class="tag-radar-icon">🧭</span>
              <span>MARITIME OPERATIONAL CONSOLE</span>
            </div>

            <h1 class="login-hero-heading">
              Autonomous Marine Reasoning &amp; Coastal Safety
            </h1>

            <p class="login-hero-lead">
              Real-time INCOIS PFZ thermal advisories, IMD cyclone bulletins, and multi-agent oceanographic intelligence for Indian coastal waters.
            </p>

            <!-- Minimal Capability Chips -->
            <div class="login-caps-row">
              <div class="login-cap-chip">
                <span class="cap-icon">🛰️</span>
                <span>Live INCOIS PFZ &amp; WW3 Wave State</span>
              </div>
              <div class="login-cap-chip">
                <span class="cap-icon">🌪️</span>
                <span>IMD Cyclone &amp; Gale Warning Corridors</span>
              </div>
              <div class="login-cap-chip">
                <span class="cap-icon">🛡️</span>
                <span>IMBL Border Geofence &amp; SAR Drift Models</span>
              </div>
            </div>
          </div>

          <!-- Right Col: High-End Authentication Card -->
          <div class="login-card-container">
            <div class="login-auth-card">
              <div class="auth-card-top">
                <div class="auth-radar-emblem">
                  <span class="auth-emblem-core">⚓</span>
                </div>
                <h2 class="auth-card-title">Sign In to ORCA</h2>
                <p class="auth-card-desc">
                  Access your role-calibrated ocean telemetry, navigational safety floors, and cloud mission logs.
                </p>
              </div>

              <!-- Google Sign In Button -->
              <div class="auth-card-actions">
                <button class="btn-google-sign-in" id="btn-google-login-action" ${this.isSigningIn ? 'disabled' : ''}>
                  ${this.isSigningIn ? `
                    <div class="login-spinner"></div>
                    <span>Signing in...</span>
                  ` : `
                    <svg width="20" height="20" viewBox="0 0 24 24">
                      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
                      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
                    </svg>
                    <span>Continue with Google</span>
                  `}
                </button>
              </div>

              <!-- Compact Verification Note -->
              <div class="auth-compact-foot">
                <span class="foot-lock-icon">🔒</span>
                <span>Calibrated for Coastal Fishermen, Trawlers, Coast Guard &amp; Ocean Researchers</span>
              </div>
            </div>
          </div>

        </div>
      </main>

      <!-- Tactical Footer -->
      <footer class="login-footer-bar">
        <span>Smart India Hackathon 2026 • Problem Statement 26176 (ISRO / INCOIS / MoES)</span>
        <span>ECDIS Compliant • Deterministic Multi-Agent Verification</span>
      </footer>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    // Language switcher
    this.element.querySelectorAll('.login-lang-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const lang = btn.getAttribute('data-lang') as 'en' | 'mr' | 'hi';
        if (lang) {
          store.setLanguage(lang);
          showToast(`Language switched to ${lang.toUpperCase()}`, 'info');
        }
      });
    });

    // Theme toggle
    this.element.querySelector('#btn-login-theme-toggle')?.addEventListener('click', () => {
      const current = store.settings.theme;
      const nextTheme = current === 'dark' ? 'light' : 'dark';
      store.setTheme(nextTheme);
    });

    // Google Login Action
    this.element.querySelector('#btn-google-login-action')?.addEventListener('click', async () => {
      if (this.isSigningIn) return;
      this.isSigningIn = true;
      this.render();

      try {
        await store.loginWithGoogle();
      } catch (err) {
        console.error('Login action error:', err);
      } finally {
        this.isSigningIn = false;
        this.render();
      }
    });
  }
}
