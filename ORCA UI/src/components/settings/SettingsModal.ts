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

    this.element.innerHTML = `
      <div class="modal-container" style="max-width: 500px;">
        <div class="modal-header">
          <div style="font-weight:600;font-size:16px;color:var(--text-primary);display:flex;align-items:center;gap:8px;">
            ${ICONS.settings}
            <span>Workspace Settings</span>
          </div>
          <button class="icon-btn" id="btn-close-settings" title="Close" aria-label="Close Settings">
            ${ICONS.x}
          </button>
        </div>

        <div class="modal-body" style="display:flex;flex-direction:column;gap:18px;">
          <!-- Theme Preference -->
          <div>
            <label style="display:block;font-size:13px;font-weight:600;margin-bottom:6px;color:var(--text-primary);">Appearance</label>
            <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:8px;">
              <button class="theme-btn ${settings.theme === 'dark' ? 'active' : ''}" data-theme-val="dark" style="padding:8px;border:1px solid ${settings.theme === 'dark' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:var(--bg-card);color:var(--text-primary);display:flex;align-items:center;justify-content:center;gap:6px;font-size:12px;cursor:pointer;">
                ${ICONS.moon} Dark
              </button>
              <button class="theme-btn ${settings.theme === 'light' ? 'active' : ''}" data-theme-val="light" style="padding:8px;border:1px solid ${settings.theme === 'light' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:var(--bg-card);color:var(--text-primary);display:flex;align-items:center;justify-content:center;gap:6px;font-size:12px;cursor:pointer;">
                ${ICONS.sun} Light
              </button>
              <button class="theme-btn ${settings.theme === 'system' ? 'active' : ''}" data-theme-val="system" style="padding:8px;border:1px solid ${settings.theme === 'system' ? 'var(--primary)' : 'var(--border-default)'};border-radius:var(--radius-xs);background:var(--bg-card);color:var(--text-primary);display:flex;align-items:center;justify-content:center;gap:6px;font-size:12px;cursor:pointer;">
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

    // Reset Data
    this.element.querySelector('#btn-reset-data')?.addEventListener('click', () => {
      if (confirm('Reset all chats and settings to defaults?')) {
        localStorage.clear();
        window.location.reload();
      }
    });
  }
}
