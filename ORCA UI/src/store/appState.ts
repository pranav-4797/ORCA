import { Chat, AppSettings, ThemeMode } from '../types/chat';
import { Message, Attachment } from '../types/message';
import { Agent, AgentExecutionState, AgentActivityStep } from '../types/agent';
import { MOCK_AGENTS, AVAILABLE_MODELS } from '../data/mockAgents';
import { INITIAL_CHATS, INITIAL_MESSAGES } from '../data/mockChats';
import { MockAIService } from '../services/mockAIService';
import {
  OrcaApiService,
  BACKEND_URL,
  fetchOrcaAgents,
  fetchPfzLive,
  fetchVizGeojson,
  fetchVizSeries,
  OrcaPfzLive,
  OrcaSpecialist,
  OrcaVizSeries,
} from '../services/orcaApiService';
import { generateId } from '../utils/helpers';
import { showToast } from '../components/ui/Toast';
import { User } from 'firebase/auth';
import {
  loginWithGooglePopup,
  logoutUser,
  subscribeToAuth,
  saveUserProfile,
  saveUserChatToFirestore,
  deleteUserChatFromFirestore,
  saveUserMessageToFirestore,
  loadUserSessionsFromFirestore,
  saveUserCategoryProfileToFirestore,
  getUserCategoryProfileFromFirestore,
} from '../services/firebase';
import {
  UserCategoryConfig,
  UserCategoryProfile,
  USER_CATEGORIES,
} from '../types/userCategory';


type StateListener = () => void;

class AppStore {
  private static instance: AppStore;

  // Authentication State
  public currentUser: User | null = null;
  public authInitialized: boolean = false;
  public isSelectingRole: boolean = false;

  // Data State
  public chats: Chat[] = [];
  public messages: Record<string, Message[]> = {};
  public agents: Agent[] = MOCK_AGENTS;
  public models = AVAILABLE_MODELS;

  // Selected State
  public activeChatId: string | null = null;
  public activeAgentId: string = 'general';
  public activeModel: string = 'Gemini 1.5 Pro';

  // Agent Thinking / Activity State
  public executionState: AgentExecutionState = {
    agentId: 'general',
    state: 'idle',
    currentAction: 'Ready to assist',
    steps: []
  };

  // Streaming State
  public isStreaming: boolean = false;
  private currentAbortController: AbortController | null = null;

  // Backend connectivity
  public backendOnline: boolean | null = null; // null = probing
  public backendUrl: string = BACKEND_URL;

  // Device GPS / location (user's real position). gpsStatus:
  //   'granted'  -> live browser GPS captured
  //   'denied'   -> permission denied (banner shown)
  //   'cached'   -> using a previously saved position
  //   'none'     -> no location yet (Panaji last-resort on the backend)
  public gpsCoords: [number, number] | null = null;
  public gpsStatus: 'granted' | 'denied' | 'cached' | 'none' = 'none';
  public locationBanner: string | null = null;

  // Explicit map-tap coordinate selection (Part A2). The user tapped a
  // coastal/offshore point on the map; it is the highest-priority location
  // and overrides GPS / typed / PFZ coordinates. Never snapped.
  public mapPoint: [number, number] | null = null;

  // Operational picture: /viz payloads for the last answered query.
  public vizGeojson: any = null;
  public vizSeries: OrcaVizSeries | null = null;
  public vizSessionId: string | null = null;
  public mapPanelOpen: boolean = true;
  public activityPanelOpen: boolean = false;

// Query routing: 'auto' = ORCA picks best specialist(s) (default, fast);
  // 'panel' = all specialists discuss then reconcile (demo/deep);
  // 'agent' = one named specialist answers directly (no discussion).

  // Official INCOIS PFZ live layer (zone lines + landing centres), refreshed
  // whenever the app comes online. Feed is cached server-side for 10 minutes.
  public pfzLive: OrcaPfzLive | null = null;
  public pfzLiveLoadedAt: number = 0;

  public queryMode: 'auto' | 'panel' | 'agent' = 'auto';
  public directAgentKey: string = '';
  public backendAgents: OrcaSpecialist[] = [
    {
      key: 'ocean_state',
      name: 'Ocean-State Agent',
      description: 'Live SST, waves, wind, tides and chlorophyll',
      requires: [],
    },
    {
      key: 'hazard',
      name: 'Hazard Agent',
      description: 'Safety verdicts + live IMD cyclone/marine alerts',
      requires: ['ocean_state'],
    },
    {
      key: 'pfz',
      name: 'PFZ Agent',
      description: 'Nearest fishing zones from live thermal fronts',
      requires: [],
    },
    {
      key: 'geospatial',
      name: 'Geospatial Agent',
      description: 'Boundary geofencing + weather-aware safe routes',
      requires: [],
    },
    {
      key: 'trend',
      name: 'Trend Agent',
      description: 'Months-long SST/chlorophyll trend analysis',
      requires: [],
    },
  ];

