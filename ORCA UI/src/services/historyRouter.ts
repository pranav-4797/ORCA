import { store } from '../store/appState';

/**
 * History Router & Subdomain/Back-Button Navigation Manager
 * 
 * Prevents accidental exit from ORCA when pressing browser/mobile back buttons.
 * Translates browser history actions (popstate) into internal UI navigation
 * (closing modals, returning to previous chat, closing drawers) instead of
 * terminating the web session.
 */
export class HistoryRouter {
  private static instance: HistoryRouter;
  private isHandlingPopstate: boolean = false;
  private chatHistoryStack: string[] = [];

  private constructor() {
    this.init();
  }

  public static getInstance(): HistoryRouter {
    if (!HistoryRouter.instance) {
      HistoryRouter.instance = new HistoryRouter();
    }
    return HistoryRouter.instance;
  }

  private init(): void {
    // Initial entry push so back button is trapped inside the SPA
    if (!window.location.hash) {
      window.history.replaceState({ page: 'home', chatId: store.activeChatId }, '', '#/');
    }

    // Listen to browser Back / Forward buttons
    window.addEventListener('popstate', (event) => {
      this.handlePopState(event);
    });

    // Subscribe to store state changes to sync URL hash & push history
    let prevActiveChatId = store.activeChatId;
    let prevSearchOpen = store.searchModalOpen;
    let prevSettingsOpen = store.settingsModalOpen;
    let prevAuthOpen = store.authModalOpen;
    let prevMobileSidebar = store.mobileSidebarOpen;
    let prevMapOpen = store.mapPanelOpen;

    store.subscribe(() => {
      if (this.isHandlingPopstate) return;

      // Handle Modals
      if (store.searchModalOpen && !prevSearchOpen) {
        this.pushRoute('search', '#/search');
      } else if (!store.searchModalOpen && prevSearchOpen && window.location.hash.includes('search')) {
        this.replaceActiveChatRoute();
      }

      if (store.settingsModalOpen && !prevSettingsOpen) {
        this.pushRoute('settings', '#/settings');
      } else if (!store.settingsModalOpen && prevSettingsOpen && window.location.hash.includes('settings')) {
        this.replaceActiveChatRoute();
      }

      if (store.authModalOpen && !prevAuthOpen) {
        this.pushRoute('auth', '#/auth');
      } else if (!store.authModalOpen && prevAuthOpen && window.location.hash.includes('auth')) {
        this.replaceActiveChatRoute();
      }

      if (store.mobileSidebarOpen && !prevMobileSidebar) {
        this.pushRoute('menu', '#/menu');
      } else if (!store.mobileSidebarOpen && prevMobileSidebar && window.location.hash.includes('menu')) {
        this.replaceActiveChatRoute();
      }

      // Handle Chat Switch
      if (store.activeChatId && store.activeChatId !== prevActiveChatId) {
        if (!this.chatHistoryStack.includes(store.activeChatId)) {
          this.chatHistoryStack.push(store.activeChatId);
        }
        this.pushRoute('chat', `#/chat/${store.activeChatId}`, { chatId: store.activeChatId });
      }

      prevActiveChatId = store.activeChatId;
      prevSearchOpen = store.searchModalOpen;
      prevSettingsOpen = store.settingsModalOpen;
      prevAuthOpen = store.authModalOpen;
      prevMobileSidebar = store.mobileSidebarOpen;
      prevMapOpen = store.mapPanelOpen;
    });

    // Handle initial hash on cold boot
    this.parseInitialHash();
  }

  private parseInitialHash(): void {
    const hash = window.location.hash;
    if (hash.startsWith('#/chat/')) {
      const targetChatId = hash.replace('#/chat/', '').trim();
      if (targetChatId && store.chats.some(c => c.id === targetChatId)) {
        store.selectChat(targetChatId);
      }
    } else if (hash === '#/search') {
      store.toggleSearchModal(true);
    } else if (hash === '#/settings') {
      store.toggleSettingsModal(true);
    } else if (hash === '#/auth') {
      store.toggleAuthModal(true);
    }
  }

  private pushRoute(page: string, hash: string, extraState: Record<string, any> = {}): void {
    if (window.location.hash !== hash) {
      window.history.pushState({ page, ...extraState }, '', hash);
    }
  }

  private replaceActiveChatRoute(): void {
    const hash = store.activeChatId ? `#/chat/${store.activeChatId}` : '#/';
    window.history.replaceState({ page: 'chat', chatId: store.activeChatId }, '', hash);
  }

  private handlePopState(event: PopStateEvent): void {
    this.isHandlingPopstate = true;
    try {
      // 1. If any modal is open, close it on back button
      if (store.searchModalOpen) {
        store.toggleSearchModal(false);
        return;
      }
      if (store.settingsModalOpen) {
        store.toggleSettingsModal(false);
        return;
      }
      if (store.authModalOpen) {
        store.toggleAuthModal(false);
        return;
      }
      if (store.mobileSidebarOpen) {
        store.toggleMobileSidebar(false);
        return;
      }
      if (store.mobileAgentDrawerOpen) {
        store.toggleMobileAgentDrawer(false);
        return;
      }

      // 2. Navigate based on state or hash
      const state = event.state;
      if (state && state.chatId) {
        if (store.activeChatId !== state.chatId && store.chats.some(c => c.id === state.chatId)) {
          store.selectChat(state.chatId);
          return;
        }
      }

      // 3. If popped to root hash or unknown, fallback to previous chat or default
      const hash = window.location.hash;
      if (hash.startsWith('#/chat/')) {
        const id = hash.replace('#/chat/', '').trim();
        if (id && store.chats.some(c => c.id === id)) {
          store.selectChat(id);
          return;
        }
      }

      // If at root and there are chats, stay on primary view and prevent site exit
      if (store.chats.length > 0 && !store.activeChatId) {
        store.selectChat(store.chats[0].id);
      }
    } finally {
      this.isHandlingPopstate = false;
    }
  }
}
