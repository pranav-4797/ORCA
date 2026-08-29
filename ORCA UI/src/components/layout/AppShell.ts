import { store } from '../../store/appState';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { ChatWindow } from '../chat/ChatWindow';
import { AgentPanel } from '../agents/AgentPanel';
import { OperationalPicture } from '../map/OperationalPicture';
import { SearchModal } from '../search/SearchModal';
import { SettingsModal } from '../settings/SettingsModal';
import { AuthModal } from '../auth/AuthModal';
import { CategoryModal } from '../auth/CategoryModal';
import { ToastManager } from '../ui/Toast';

export class AppShell {
  private element: HTMLElement;
  private sidebar: Sidebar;
  private header: Header;
  private chatWindow: ChatWindow;
  private operationalPicture: OperationalPicture;
  private agentPanel: AgentPanel;
  private searchModal: SearchModal;
  private settingsModal: SettingsModal;
  private authModal: AuthModal;
  private categoryModal: CategoryModal;
  private mobileBackdrop: HTMLElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'app-layout';

    // Initialize core components
    this.sidebar = new Sidebar();
    this.header = new Header();
    this.chatWindow = new ChatWindow();
    this.operationalPicture = new OperationalPicture();
    this.agentPanel = new AgentPanel();
    this.searchModal = new SearchModal();
    this.settingsModal = new SettingsModal();
    this.authModal = new AuthModal();
    this.categoryModal = new CategoryModal();

    // Mobile Backdrop
    this.mobileBackdrop = document.createElement('div');
    this.mobileBackdrop.className = 'drawer-backdrop';
    this.mobileBackdrop.id = 'mobile-backdrop';

    // Assemble DOM
    this.element.appendChild(this.sidebar.getElement());

    const centerWorkspace = document.createElement('div');
    centerWorkspace.className = 'main-workspace';
    centerWorkspace.appendChild(this.header.getElement());

    // Dual-Pane Maritime Console Stage (Left: Chat, Right: Operations Map & HUD)
    const dualPaneStage = document.createElement('div');
    dualPaneStage.className = 'console-dual-pane-stage';
    dualPaneStage.appendChild(this.chatWindow.getElement());
    dualPaneStage.appendChild(this.operationalPicture.getElement());

    centerWorkspace.appendChild(dualPaneStage);

    this.element.appendChild(centerWorkspace);
    this.element.appendChild(this.agentPanel.getElement());
    this.element.appendChild(this.mobileBackdrop);
    this.element.appendChild(this.searchModal.getElement());
    this.element.appendChild(this.settingsModal.getElement());
    this.element.appendChild(this.authModal.getElement());
    this.element.appendChild(this.categoryModal.getElement());


    // Initialize toast manager
    ToastManager.getInstance();

    this.attachGlobalEvents();
    store.subscribe(() => this.updateDrawerBackdrop());
  }

  public getElement(): HTMLElement {
    return this.element;
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