  // UI Drawer / Modal States
  public sidebarCollapsed: boolean = true;
  public mobileSidebarOpen: boolean = false;
  public agentPanelOpen: boolean = false;
  public mobileAgentDrawerOpen: boolean = false;
  public searchModalOpen: boolean = false;
  public settingsModalOpen: boolean = false;
  public authModalOpen: boolean = false;
  public categoryModalOpen: boolean = false;
  public userCategory: UserCategoryProfile | null = null;
  public activeLanguage: 'en' | 'mr' | 'hi' = 'en';
  public activeNavTab: 'overview' | 'chat' | 'sar' | 'system' = 'chat';
  public searchQuery: string = '';

  // Settings
  public settings: AppSettings = {
    theme: 'light',
    sidebarCollapsed: true,
    agentPanelOpen: false,
    soundEnabled: true,
    sendOnEnter: true,
    streamSpeed: 'normal',
    defaultModel: 'Gemini 1.5 Pro',
    codeTheme: 'light',
    fontSize: 'medium'
  };

  private listeners: Set<StateListener> = new Set();

  private constructor() {
    this.loadFromStorage();
    this.preloadLocation();
    this.probeBackend();

    // Listen for Firebase Auth state changes & sync Firestore
    subscribeToAuth(async (user) => {
      this.currentUser = user;
      this.authInitialized = true;
      if (user) {
        void saveUserProfile(user);
        
        // 1. Check user category/role (Check local storage cache first, then Firestore)
        try {
          const cachedRole = localStorage.getItem(`orca_role_${user.uid}`);
          if (cachedRole) {
            this.userCategory = JSON.parse(cachedRole);
            this.isSelectingRole = false;
            this.categoryModalOpen = false;
          }

          const categoryProfile = await getUserCategoryProfileFromFirestore(user.uid);
          if (categoryProfile) {
            this.userCategory = categoryProfile;
            this.isSelectingRole = false;
            this.categoryModalOpen = false;
            localStorage.setItem(`orca_role_${user.uid}`, JSON.stringify(categoryProfile));
          } else if (!this.userCategory) {
            // New user without role selected -> show role selection page
            this.userCategory = null;
            this.isSelectingRole = true;
            this.categoryModalOpen = true;
          }
        } catch (catErr) {
          console.warn('[Firestore] Category check error:', catErr);
          if (!this.userCategory) {
            this.isSelectingRole = true;
          }
        }

        // 2. Load chat history
        try {
          const remoteData = await loadUserSessionsFromFirestore(user.uid);
          if (remoteData && remoteData.chats.length > 0) {
            this.chats = remoteData.chats;
            this.messages = remoteData.messages;

            if (!this.activeChatId || !this.chats.some(c => c.id === this.activeChatId)) {
              this.activeChatId = this.chats[0].id;
            }
            this.notify();
            showToast(`Loaded ${this.chats.length} mission sessions from cloud`, 'success');
          } else {
            // First time login: create clean session in cloud
            const initialChat: Chat = {
              id: generateId('chat'),
              title: 'Mission Briefing',
              createdAt: Date.now(),
              updatedAt: Date.now(),
              agentId: 'orca-nav',
              model: 'llama-3.3-70b-versatile',
              messageCount: 0,
              pinned: false,
            };
            this.chats = [initialChat];
            this.messages = { [initialChat.id]: [] };
            this.activeChatId = initialChat.id;
            void saveUserChatToFirestore(user.uid, initialChat);
            this.notify();
          }
        } catch (e) {
          console.warn('[Firestore] Sync initialization error:', e);
        }
      } else {
        // Not logged in -> reset state
        this.userCategory = null;
        this.isSelectingRole = false;
        this.categoryModalOpen = false;
        this.loadFromStorage();
      }
      this.notify();
    });
  }

  public async loginWithGoogle(): Promise<void> {
    try {
      const user = await loginWithGooglePopup();
      this.currentUser = user;
      this.authInitialized = true;
      if (!this.userCategory) {
        this.isSelectingRole = true;
      }
      this.notify();
      showToast(`Welcome aboard, Officer ${user.displayName || user.email}!`, 'success');
    } catch (err: any) {
      if (err.code !== 'auth/popup-closed-by-user') {
        console.error('Google Auth Error:', err);
        showToast(`Sign in error: ${err.message || err}`, 'error');
      }
    }
  }

  public openRoleSelection(open: boolean = true): void {
    this.isSelectingRole = open;
    this.categoryModalOpen = open;
    this.notify();
  }

  public toggleCategoryModal(open?: boolean): void {
    this.isSelectingRole = open !== undefined ? open : !this.isSelectingRole;
    this.categoryModalOpen = this.isSelectingRole;
    this.notify();
  }

  public async setUserCategory(config: UserCategoryConfig): Promise<void> {
    const profile: UserCategoryProfile = {
      category: config.key,
      roleName: config.name,
      vesselClass: config.vesselClass,
      badgeEmoji: config.icon,
      tagline: config.tagline,
      updatedAt: Date.now(),
    };

    this.userCategory = profile;
    this.isSelectingRole = false;
    this.categoryModalOpen = false;

    if (this.currentUser) {
      localStorage.setItem(`orca_role_${this.currentUser.uid}`, JSON.stringify(profile));
      try {
        await saveUserCategoryProfileToFirestore(this.currentUser.uid, profile);
        showToast(`Operational Profile set to ${config.icon} ${config.name}`, 'success');
      } catch (err) {
        console.warn('Failed to save category profile to Firestore:', err);
        showToast(`Role active for session (${config.name})`, 'info');
      }
    }

    this.notify();
  }

