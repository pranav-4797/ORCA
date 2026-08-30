import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';
import { showToast } from '../ui/Toast';

export class Sidebar {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement('aside');
    this.element.className = 'sidebar';
    this.render();
    store.subscribe(() => this.render());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const isCollapsed = store.sidebarCollapsed;
    const isMobileOpen = store.mobileSidebarOpen;
    const activeChatId = store.activeChatId;
    const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
    const searchKbd = isMac ? '⌘K' : 'Ctrl K';

    this.element.className = `sidebar ${isCollapsed ? 'collapsed' : ''} ${isMobileOpen ? 'mobile-open' : ''}`;

    const pinnedChats = store.chats.filter(c => c.pinned);
    const recentChats = store.chats.filter(c => !c.pinned);
    const user = store.currentUser;
    const officerName = user?.displayName || 'Watch Officer';
    const officerInitials = (user?.displayName || user?.email || 'OP').slice(0, 2).toUpperCase();

    this.element.innerHTML = `
      <div class="sidebar-header">
        <div class="brand-area" id="brand-home-link" title="ORCA Maritime Intelligence">
          <div class="brand-logo">
            <img src="/favicon.svg" alt="ORCA Compass Emblem" class="brand-favicon-img" />
          </div>
          <div class="brand-text-col">
            <span class="brand-text">ORCA</span>
            <span class="brand-subtext">Marine Intelligence</span>
          </div>
        </div>
        <button class="icon-btn" id="btn-collapse-sidebar" title="${isCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}" aria-label="Toggle Sidebar">
          ${isCollapsed ? ICONS.chevronRight || '▸' : ICONS.sidebar}
        </button>
      </div>

      <!-- Action buttons -->
      <div class="sidebar-nav-actions">
        <button class="btn-new-chat" id="btn-sidebar-new-chat" title="New Maritime Briefing">
          ${ICONS.plus}
          <span class="label">New Briefing</span>
        </button>

        <button class="search-trigger-btn" id="btn-sidebar-search" title="Search Briefings (${searchKbd})">
          <div style="display:flex;align-items:center;gap:6px;">
            ${ICONS.search}
            <span class="label">Search...</span>
          </div>
          <kbd class="search-kbd">${searchKbd}</kbd>
        </button>
      </div>

      <!-- Main Mission Briefings History -->
      <div class="sidebar-content">
        ${pinnedChats.length > 0 ? `
          <div class="sidebar-group">
            <div class="sidebar-section-title">Pinned Briefs</div>
            <ul class="chat-list">
              ${pinnedChats.map(c => this.renderChatItem(c, activeChatId === c.id)).join('')}
            </ul>
          </div>
        ` : ''}

        <div class="sidebar-group">
          <div class="sidebar-section-title">${pinnedChats.length > 0 ? 'Recent Briefs' : 'Mission History'}</div>
          <ul class="chat-list">
            ${recentChats.length > 0 
              ? recentChats.map(c => this.renderChatItem(c, activeChatId === c.id)).join('')
              : `<li class="empty-history-hint">No previous briefings</li>`
            }
          </ul>
        </div>
      </div>

      <!-- Settings Button -->
      <div class="sidebar-settings-section">
        <button class="sidebar-settings-btn" id="btn-sidebar-open-settings" title="Workspace Settings &amp; Navigation">
          <span class="settings-btn-icon">${ICONS.settings}</span>
          <span class="settings-btn-label">Settings</span>
        </button>
      </div>

      <!-- Clean Footer -->
      <div class="sidebar-footer">
        <button class="user-profile-btn" id="btn-sidebar-profile" title="Role: ${store.userCategory?.roleName || 'Verified Officer'} • Click to change profile">
          ${user?.photoURL ? `
            <img src="${user.photoURL}" alt="Officer" class="sidebar-user-avatar-img" />
          ` : `
            <div class="user-avatar">${officerInitials}</div>
          `}
          <div class="user-details">
            <div class="user-name">${officerName}</div>
            <div class="user-plan">${store.userCategory ? `${store.userCategory.badgeEmoji} ${store.userCategory.roleName}` : user ? 'Verified Officer' : 'Authentication Required'}</div>
          </div>
        </button>
      </div>
    `;

    this.attachEvents();
  }

  private renderChatItem(chat: import('../../types/chat').Chat, isActive: boolean): string {
    const agent = store.agents.find(a => a.id === chat.agentId);
    const iconName = agent ? agent.icon : 'messageSquare';

    return `
      <li class="chat-item ${isActive ? 'active' : ''}" data-chat-id="${chat.id}" title="${chat.title}">
        <span class="chat-item-icon">${ICONS[iconName] || ICONS.messageSquare}</span>
        <span class="chat-item-title">${chat.title}</span>
        <div class="chat-item-actions">
          <button class="chat-action-btn btn-pin-chat" data-chat-id="${chat.id}" title="${chat.pinned ? 'Unpin' : 'Pin'}">
            ${ICONS.pin}
          </button>
          <button class="chat-action-btn btn-delete-chat" data-chat-id="${chat.id}" title="Delete">
            ${ICONS.trash}
          </button>
        </div>
      </li>
    `;
  }

  private attachEvents(): void {
    // Collapse / Expand toggle button
    this.element.querySelector('#btn-collapse-sidebar')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const isMobile = window.innerWidth < 768;
      if (isMobile) {
        store.toggleMobileSidebar(false);
      } else {
        store.toggleSidebar();
      }
    });

    // New Inquiry button
    this.element.querySelector('#btn-sidebar-new-chat')?.addEventListener('click', () => {
      store.createNewChat();
      store.toggleMobileSidebar(false);
      showToast('Started new mission brief', 'info');
    });

    // Search button
    this.element.querySelector('#btn-sidebar-search')?.addEventListener('click', () => {
      store.toggleSearchModal(true);
    });

    // Chat Item selection
    const chatItems = this.element.querySelectorAll('.chat-item');
    chatItems.forEach(item => {
      item.addEventListener('click', (e) => {
        const target = e.target as HTMLElement;
        if (target.closest('.chat-action-btn')) return;

        const chatId = item.getAttribute('data-chat-id');
        if (chatId) {
          store.selectChat(chatId);
          store.toggleMobileSidebar(false);
        }
      });
    });

    // Pin chat button
    const pinButtons = this.element.querySelectorAll('.btn-pin-chat');
    pinButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const chatId = btn.getAttribute('data-chat-id');
        if (chatId) {
          store.togglePinChat(chatId);
          showToast('Briefing pin status updated', 'info');
        }
      });
    });

    // Delete chat button
    const deleteButtons = this.element.querySelectorAll('.btn-delete-chat');
    deleteButtons.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const chatId = btn.getAttribute('data-chat-id');
        if (chatId) {
          if (confirm('Delete this mission brief?')) {
            store.deleteChat(chatId);
            showToast('Briefing deleted', 'info');
          }
        }
      });
    });

    // Settings button
    this.element.querySelector('#btn-sidebar-open-settings')?.addEventListener('click', () => {
      store.toggleSettingsModal(true);
    });

    // Profile footer button
    this.element.querySelector('#btn-sidebar-profile')?.addEventListener('click', () => {
      store.openRoleSelection(true);
    });
  }
}
