import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';
import { showToast } from '../ui/Toast';
import { copyToClipboard } from '../../utils/helpers';

export class Header {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement('header');
    this.element.className = 'top-header';
    this.render();
    store.subscribe(() => this.render());
  }
  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const isThinking = store.isStreaming;
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const activeChat = store.getActiveChat();

    this.element.innerHTML = `
      <div class="header-left">
        <button class="icon-btn btn-mobile-menu" id="btn-toggle-mobile-sidebar" title="Open Navigation Menu" aria-label="Open Navigation Menu">
          ${ICONS.menu}
        </button>

        <div class="orca-brand-badge">
          <span class="orca-brand-title">ORCA</span>
          <span class="orca-region-divider"></span>
          <span class="orca-region-label">Indian Region</span>
        </div>

        ${activeChat && activeChat.messageCount > 0 ? `
          <div class="header-active-brief-title" id="chat-title-heading" title="Click to rename brief">
            <span class="title-text">${activeChat.title}</span>
          </div>
        ` : ''}
      </div>

      <div class="header-right">
        <!-- Telemetry Indicators -->
        <div class="header-telemetry-status">
          <button class="orca-status-chip ${store.backendOnline === false ? 'offline' : isThinking ? 'busy' : 'safe'}"
                  id="btn-backend-status"
                  title="${store.backendOnline === false
                    ? `Backend OFFLINE at ${store.backendUrl} — click to retry`
                    : `Live backend: ${store.backendUrl}`}">
            <span class="status-indicator-dot ${isThinking ? 'thinking' : ''}"></span>
            <span class="status-text">${store.backendOnline === false ? 'DEMO MODE' : store.backendOnline === null ? 'CONNECTING' : 'LIVE'}</span>
          </button>
        </div>

        <button class="icon-btn" id="btn-theme-toggle" title="Toggle Theme (ECDIS Night / Maritime Light)" aria-label="Toggle Theme">
          ${isDark ? ICONS.sun : ICONS.moon}
        </button>

        <button class="icon-btn" id="btn-share-chat" title="Export / Share Mission Brief" aria-label="Share Brief">
          ${ICONS.share}
        </button>

        <button class="icon-btn ${store.agentPanelOpen ? 'active' : ''}" id="btn-toggle-agent-panel" title="Toggle Mission & Telemetry Inspector" aria-label="Toggle Inspector">
          ${ICONS.sidebarRight}
        </button>

        <!-- Google Auth / Officer Profile Popover -->
        ${store.currentUser ? `
          <div class="officer-profile-chip" id="officer-profile-chip" title="${store.currentUser.displayName || store.currentUser.email} • Click for account options">
            ${store.currentUser.photoURL ? `
              <img src="${store.currentUser.photoURL}" alt="Officer Avatar" class="officer-avatar-img" />
            ` : `
              <div class="officer-avatar">${(store.currentUser.displayName || store.currentUser.email || 'OP').slice(0, 2).toUpperCase()}</div>
            `}
            <div class="officer-popover" id="officer-popover" style="display:none;">
              <div class="officer-popover-header">
                <div class="popover-name">${store.currentUser.displayName || 'Watch Officer'}</div>
                <div class="popover-email">${store.currentUser.email}</div>
                <div class="officer-role-pill" style="margin-top:4px;">
                  <span>${store.userCategory?.badgeEmoji || '⚓'}</span>
                  <span>${store.userCategory?.roleName || 'General Mariner'}</span>
                </div>
              </div>
              <button class="btn-popover-action" id="btn-popover-switch-role">
                <span>🔄</span>
                <span>Switch Operational Role</span>
              </button>
              <button class="btn-popover-logout" id="btn-header-logout">
                <span>${ICONS.logOut || '⎋'}</span>
                <span>Sign Out</span>
              </button>
            </div>
          </div>
        ` : `
          <button class="btn-google-auth" id="btn-header-login" title="Sign in with Google Account">
            <svg width="15" height="15" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
            </svg>
            <span>Sign In</span>
          </button>
        `}
      </div>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    // Google Auth Login
    this.element.querySelector('#btn-header-login')?.addEventListener('click', () => {
      store.loginWithGoogle();
    });

    // Switch Role via popover
    this.element.querySelector('#btn-popover-switch-role')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const popover = this.element.querySelector('#officer-popover') as HTMLElement | null;
      if (popover) popover.style.display = 'none';
      store.toggleCategoryModal(true);
    });

    // Toggle Officer Popover
    const profileChip = this.element.querySelector('#officer-profile-chip');
    const popover = this.element.querySelector('#officer-popover') as HTMLElement | null;
    profileChip?.addEventListener('click', (e) => {
      e.stopPropagation();
      if (popover) {
        popover.style.display = popover.style.display === 'none' ? 'block' : 'none';
      }
    });

    // Close popover on outside click
    document.addEventListener('click', () => {
      if (popover) popover.style.display = 'none';
    });

    // Logout
    this.element.querySelector('#btn-header-logout')?.addEventListener('click', (e) => {
      e.stopPropagation();
      store.logout();
    });

    // Backend status chip -> manual reconnect attempt
    this.element.querySelector('#btn-backend-status')?.addEventListener('click', () => {
      if (store.backendOnline === false) {
        showToast('Retrying ORCA backend connection...', 'info');
        store.reconnectBackend();
      } else {
        showToast(`Live multi-agent backend: ${store.backendUrl}`, 'info');
      }
    });

    // Mobile menu toggle
    this.element.querySelector('#btn-toggle-mobile-sidebar')?.addEventListener('click', () => {
      store.toggleMobileSidebar(true);
    });

    // Theme toggle
    this.element.querySelector('#btn-theme-toggle')?.addEventListener('click', () => {
      const current = store.settings.theme;
      const nextTheme = current === 'dark' ? 'light' : 'dark';
      store.setTheme(nextTheme);
      showToast(`Interface switched to ${nextTheme === 'dark' ? 'ECDIS Night Mode' : 'Maritime Precision Light'}`, 'info');
    });

    // Share brief
    this.element.querySelector('#btn-share-chat')?.addEventListener('click', async () => {
      const activeChat = store.getActiveChat();
      if (!activeChat) {
        showToast('No mission brief selected to export', 'info');
        return;
      }
      const shareUrl = `${window.location.origin}?brief=${activeChat.id}`;
      await copyToClipboard(shareUrl);
      showToast('Mission brief link copied to clipboard', 'success');
    });

    // Agent / Telemetry panel toggle
    this.element.querySelector('#btn-toggle-agent-panel')?.addEventListener('click', () => {
      const isMobileOrTablet = window.innerWidth < 1280;
      if (isMobileOrTablet) {
        store.toggleMobileAgentDrawer();
      } else {
        store.toggleAgentPanel();
      }
    });

    // Rename chat
    this.element.querySelector('#chat-title-heading')?.addEventListener('click', () => {
      const activeChat = store.getActiveChat();
      if (!activeChat) return;

      const currentTitle = activeChat.title;
      const newTitle = prompt('Rename Mission Brief:', currentTitle);
      if (newTitle && newTitle.trim() && newTitle !== currentTitle) {
        store.renameChat(activeChat.id, newTitle.trim());
        showToast('Mission brief title updated', 'success');
      }
    });
  }
}