  public setLanguage(lang: 'en' | 'mr' | 'hi'): void {
    this.activeLanguage = lang;
    this.notify();
  }

  public setNavTab(tab: 'overview' | 'chat' | 'sar' | 'system'): void {
    this.activeNavTab = tab;
    if (tab === 'sar') {
      this.toggleAgentPanel(true);
    } else if (tab === 'system') {
      this.toggleSettingsModal(true);
    }
    this.notify();
  }

  public async logout(): Promise<void> {
    try {
      await logoutUser();
      this.currentUser = null;
      this.userCategory = null;
      this.isSelectingRole = false;
      this.categoryModalOpen = false;
      this.chats = [...INITIAL_CHATS];
      this.messages = { ...INITIAL_MESSAGES };
      this.activeChatId = this.chats[0]?.id || null;
      localStorage.removeItem('ai_workspace_chats');
      localStorage.removeItem('ai_workspace_messages');
      this.notify();
      showToast('Signed out from ORCA Command.', 'info');
    } catch (err: any) {
      console.error('Sign Out Error:', err);
      showToast('Error during sign out.', 'error');
    }
  }


  /** Probe the ORCA FastAPI backend; wire proactive alerts when online.
   * Retries every 15 s while offline so starting uvicorn mid-session
   * reconnects without a page reload. */
  private async probeBackend(manual = false): Promise<void> {
    try {
      const res = await fetch(`${BACKEND_URL}/health`, {
        signal: AbortSignal.timeout(2500),
      });
      this.backendOnline = res.ok;
    } catch {
      this.backendOnline = false;
    }
    if (this.backendOnline) {
      if (!this._alertsWired) {
        this._alertsWired = true;
        console.info('[ORCA] backend online at', BACKEND_URL);
        showToast('Connected to ORCA backend', 'success');
        void this.fetchBackendAgents();
        void this.loadPfzLive();
        OrcaApiService.startAlertStream(
          'web-demo-user', 16.9902, 73.3120,
          (alert) => this.injectProactiveAlert(alert),
        );
      }
      this.notify();
      return;
    }
    if (manual || this.backendOnline === false) {
      // Only warn once per outage; keep retrying quietly.
      if (!this._offlineWarned || manual) {
        this._offlineWarned = true;
        showToast(
          `ORCA backend offline at ${BACKEND_URL} — run: uvicorn main:app --port 8000`,
          'error',
        );
        console.warn('[ORCA] backend offline -- falling back to mock service');
      }
      setTimeout(() => this.probeBackend(), 15000);
    }
    this.notify();
  }

  /** Force an immediate reconnect attempt (UI hook). */
  public reconnectBackend(): void {
    this._offlineWarned = false;
    void this.probeBackend(true);
  }

  /** Refresh the addressable-specialist registry from GET /agents. */
  public async fetchBackendAgents(): Promise<void> {
    try {
      this.backendAgents = await fetchOrcaAgents();
      if (!this.backendAgents.some(a => a.key === this.directAgentKey)) {
        this.directAgentKey = this.backendAgents[0]?.key || '';
      }
      console.info('[ORCA] specialist registry loaded', this.backendAgents);
    } catch {
      console.warn('[ORCA] /agents fetch failed -- keeping built-in registry');
    }
    this.notify();
  }

  /** Label describing the currently selected answering path. */
  public getQueryModeLabel(): string {
    if (this.queryMode === 'agent') {
      const spec = this.backendAgents.find(a => a.key === this.directAgentKey);
      return spec ? spec.name : 'Direct agent';
    }
    if (this.queryMode === 'auto') {
      return 'AUTO SELECT';
    }
    return 'ORCA Panel';
  }

  public getAutoRoutingLabel(): string | null {
    if (this.queryMode !== 'auto' || !this.activeChatId) return null;
    const msgs = this.messages[this.activeChatId] || [];
    const last = [...msgs].reverse().find(m => m.role === 'assistant' && (m as any).autoRouting);
    const routing: any = (last as any)?.autoRouting;
    if (!routing) return null;
    const agents = (routing.agents || []).map((a: string) => a.replace('Agent','').trim()).join(' + ');
    return agents ? `AUTO → ${agents}` : null;
  }

  public setQueryMode(mode: 'auto' | 'panel' | 'agent'): void {
    this.queryMode = mode;
    this.notify();
  }

  public setDirectAgent(key: string): void {
    this.directAgentKey = key;
    this.notify();
  }

