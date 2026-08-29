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
      <!-- Top Nautical Brand & Status Strip -->
      <div class="header-main-strip">
        <div class="header-left">
          <button class="icon-btn btn-mobile-menu" id="btn-toggle-mobile-sidebar" title="Open Navigation Menu" aria-label="Open Navigation Menu">
            ${ICONS.menu}
          </button>

          <div class="orca-brand-badge">
            <span class="orca-brand-icon">⚓</span>
            <div class="orca-brand-text-col">
              <span class="orca-brand-title">ORCA</span>
              <span class="orca-brand-tagline">MARINE ECOSYSTEM REASONING • COLLABORATIVE AGENTS</span>
            </div>
          </div>
        </div>

        <!-- Top Navigation Tabs (Today | Ask ORCA | Authority | System) -->
        <nav class="header-nav-tabs" role="tablist">
          <button class="nav-tab-btn" id="tab-today" data-tab="today">आज / Today</button>
          <button class="nav-tab-btn active" id="tab-ask-orca" data-tab="chat">ORCA ला विचारा / Ask ORCA</button>
          <button class="nav-tab-btn" id="tab-authority" data-tab="sar">प्रशासन / Authority</button>
          <button class="nav-tab-btn" id="tab-system" data-tab="system">प्रणाली / System</button>
        </nav>

        <div class="header-right">
          <!-- ECDIS Chart & Edition Badges -->
          <div class="ecdis-meta-chip">
            <span class="meta-label">CHART #</span>
            <span class="meta-val">SIH26176</span>
          </div>

          <div class="ecdis-meta-chip">
            <span class="meta-label">DATA EDITION</span>
            <span class="meta-val highlight">${store.backendOnline ? 'LIVE' : 'DEMO'}</span>
          </div>

          <button class="btn-voice-indicator" id="btn-header-voice-toggle" title="Toggle Voice Response">
            <span>🔊 VOICE</span>
            <span class="voice-state-text">ON</span>
          </button>

          <button class="icon-btn" id="btn-theme-toggle" title="Toggle Theme (Night / Day)">
            ${isDark ? ICONS.sun : ICONS.moon}
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
              <span>Sign In</span>
            </button>
          `}
        </div>
      </div>

      <!-- Rehearsed Coastal Scenarios Ribbon -->
      <div class="scenarios-quick-ribbon">
        <span class="scenarios-title">REHEARSED SCENARIOS</span>
        <div class="scenarios-list">
          <button class="scenario-btn" data-scenario="safe_goa">
            <span class="sc-num">1</span>
            <span class="sc-name">Safe</span>
            <span class="sc-loc">GOA • LOW</span>
          </button>
          <button class="scenario-btn" data-scenario="rough_mumbai">
            <span class="sc-num">2</span>
            <span class="sc-name">Rough</span>
            <span class="sc-loc">MUMBAI • मराठी</span>
          </button>
          <button class="scenario-btn" data-scenario="cyclone_paradip">
            <span class="sc-num">3</span>
            <span class="sc-name">Cyclone</span>
            <span class="sc-loc">PARADIP • EXTREME</span>
          </button>
          <button class="scenario-btn" data-scenario="pfz_kochi">
            <span class="sc-num">4</span>
            <span class="sc-name">Fishing zones</span>
            <span class="sc-loc">KOCHI • हिंदी</span>
          </button>
          <button class="scenario-btn" data-scenario="safe_route_mumbai">
            <span class="sc-num">5</span>
            <span class="sc-name">Safe route</span>
            <span class="sc-loc">MUMBAI • GEOFENCE</span>
          </button>
        </div>
      </div>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    // Google Auth Login
    this.element.querySelector('#btn-header-login')?.addEventListener('click', () => {
      store.loginWithGoogle();
    });

    // Rehearsed Scenarios Click
    this.element.querySelectorAll('.scenario-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const scenario = btn.getAttribute('data-scenario');
        if (scenario === 'safe_goa') {
          store.sendMessage('Is it safe to sail from Panaji Port, Goa tomorrow morning? Inspect waves and wind.');
        } else if (scenario === 'rough_mumbai') {
          store.sendMessage('मी उद्या सकाळी ६ वाजता मुंबईजवळ मासेमारीला जाऊ शकतो का?');
        } else if (scenario === 'cyclone_paradip') {
          store.sendMessage('Are there active cyclone or high wave warnings near Paradip port, Odisha?');
        } else if (scenario === 'pfz_kochi') {
          store.sendMessage('कोच्चि तट के पास सबसे निकटतम मछली पकड़ने का क्षेत्र (PFZ) कहाँ है?');
        } else if (scenario === 'safe_route_mumbai') {
          store.sendMessage('Plot a safe navigational route from Mumbai Harbour avoiding restricted coastal zones.');
        }
      });
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
