import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';
import { showToast } from '../ui/Toast';

export class SettingsModal {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'modal-backdrop';
    this.render();
    store.subscribe(() => this.updateVisibility());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private updateVisibility(): void {
    if (store.settingsModalOpen) {
      this.element.classList.add('active');
      this.render();
    } else {
      this.element.classList.remove('active');
    }
  }

  private render(): void {
    const settings = store.settings;
    const lang = store.activeLanguage || 'en';

    this.element.innerHTML = `
      <div class="modal-container" style="max-width: 520px;">
        <div class="modal-header">
          <div style="font-weight:700;font-size:15px;color:var(--text-primary);display:flex;align-items:center;gap:8px;">
            ${ICONS.settings}
            <span>ORCA Workspace &amp; Navigation Settings</span>
          </div>
          <button class="icon-btn" id="btn-close-settings" title="Close" aria-label="Close Settings">
            ${ICONS.x}
          </button>
        </div>

        <div class="modal-body" style="display:flex;flex-direction:column;gap:18px;">
          <!-- Console Workspace Navigation View -->
          <div>
            <label style="display:block;font-size:12px;font-weight:700;letter-spacing:0.04em;margin-bottom:8px;color:var(--primary);text-transform:uppercase;">
              Active Console View
            </label>
            <div style="display:grid;grid-template-columns:repeat(2, 1fr);gap:8px;">
              <button class="settings-nav-btn ${store.activeNavTab === 'overview' ? 'active' : ''}" data-nav-tab="overview" style="padding:10px 12px;border:1px solid ${store.activeNavTab === 'overview' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:${store.activeNavTab === 'overview' ? 'rgba(14,124,134,0.15)' : 'var(--bg-card)'};color:var(--text-primary);display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;cursor:pointer;">
                <span>🗺️</span>
                <span>Overview (Map &amp; HUD)</span>
              </button>
              <button class="settings-nav-btn ${store.activeNavTab === 'chat' ? 'active' : ''}" data-nav-tab="chat" style="padding:10px 12px;border:1px solid ${store.activeNavTab === 'chat' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:${store.activeNavTab === 'chat' ? 'rgba(14,124,134,0.15)' : 'var(--bg-card)'};color:var(--text-primary);display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;cursor:pointer;">
                <span>💬</span>
                <span>Ask ORCA (Chat)</span>
              </button>
              <button class="settings-nav-btn ${store.activeNavTab === 'sar' ? 'active' : ''}" data-nav-tab="sar" style="padding:10px 12px;border:1px solid ${store.activeNavTab === 'sar' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:${store.activeNavTab === 'sar' ? 'rgba(14,124,134,0.15)' : 'var(--bg-card)'};color:var(--text-primary);display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;cursor:pointer;">
                <span>🛡️</span>
                <span>Authority &amp; SAR</span>
              </button>
              <button class="settings-nav-btn ${store.activeNavTab === 'system' ? 'active' : ''}" data-nav-tab="system" style="padding:10px 12px;border:1px solid ${store.activeNavTab === 'system' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:${store.activeNavTab === 'system' ? 'rgba(14,124,134,0.15)' : 'var(--bg-card)'};color:var(--text-primary);display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;cursor:pointer;">
                <span>🤖</span>
                <span>Multi-Agent System</span>
              </button>
            </div>
          </div>

          <!-- Active Operational Role -->
          <div style="background:var(--bg-surface-hover);padding:12px;border:1px solid var(--border-subtle);border-radius:var(--radius-xs);">
            <label style="display:block;font-size:12px;font-weight:700;letter-spacing:0.04em;margin-bottom:6px;color:var(--primary);text-transform:uppercase;">
              Maritime Operational Role
            </label>
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
              <div>
                <div style="font-size:14px;font-weight:600;color:var(--text-primary);display:flex;align-items:center;gap:6px;">
                  <span>${store.userCategory?.badgeEmoji || '⚓'}</span>
                  <span>${store.userCategory?.roleName || 'No Role Selected'}</span>
                </div>
                <div style="font-size:12px;color:var(--text-secondary);margin-top:2px;">
                  ${store.userCategory?.tagline || 'Select your maritime profile for tailored telemetry'}
                </div>
              </div>
              <button id="btn-settings-change-role" style="padding:6px 12px;background:var(--bg-surface);border:1px solid var(--border-strong);border-radius:var(--radius-xs);color:var(--primary);font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;">
                Switch Role
              </button>
            </div>
          </div>

          <!-- Language Preference -->
          <div>
            <label style="display:block;font-size:13px;font-weight:600;margin-bottom:6px;color:var(--text-primary);">Language</label>
            <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:8px;">
              <button class="settings-lang-btn ${lang === 'en' ? 'active' : ''}" data-lang-val="en" style="padding:8px;border:1px solid ${lang === 'en' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:${lang === 'en' ? 'rgba(14,124,134,0.15)' : 'var(--bg-card)'};color:var(--text-primary);font-size:12px;font-weight:600;cursor:pointer;">
                English
              </button>
              <button class="settings-lang-btn ${lang === 'mr' ? 'active' : ''}" data-lang-val="mr" style="padding:8px;border:1px solid ${lang === 'mr' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:${lang === 'mr' ? 'rgba(14,124,134,0.15)' : 'var(--bg-card)'};color:var(--text-primary);font-size:12px;font-weight:600;cursor:pointer;">
                मराठी
              </button>
              <button class="settings-lang-btn ${lang === 'hi' ? 'active' : ''}" data-lang-val="hi" style="padding:8px;border:1px solid ${lang === 'hi' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:${lang === 'hi' ? 'rgba(14,124,134,0.15)' : 'var(--bg-card)'};color:var(--text-primary);font-size:12px;font-weight:600;cursor:pointer;">
                हिन्दी
              </button>
            </div>
          </div>

          <!-- Theme Preference -->
          <div>
            <label style="display:block;font-size:13px;font-weight:600;margin-bottom:6px;color:var(--text-primary);">Appearance</label>
            <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:8px;">
              <button class="theme-btn ${settings.theme === 'dark' ? 'active' : ''}" data-theme-val="dark" style="padding:8px;border:1px solid ${settings.theme === 'dark' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:${settings.theme === 'dark' ? 'rgba(14,124,134,0.15)' : 'var(--bg-card)'};color:var(--text-primary);display:flex;align-items:center;justify-content:center;gap:6px;font-size:12px;cursor:pointer;">
                ${ICONS.moon} Dark
              </button>
              <button class="theme-btn ${settings.theme === 'light' ? 'active' : ''}" data-theme-val="light" style="padding:8px;border:1px solid ${settings.theme === 'light' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:${settings.theme === 'light' ? 'rgba(14,124,134,0.15)' : 'var(--bg-card)'};color:var(--text-primary);display:flex;align-items:center;justify-content:center;gap:6px;font-size:12px;cursor:pointer;">
                ${ICONS.sun} Light
              </button>
              <button class="theme-btn ${settings.theme === 'system' ? 'active' : ''}" data-theme-val="system" style="padding:8px;border:1px solid ${settings.theme === 'system' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:${settings.theme === 'system' ? 'rgba(14,124,134,0.15)' : 'var(--bg-card)'};color:var(--text-primary);display:flex;align-items:center;justify-content:center;gap:6px;font-size:12px;cursor:pointer;">
                ${ICONS.cpu} System
              </button>
            </div>
          </div>

          <!-- Behavior Toggles -->
          <div style="display:flex;flex-direction:column;gap:10px;">
            <label style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;">
              <div>
                <div style="font-size:13px;font-weight:500;color:var(--text-primary);">Send message on Enter</div>
                <div style="font-size:11px;color:var(--text-tertiary);">Shift+Enter will insert a new line</div>
              </div>
              <input type="checkbox" id="chk-send-enter" ${settings.sendOnEnter ? 'checked' : ''} style="width:16px;height:16px;accent-color:var(--primary);cursor:pointer;">
            </label>

            <label style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;">
              <div>
                <div style="font-size:13px;font-weight:500;color:var(--text-primary);">Audio feedback</div>
                <div style="font-size:11px;color:var(--text-tertiary);">Play subtle click and completion sounds</div>
              </div>
              <input type="checkbox" id="chk-sound" ${settings.soundEnabled ? 'checked' : ''} style="width:16px;height:16px;accent-color:var(--primary);cursor:pointer;">
            </label>
          </div>

          <!-- Developer & Reset Area -->
          <div style="padding-top:10px;border-top:1px solid var(--border-subtle);">
            <div style="font-size:11px;font-weight:700;letter-spacing:0.06em;margin-bottom:8px;color:var(--text-tertiary);text-transform:uppercase;">Data Management</div>
            <button id="btn-reset-data" style="width:100%;padding:8px;border:1px solid var(--status-critical-border);background:var(--status-critical-bg);color:var(--status-critical);border-radius:var(--radius-xs);font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center;gap:6px;cursor:pointer;">
              ${ICONS.trash} Reset Demo Data to Defaults
            </button>
          </div>
        </div>

        <div class="modal-footer">
          <button id="btn-save-settings" style="padding:6px 16px;background:var(--primary);color:var(--primary-text);border:none;border-radius:var(--radius-xs);font-size:13px;font-weight:600;cursor:pointer;">
            Done
          </button>
        </div>
      </div>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    this.element.addEventListener('click', (e) => {
      if (e.target === this.element) {
        store.toggleSettingsModal(false);
      }
    });

    this.element.querySelector('#btn-close-settings')?.addEventListener('click', () => {
      store.toggleSettingsModal(false);
    });

    this.element.querySelector('#btn-save-settings')?.addEventListener('click', () => {
      store.toggleSettingsModal(false);
    });

    // Navigation Tab buttons
    this.element.querySelectorAll('.settings-nav-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const tab = btn.getAttribute('data-nav-tab') as 'overview' | 'chat' | 'sar' | 'system';
        if (tab) {
          store.setNavTab(tab);
          store.toggleSettingsModal(false);
          showToast(`Switched view to ${tab.toUpperCase()}`, 'info');
        }
      });
    });

    // Language buttons
    this.element.querySelectorAll('.settings-lang-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const lang = btn.getAttribute('data-lang-val') as 'en' | 'mr' | 'hi';
        if (lang) {
          store.setLanguage(lang);
          this.render();
          showToast(`Language switched to ${lang.toUpperCase()}`, 'info');
        }
      });
    });

    // Change Role button
    this.element.querySelector('#btn-settings-change-role')?.addEventListener('click', () => {
      store.toggleSettingsModal(false);
      store.openRoleSelection(true);
    });

    // Theme selector buttons
    const themeBtns = this.element.querySelectorAll('.theme-btn');
    themeBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        const val = btn.getAttribute('data-theme-val') as import('../../types/chat').ThemeMode;
        if (val) {
          store.setTheme(val);
          this.render();
          showToast(`Theme changed to ${val}`, 'info');
        }
      });
    });

    // Send on Enter toggle
    const chkEnter = this.element.querySelector('#chk-send-enter') as HTMLInputElement;
    chkEnter?.addEventListener('change', () => {
      store.settings.sendOnEnter = chkEnter.checked;
    });

    // Audio Feedback toggle
    const chkSound = this.element.querySelector('#chk-sound') as HTMLInputElement;
    chkSound?.addEventListener('change', () => {
      store.settings.soundEnabled = chkSound.checked;
    });

    // Reset Data
    this.element.querySelector('#btn-reset-data')?.addEventListener('click', () => {
      if (confirm('Reset all chats and settings to defaults?')) {
        localStorage.clear();
        window.location.reload();
      }
    });
  }
}
