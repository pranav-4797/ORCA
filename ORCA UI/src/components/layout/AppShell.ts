import { store } from '../../store/appState';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { ChatWindow } from '../chat/ChatWindow';
import { AgentPanel } from '../agents/AgentPanel';
import { OperationalPicture } from '../map/OperationalPicture';
import { SearchModal } from '../search/SearchModal';
import { SettingsModal } from '../settings/SettingsModal';
import { LoginPage } from '../auth/LoginPage';
import { RoleSelectionPage } from '../auth/RoleSelectionPage';
import { ToastManager } from '../ui/Toast';

export class AppShell {
  private element: HTMLElement;
  private loginPage: LoginPage;
  private roleSelectionPage: RoleSelectionPage;
  private consoleLayout: HTMLElement;
  private loadingScreen: HTMLElement;

  private sidebar: Sidebar;
  private header: Header;
  private chatWindow: ChatWindow;
  private operationalPicture: OperationalPicture;
  private agentPanel: AgentPanel;
  private searchModal: SearchModal;
  private settingsModal: SettingsModal;
  private mobileBackdrop: HTMLElement;
  private locationBanner: HTMLElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'app-shell-root';

    // 1. Dedicated Full-Page Login
    this.loginPage = new LoginPage();

    // 2. Dedicated Full-Page Role Selection
    this.roleSelectionPage = new RoleSelectionPage();

    // 3. Loading / Splash Screen
    this.loadingScreen = document.createElement('div');
    this.loadingScreen.className = 'orca-loading-screen';
    this.loadingScreen.innerHTML = `
      <div class="loading-radar-emblem">
        <div class="loading-radar-sweep"></div>
        <span class="loading-anchor">⚓</span>
      </div>
      <div class="loading-text-meta">
        <span class="loading-brand">ORCA COMMAND</span>
        <span class="loading-sub">Connecting Marine Bridge Telemetry...</span>
      </div>
    `;

    // 4. Dual-Pane Maritime Command Console Layout
    this.consoleLayout = document.createElement('div');
    this.consoleLayout.className = 'app-layout';

    this.sidebar = new Sidebar();
    this.header = new Header();
    this.chatWindow = new ChatWindow();
    this.operationalPicture = new OperationalPicture();
    this.agentPanel = new AgentPanel();
    this.searchModal = new SearchModal();
    this.settingsModal = new SettingsModal();

    this.mobileBackdrop = document.createElement('div');
    this.mobileBackdrop.className = 'drawer-backdrop';
    this.mobileBackdrop.id = 'mobile-backdrop';

    this.consoleLayout.appendChild(this.sidebar.getElement());

    const centerWorkspace = document.createElement('div');
    centerWorkspace.className = 'main-workspace';

    // Location banner
    this.locationBanner = document.createElement('div');
    this.locationBanner.className = 'orca-location-banner';
    this.locationBanner.style.display = 'none';
    centerWorkspace.appendChild(this.locationBanner);

    centerWorkspace.appendChild(this.header.getElement());

    // Dual-Pane Console Stage
    const dualPaneStage = document.createElement('div');
    dualPaneStage.className = 'console-dual-pane-stage';
    dualPaneStage.appendChild(this.chatWindow.getElement());
    dualPaneStage.appendChild(this.operationalPicture.getElement());

    centerWorkspace.appendChild(dualPaneStage);

    this.consoleLayout.appendChild(centerWorkspace);
    this.consoleLayout.appendChild(this.agentPanel.getElement());
    this.consoleLayout.appendChild(this.mobileBackdrop);
    this.consoleLayout.appendChild(this.searchModal.getElement());
    this.consoleLayout.appendChild(this.settingsModal.getElement());

    // Assemble Top-Level Shell
    this.element.appendChild(this.loadingScreen);
    this.element.appendChild(this.loginPage.getElement());
    this.element.appendChild(this.roleSelectionPage.getElement());
    this.element.appendChild(this.consoleLayout);

    // Initialize toast manager
    ToastManager.getInstance();

    this.attachGlobalEvents();
    this.updateView();

    store.subscribe(() => {
      this.updateView();
      this.updateDrawerBackdrop();
      this.updateLocationBanner();
    });
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private updateView(): void {
    // 1. Initial auth verification check
    if (!store.authInitialized) {
      this.loadingScreen.style.display = 'flex';
      this.loginPage.getElement().style.display = 'none';
      this.roleSelectionPage.getElement().style.display = 'none';
      this.consoleLayout.style.display = 'none';
      return;
    }
    this.loadingScreen.style.display = 'none';

    // 2. Unauthenticated -> Dedicated Full-Page Login
    if (!store.currentUser) {
      this.loginPage.getElement().style.display = 'flex';
      this.roleSelectionPage.getElement().style.display = 'none';
      this.consoleLayout.style.display = 'none';
      return;
    }

    // 3. Logged in, but no role selected OR requested to switch role -> Dedicated Full-Page Role Selection
    if (!store.userCategory || store.isSelectingRole) {
      this.loginPage.getElement().style.display = 'none';
      this.roleSelectionPage.getElement().style.display = 'flex';
      this.consoleLayout.style.display = 'none';
      return;
    }

    // 4. Authenticated with active operational role -> Main Dual-Pane Command Console
    const wasHidden = this.consoleLayout.style.display === 'none';
    this.loginPage.getElement().style.display = 'none';
    this.roleSelectionPage.getElement().style.display = 'none';
    this.consoleLayout.style.display = 'flex';

    if (wasHidden) {
      setTimeout(() => {
        window.dispatchEvent(new Event('resize'));
      }, 50);
    }
  }

  private updateLocationBanner(): void {
    const msg = store.locationBanner;
    if (msg) {
      this.locationBanner.textContent = msg;
      this.locationBanner.style.display = 'block';
    } else {
      this.locationBanner.style.display = 'none';
    }
  }

  private updateDrawerBackdrop(): void {
    const isDrawerOpen = store.mobileSidebarOpen || store.mobileAgentDrawerOpen;
    if (isDrawerOpen) {
      this.mobileBackdrop.classList.add('active');
    } else {
      this.mobileBackdrop.classList.remove('active');
    }
  }

  private attachGlobalEvents(): void {
    // Backdrop click dismisses drawers
    this.mobileBackdrop.addEventListener('click', () => {
      store.toggleMobileSidebar(false);
      store.toggleMobileAgentDrawer(false);
    });

    // Global Keybindings
    window.addEventListener('keydown', (e) => {
      // Escape key closes modals / drawers
      if (e.key === 'Escape') {
        if (store.searchModalOpen) {
          store.toggleSearchModal(false);
          e.preventDefault();
        } else if (store.settingsModalOpen) {
          store.toggleSettingsModal(false);
          e.preventDefault();
        } else if (store.mobileSidebarOpen || store.mobileAgentDrawerOpen) {
          store.toggleMobileSidebar(false);
          store.toggleMobileAgentDrawer(false);
          e.preventDefault();
        }
      }

      // Ctrl + K or Cmd + K for Search
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        store.toggleSearchModal();
      }

      // Ctrl + N or Cmd + N for New Chat
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
        e.preventDefault();
        store.createNewChat();
      }
    });
  }
}