  /** Record the user's live GPS (or denial) so the map, banner and queries use
   * the real location instead of the Panaji default.
   * A live 'granted' fix is authoritative: it overwrites any stale stored
   * position so a previously-saved city can never outrank where you actually are. */
  public setGps(
    coords: [number, number] | null,
    status: 'granted' | 'denied' | 'cached' | 'none' = coords ? 'granted' : 'none',
  ): void {
    this.gpsCoords = coords;
    this.gpsStatus = status;
    if (status === 'denied' && !coords) {
      this.locationBanner =
        'Location permission denied. Using selected location.';
    } else if (status === 'granted' && coords) {
      // Live fix wins over any stored value -- persist only this and clear
      // stale demo keys so we never come back to an old city.
      this.locationBanner = null;
      try {
        localStorage.setItem('orca_device_gps', JSON.stringify(coords));
        localStorage.setItem('orca_device_gps_ts', String(Date.now()));
        localStorage.removeItem('orca_demo_gps');
      } catch { /* storage unavailable */ }
    } else if (coords) {
      this.locationBanner = null;
    }
    this.notify();
  }

  /** Source of truth for the current location: device GPS -> stored position. */
  public currentLocation(): [number, number] | null {
    return this.gpsCoords;
  }

  /** Record an explicit map-tap coordinate selection. This is the highest
   * priority location for the next query and is sent to the backend as
   * `map_point` (a distinct field from GPS — it must never be snapped). */
  public setMapPoint(coords: [number, number] | null): void {
    this.mapPoint = coords;
    this.notify();
  }

  /** Restore a previously saved GPS position so we never start on Panaji.
   * Only restores if fresh (<5 min) — stale Pune from an old session is cleared. */
  private preloadLocation(): void {
    try {
      const raw = localStorage.getItem('orca_device_gps');
      const ts = Number(localStorage.getItem('orca_device_gps_ts') || 0);
      if (raw && ts && Date.now() - ts < 300000) {
        const v = JSON.parse(raw);
        if (Array.isArray(v) && v.length >= 2) {
          this.gpsCoords = [Number(v[0]), Number(v[1])];
          this.gpsStatus = 'cached';
        }
      } else if (raw && !ts) {
        // Legacy stale entry — clear Pune ghost
        localStorage.removeItem('orca_device_gps');
        localStorage.removeItem('orca_demo_gps');
      }
    } catch { /* no stored position */ }
  }

  /** Pull the operational picture (map GeoJSON + hourly series) for the
   * session that just produced an answer. */
  public async loadViz(sessionId: string): Promise<void> {
    try {
      const [geojson, series] = await Promise.all([
        fetchVizGeojson(sessionId),
        fetchVizSeries(sessionId),
      ]);
      this.vizGeojson = geojson;
      this.vizSeries = series;
      this.vizSessionId = sessionId;
      this.mapPanelOpen = true;
    } catch {
      // 404 when the query produced no mappable data -- keep previous view.
    }
    this.notify();
  }

  public setSyntheticViz(geojson: any, sessionId: string): void {
    this.vizGeojson = geojson;
    this.vizSessionId = sessionId;
    this.mapPanelOpen = true;
    this.notify();
  }

  public toggleMapPanel(open?: boolean): void {
    this.mapPanelOpen = open !== undefined ? open : !this.mapPanelOpen;
    this.notify();
  }

  /** Pull the official INCOIS PFZ feed (zone lines + landing centres) once
   * when the backend comes online; the OceanMap renders it as a base layer.
   * A failure here is non-fatal: the map simply keeps the viz-only view. */
  public async loadPfzLive(): Promise<void> {
    const feed = await fetchPfzLive();
    if (feed) {
      this.pfzLive = feed;
      this.pfzLiveLoadedAt = Date.now();
      this.notify();
    }
  }

  public toggleActivityPanel(open?: boolean): void {
    this.activityPanelOpen = open !== undefined ? open : !this.activityPanelOpen;
    this.notify();
  }

  private _alertsWired = false;
  private _offlineWarned = false;

  /** Push a server-initiated proactive alert into the active chat. */
  public injectProactiveAlert(alert: {
    title?: string; message?: string; severity?: string; language?: string;
  }): void {
    const sev = alert.severity || 'INFO';
    const icon = sev === 'UNSAFE' ? '🔴' : sev === 'CAUTION' ? '🟠' : '🔔';
    const content =
      `> [!WARNING]\n> ${icon} PROACTIVE SAFETY ALERT (${sev}) — ${alert.title || ''}\n\n` +
      `${alert.message || ''}\n\n*Pushed by ORCA's Proactive Monitor Agent — no query required.*`;

    let chatId = this.activeChatId;
    if (!chatId) {
      chatId = this.createNewChat('orca-nav');
    }
    if (!this.messages[chatId]) this.messages[chatId] = [];
    this.messages[chatId].push({
      id: generateId('msg-alert'),
      chatId,
      role: 'assistant',
      content,
      timestamp: Date.now(),
      agentId: 'orca-weather',
      modelUsed: 'Proactive Monitor',
    });
    const chat = this.chats.find((c) => c.id === chatId);
    if (chat) {
      chat.messageCount = this.messages[chatId].length;
      chat.updatedAt = Date.now();
      chat.lastMessagePreview = `ALERT: ${(alert.title || '').slice(0, 50)}`;
    }
    showToast(`Proactive alert: ${alert.title || sev}`, sev === 'UNSAFE' ? 'error' : 'info');
    this.notify();
  }

  public static getInstance(): AppStore {
    if (!AppStore.instance) {
      AppStore.instance = new AppStore();
    }
    return AppStore.instance;
  }

  public subscribe(listener: StateListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify(): void {
    this.saveToStorage();
    this.listeners.forEach(fn => fn());
  }

  private loadFromStorage(): void {
    try {
      const storedSettings = localStorage.getItem('ai_workspace_settings');
      if (storedSettings) {
        this.settings = { ...this.settings, ...JSON.parse(storedSettings) };
      }

      const storedChats = localStorage.getItem('ai_workspace_chats');
      if (storedChats) {
        this.chats = JSON.parse(storedChats);
      } else {
        this.chats = [...INITIAL_CHATS];
      }

      const storedMessages = localStorage.getItem('ai_workspace_messages');
      if (storedMessages) {
        this.messages = JSON.parse(storedMessages);
      } else {
        this.messages = { ...INITIAL_MESSAGES };
      }

      const storedActiveChat = localStorage.getItem('ai_workspace_active_chat');
      if (storedActiveChat && this.chats.some(c => c.id === storedActiveChat)) {
        this.activeChatId = storedActiveChat;
      } else if (this.chats.length > 0) {
        this.activeChatId = this.chats[0].id;
      }

      // Sync active agent & model from active chat
      if (this.activeChatId) {
        const chat = this.chats.find(c => c.id === this.activeChatId);
        if (chat) {
          this.activeAgentId = chat.agentId;
          this.activeModel = chat.model;
        }
      }
    } catch (e) {
      console.warn('Could not load from localStorage, using defaults', e);
      this.chats = [...INITIAL_CHATS];
      this.messages = { ...INITIAL_MESSAGES };
      this.activeChatId = this.chats[0]?.id || null;
    }

    this.applyTheme(this.settings.theme);
  }

  private saveToStorage(): void {
    try {
      localStorage.setItem('ai_workspace_settings', JSON.stringify(this.settings));
      localStorage.setItem('ai_workspace_chats', JSON.stringify(this.chats));
      localStorage.setItem('ai_workspace_messages', JSON.stringify(this.messages));
      if (this.activeChatId) {
        localStorage.setItem('ai_workspace_active_chat', this.activeChatId);
      }
    } catch (e) {
      // Storage might be quota-limited or disabled
    }
  }

  // Theme Handling (Always White / Light Mode)
  public setTheme(_theme: ThemeMode = 'light'): void {
    this.settings.theme = 'light';
    this.applyTheme('light');
    this.notify();
  }

  public applyTheme(_theme?: ThemeMode): void {
    document.documentElement.setAttribute('data-theme', 'light');
    document.documentElement.classList.remove('dark');
    document.documentElement.classList.add('light');
  }

  // Navigation & Chat Management
  public selectChat(chatId: string | null): void {
    this.activeChatId = chatId;
    if (chatId) {
      const chat = this.chats.find(c => c.id === chatId);
      if (chat) {
        this.activeAgentId = chat.agentId;
        this.activeModel = chat.model;
      }
    }
    this.mobileSidebarOpen = false;
    this.notify();
  }

  public createNewChat(initialAgentId?: string, initialPrompt?: string): string {
    const agentId = initialAgentId || this.activeAgentId || 'general';
    const agent = this.agents.find(a => a.id === agentId) || this.agents[0];

    const newChat: Chat = {
      id: generateId('chat'),
      title: initialPrompt ? initialPrompt.slice(0, 30) + '...' : 'New Conversation',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      agentId: agent.id,
      model: agent.defaultModel,
      messageCount: 0,
      pinned: false
    };

    this.chats.unshift(newChat);
    this.messages[newChat.id] = [];
    this.activeChatId = newChat.id;
    this.activeAgentId = agent.id;
    this.activeModel = agent.defaultModel;
    this.mobileSidebarOpen = false;

    this.executionState = {
      agentId: agent.id,
      state: 'idle',
      currentAction: 'Ready to assist',
      steps: []
    };

    if (this.currentUser) {
      void saveUserChatToFirestore(this.currentUser.uid, newChat);
    }

    this.notify();
    return newChat.id;
  }

  public deleteChat(chatId: string): void {
    this.chats = this.chats.filter(c => c.id !== chatId);
    delete this.messages[chatId];

    if (this.currentUser) {
      void deleteUserChatFromFirestore(this.currentUser.uid, chatId);
    }

    if (this.activeChatId === chatId) {
      this.activeChatId = this.chats.length > 0 ? this.chats[0].id : null;
      if (this.activeChatId) {
        const chat = this.chats.find(c => c.id === this.activeChatId);
        if (chat) {
          this.activeAgentId = chat.agentId;
          this.activeModel = chat.model;
        }
      }
    }
    this.notify();
  }

  public renameChat(chatId: string, newTitle: string): void {
    const chat = this.chats.find(c => c.id === chatId);
    if (chat && newTitle.trim()) {
      chat.title = newTitle.trim();
      chat.updatedAt = Date.now();
      if (this.currentUser) {
        void saveUserChatToFirestore(this.currentUser.uid, chat);
      }
      this.notify();
    }
  }

  public togglePinChat(chatId: string): void {
    const chat = this.chats.find(c => c.id === chatId);
    if (chat) {
      chat.pinned = !chat.pinned;
      chat.updatedAt = Date.now();
      if (this.currentUser) {
        void saveUserChatToFirestore(this.currentUser.uid, chat);
      }
      this.notify();
    }
  }

  // Agent & Model Selection
  public selectAgent(agentId: string): void {
    const agent = this.agents.find(a => a.id === agentId);
    if (!agent) return;

    this.activeAgentId = agentId;
    this.activeModel = agent.defaultModel;

    if (this.activeChatId) {
      const chat = this.chats.find(c => c.id === this.activeChatId);
      if (chat) {
        chat.agentId = agentId;
        chat.model = agent.defaultModel;
      }
    }

    this.executionState = {
      agentId: agent.id,
      state: 'idle',
      currentAction: `Agent ${agent.name} active`,
      steps: []
    };

    this.notify();
  }

  public selectModel(modelName: string): void {
    this.activeModel = modelName;
    if (this.activeChatId) {
      const chat = this.chats.find(c => c.id === this.activeChatId);
      if (chat) {
        chat.model = modelName;
      }
    }
    this.notify();
  }

  public getGuestUserMessageCount(): number {
    let count = 0;
    for (const msgs of Object.values(this.messages)) {
      count += msgs.filter(m => m.role === 'user').length;
    }
    return count;
  }

  public isGuestLimitReached(): boolean {
    if (this.currentUser) return false;
    return this.getGuestUserMessageCount() >= 3;
  }

  // Messaging & Simulated Streaming
  public async sendMessage(
    prompt: string,
    attachments: Attachment[] = [],
    voice?: { blob: Blob },
  ): Promise<void> {
    if (!prompt.trim() && attachments.length === 0 && !voice) return;
    if (this.isStreaming) return;

    // Enforce Mandatory Google Sign-In after 3 guest messages
    if (!this.currentUser && this.isGuestLimitReached()) {
      this.toggleAuthModal(true);
      showToast('Guest limit reached (3/3 free queries). Please sign in with Google to continue.', 'error');
      return;
    }

    let chatId = this.activeChatId;
    let isNew = false;

    if (!chatId) {
      chatId = this.createNewChat(this.activeAgentId, prompt);
      isNew = true;
    }

    const currentChat = this.chats.find(c => c.id === chatId);
    if (!currentChat) return;

    // 1. Add User Message (voice queries show a mic marker until transcribed)
    const userMsg: Message = {
      id: generateId('msg-user'),
      chatId,
      role: 'user',
      content: prompt.trim() || '🎙️ *voice message*',
      timestamp: Date.now(),
      attachments: attachments.length > 0 ? attachments : undefined
    };

    if (!this.messages[chatId]) {
      this.messages[chatId] = [];
    }
    this.messages[chatId].push(userMsg);

    // Update chat title if it's the first message or a placeholder
    if (isNew || currentChat.messageCount === 0 || currentChat.title === 'New Conversation') {
      currentChat.title = prompt.slice(0, 35) + (prompt.length > 35 ? '...' : '');
    }

    currentChat.messageCount = this.messages[chatId].length;
    currentChat.updatedAt = Date.now();
    currentChat.lastMessagePreview = prompt.slice(0, 60);

    if (this.currentUser) {
      void saveUserChatToFirestore(this.currentUser.uid, currentChat);
      void saveUserMessageToFirestore(this.currentUser.uid, chatId, userMsg);
    }

    // 2. Prepare Assistant Message Placeholder
    const assistantMsgId = generateId('msg-ai');
    const answeringPath =
      this.queryMode === 'agent'
        ? `${this.getQueryModeLabel()} (direct)`
        : this.queryMode === 'auto'
        ? 'AUTO SELECT — ORCA picks best specialist(s)'
        : 'ORCA Panel — agents discussed';
    const assistantMsg: Message = {
      id: assistantMsgId,
      chatId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      agentId: this.activeAgentId,
      modelUsed: answeringPath,
      isStreaming: true,
      activitySteps: []
    };

    this.messages[chatId].push(assistantMsg);

    // 3. Initiate Streaming State
    this.isStreaming = true;
    this.currentAbortController = new AbortController();

    this.executionState = {
      agentId: this.activeAgentId,
      state: 'thinking',
      currentAction: 'Analyzing user request...',
      steps: [],
      startedAt: Date.now()
    };

    this.notify();

    let aiService: { sendMessage: typeof MockAIService.prototype.sendMessage };
    if (this.backendOnline === false) {
      // One quick re-probe before degrading to the mock demo service.
      await this.probeBackend();
    }
    if (this.backendOnline === false) {
      showToast('Backend offline — showing SIMULATED demo response', 'error');
      aiService = MockAIService.getInstance();
    } else {
      aiService = OrcaApiService.getInstance();
    }

    try {
      await aiService.sendMessage({
        chatId,
        prompt,
        agentId: this.activeAgentId,
        model: this.activeModel,
        attachments,
        queryMode: this.queryMode,
        targetAgent: this.directAgentKey || undefined,
        vesselClass: this.userCategory?.vesselClass || 'small_fishing_boat',
        userCategory: this.userCategory?.category || 'fisherman',
        fleetDemoLevel: (OrcaApiService as any).getFleetDemoLevel ? (OrcaApiService as any).getFleetDemoLevel() : null,
        windDemoScenario: (OrcaApiService as any).getWindDemoScenario ? (OrcaApiService as any).getWindDemoScenario() : null,
        mapPoint: this.mapPoint,
        voiceBlob: voice?.blob,
        speakReply: Boolean(voice),
        abortSignal: this.currentAbortController.signal,
        onChunk: (chunk) => {
          if (chunk.type === 'activity' && chunk.activityStep) {
            const step = chunk.activityStep;
            const existingIdx = this.executionState.steps.findIndex(s => s.id === step.id);
            if (existingIdx >= 0) {
              this.executionState.steps[existingIdx] = step;
            } else {
              this.executionState.steps.push(step);
            }
            this.executionState.currentAction = step.title;
            this.executionState.state = 'executing';

            // Also attach to message
            assistantMsg.activitySteps = [...this.executionState.steps];
            this.notify();
          } else if (chunk.type === 'token' && chunk.content) {
            // Immediate rendering path sends full answer as one token; avoid += duplication if already full
            if (chunk.content.length > 200 && assistantMsg.content.length === 0) {
              assistantMsg.content = chunk.content;
            } else {
              assistantMsg.content += chunk.content;
            }
            this.executionState.state = 'executing';
            this.executionState.currentAction = 'Generating structured response...';
            this.notify();
          } else if (chunk.type === 'done') {
            assistantMsg.isStreaming = false;
            assistantMsg.tokens = chunk.tokens;
            // Structured status takes priority for HUD (fixes UNSAFE→SAFE bug) — merged with guest limit
            if ((chunk as any).status) {
              (assistantMsg as any).status = (chunk as any).status;
            } else if ((chunk as any).content) {
              if (!assistantMsg.content) assistantMsg.content = (chunk as any).content;
            }
            if ((chunk as any).hudMetrics) {
              (assistantMsg as any).hudMetrics = (chunk as any).hudMetrics;
            }
            if ((chunk as any).routing) {
              (assistantMsg as any).autoRouting = (chunk as any).routing;
              const agents = ((chunk as any).routing.agents || []).map((a: string) => a.replace('Agent','').trim()).join(' + ');
              if (agents && this.queryMode === 'auto') {
                assistantMsg.modelUsed = `AUTO SELECT → ${agents}`;
              }
            }
            if ((chunk as any).timings) {
              const total = (chunk as any).timings.total_ms;
              if (total) {
                assistantMsg.modelUsed = `${assistantMsg.modelUsed} · ${total}ms`;
              }
            }
            if ((chunk as any).fleetConvergence) {
              (assistantMsg as any).fleetConvergence = (chunk as any).fleetConvergence;
            }
            if ((chunk as any).windDivergence) {
              (assistantMsg as any).windDivergence = (chunk as any).windDivergence;
            }
            if (!(chunk as any).content && assistantMsg.content) {
            } else if ((chunk as any).content && !assistantMsg.content) {
              assistantMsg.content = (chunk as any).content;
            }
            this.executionState.state = 'completed';
            this.executionState.currentAction = 'Completed response';
            this.executionState.finishedAt = Date.now();
            currentChat.lastMessagePreview = assistantMsg.content.slice(0, 60);
            currentChat.messageCount = this.messages[chatId].length;
            if (this.currentUser) {
              void saveUserChatToFirestore(this.currentUser.uid, currentChat);
              void saveUserMessageToFirestore(this.currentUser.uid, chatId, assistantMsg);
            } else {
              // Check if guest limit is reached after this 3rd message
              if (this.isGuestLimitReached()) {
                setTimeout(() => {
                  if (!this.currentUser) {
                    this.toggleAuthModal(true);
                  }
                }, 1000);
              }
            }
            void this.loadViz(chatId); // refresh map + charts for this answer
          } else if (chunk.type === 'error') {
            assistantMsg.isStreaming = false;
            if (chunk.error) {
              assistantMsg.content += `\n\n*[${chunk.error}]*`;
            }
            this.executionState.state = 'error';
            this.executionState.currentAction = chunk.error || 'Generation stopped';
          }
        }
      });
    } catch (err: any) {
      console.error('AI Service execution error:', err);
      assistantMsg.isStreaming = false;
      assistantMsg.content += '\n\n*(An error occurred during generation)*';
      this.executionState.state = 'error';
      this.executionState.currentAction = 'Error encountered';
    } finally {
      this.isStreaming = false;
      this.currentAbortController = null;
      assistantMsg.isStreaming = false;
      if (this.currentUser) {
        void saveUserChatToFirestore(this.currentUser.uid, currentChat);
        void saveUserMessageToFirestore(this.currentUser.uid, chatId, assistantMsg);
      }
      this.notify();
    }
  }

  public stopGeneration(): void {
    if (this.currentAbortController) {
      this.currentAbortController.abort();
      this.isStreaming = false;
      this.currentAbortController = null;
      this.executionState.state = 'completed';
      this.executionState.currentAction = 'Stopped by user';

      if (this.activeChatId && this.messages[this.activeChatId]) {
        const lastMsg = this.messages[this.activeChatId][this.messages[this.activeChatId].length - 1];
        if (lastMsg && lastMsg.role === 'assistant') {
          lastMsg.isStreaming = false;
        }
      }
      this.notify();
    }
  }

  public regenerateResponse(messageId: string): void {
    if (!this.activeChatId || this.isStreaming) return;
    const msgList = this.messages[this.activeChatId];
    if (!msgList) return;

    const targetIdx = msgList.findIndex(m => m.id === messageId);
    if (targetIdx <= 0) return;

    // Find the preceding user message
    const userMsg = msgList[targetIdx - 1];
    if (userMsg && userMsg.role === 'user') {
      // Remove this assistant message and any subsequent messages
      this.messages[this.activeChatId] = msgList.slice(0, targetIdx);
      this.sendMessage(userMsg.content, userMsg.attachments);
    }
  }

  public setMessageReaction(messageId: string, reaction: 'like' | 'dislike'): void {
    if (!this.activeChatId || !this.messages[this.activeChatId]) return;
    const msg = this.messages[this.activeChatId].find(m => m.id === messageId);
    if (msg) {
      if (msg.reactions?.type === reaction) {
        msg.reactions = { type: null };
      } else {
        msg.reactions = { type: reaction };
      }
      if (this.currentUser) {
        void saveUserMessageToFirestore(this.currentUser.uid, this.activeChatId, msg);
      }
      this.notify();
    }
  }

  public editMessage(messageId: string, newContent: string): void {
    if (!this.activeChatId || !this.messages[this.activeChatId]) return;
    const msgList = this.messages[this.activeChatId];
    const targetIdx = msgList.findIndex(m => m.id === messageId);
    if (targetIdx < 0) return;

    const msg = msgList[targetIdx];
    if (!msg.editHistory) msg.editHistory = [];
    msg.editHistory.push({ content: msg.content, timestamp: Date.now() });

    msg.content = newContent;
    msg.isEdited = true;

    if (this.currentUser) {
      void saveUserMessageToFirestore(this.currentUser.uid, this.activeChatId, msg);
    }

    // If it's a user message, truncate everything after and re-generate
    if (msg.role === 'user') {
      this.messages[this.activeChatId] = msgList.slice(0, targetIdx + 1);
      this.sendMessage(newContent, msg.attachments);
    } else {
      this.notify();
    }
  }

  public clearChat(chatId: string): void {
    if (this.messages[chatId]) {
      this.messages[chatId] = [];
      const chat = this.chats.find(c => c.id === chatId);
      if (chat) {
        chat.messageCount = 0;
        chat.lastMessagePreview = '';
      }
      this.notify();
    }
  }

  // UI Toggles
  public toggleSidebar(): void {
    this.sidebarCollapsed = !this.sidebarCollapsed;
    this.settings.sidebarCollapsed = this.sidebarCollapsed;
    this.notify();
  }

  public toggleMobileSidebar(open?: boolean): void {
    this.mobileSidebarOpen = open !== undefined ? open : !this.mobileSidebarOpen;
    this.notify();
  }

  public toggleAgentPanel(open?: boolean): void {
    this.agentPanelOpen = open !== undefined ? open : !this.agentPanelOpen;
    this.settings.agentPanelOpen = this.agentPanelOpen;
    this.notify();
  }

  public toggleMobileAgentDrawer(open?: boolean): void {
    this.mobileAgentDrawerOpen = open !== undefined ? open : !this.mobileAgentDrawerOpen;
    this.notify();
  }

  public toggleSearchModal(open?: boolean): void {
    this.searchModalOpen = open !== undefined ? open : !this.searchModalOpen;
    this.notify();
  }

  public toggleSettingsModal(open?: boolean): void {
    this.settingsModalOpen = open !== undefined ? open : !this.settingsModalOpen;
    this.notify();
  }

  public toggleAuthModal(open?: boolean): void {
    this.authModalOpen = open !== undefined ? open : !this.authModalOpen;
    this.notify();
  }

  public setSearchQuery(q: string): void {
    this.searchQuery = q;
    this.notify();
  }

  // Getters
  public getActiveChat(): Chat | undefined {
    return this.chats.find(c => c.id === this.activeChatId);
  }

  public getActiveAgent(): Agent {
    return this.agents.find(a => a.id === this.activeAgentId) || this.agents[0];
  }

  public getActiveMessages(): Message[] {
    if (!this.activeChatId) return [];
    return this.messages[this.activeChatId] || [];
  }
}

export const store = AppStore.getInstance();
