import { store } from '../../store/appState';
import { MessageList } from './MessageList';
import { Composer } from './Composer';
import { showToast } from '../ui/Toast';

export class ChatWindow {
  private element: HTMLElement;
  private headerBar: HTMLElement;
  private scrollContainer: HTMLElement;
  private suggestionBar: HTMLElement;
  private messageList: MessageList;
  private composer: Composer;
  private shouldAutoScroll = true;

  constructor() {
    this.element = document.createElement('main');
    this.element.className = 'chat-console-pane';

    // Top Language Header
    this.headerBar = document.createElement('div');
    this.headerBar.className = 'chat-console-top-bar';
    this.headerBar.innerHTML = `
      <div class="chat-top-title-col">
        <span class="chat-top-title">Ask ORCA</span>
        <span class="chat-top-sub">Type or speak — English • हिंदी • मराठी</span>
      </div>
      <div class="chat-lang-switchers">
        <button class="chat-lang-btn active" data-lang="en">EN</button>
        <button class="chat-lang-btn" data-lang="hi">हिं</button>
        <button class="chat-lang-btn" data-lang="mr">मरा</button>
      </div>
    `;

    this.scrollContainer = document.createElement('div');
    this.scrollContainer.className = 'chat-scroll-container';

    this.messageList = new MessageList();
    this.composer = new Composer();

    // Suggestion Quick Chips Bar
    this.suggestionBar = document.createElement('div');
    this.suggestionBar.className = 'chat-console-suggestion-bar';
    this.suggestionBar.innerHTML = `
      <button class="chat-sugg-chip" data-q="दुपारी १२ वाजता हवामान काय असेल?">दुपारी १२ वाजता काय?</button>
      <button class="chat-sugg-chip" data-q="Where is the nearest official INCOIS Potential Fishing Zone (PFZ) today?">जवळचे PFZ दाखवा</button>
      <button class="chat-sugg-chip" data-q="Plot a safe navigational route avoiding shallow waters and restricted zones.">सुरक्षित मार्ग दाखवा</button>
      <button class="chat-sugg-chip" data-q="Are there active cyclone or squall warnings near this sector?">जवळपास चक्रीवादळ आहे का?</button>
    `;

    this.scrollContainer.appendChild(this.messageList.getElement());
    this.element.appendChild(this.headerBar);
    this.element.appendChild(this.scrollContainer);
    this.element.appendChild(this.suggestionBar);
    this.element.appendChild(this.composer.getElement());

    this.setupEvents();
    this.setupScrollListener();
    store.subscribe(() => this.handleStateUpdate());
  }

  private setupEvents(): void {
    // Language buttons
    this.headerBar.querySelectorAll('.chat-lang-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this.headerBar.querySelectorAll('.chat-lang-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const lang = btn.getAttribute('data-lang');
        if (lang === 'mr') {
          showToast('मराठी भाषा निवडली', 'info');
        } else if (lang === 'hi') {
          showToast('हिंदी भाषा चयनित', 'info');
        } else {
          showToast('English selected', 'info');
        }
      });
    });

    // Suggestion chips
    this.suggestionBar.querySelectorAll('.chat-sugg-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const q = chip.getAttribute('data-q');
        if (q) store.sendMessage(q);
      });
    });
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  public getComposer(): Composer {
    return this.composer;
  }

  private handleStateUpdate(): void {
    if (store.isStreaming) {
      this.messageList.updateLastMessage();
      if (this.shouldAutoScroll) {
        this.scrollToBottom();
      }
    } else {
      this.messageList.render();
      this.scrollToBottom();
    }
  }

  private setupScrollListener(): void {
    this.scrollContainer.addEventListener('scroll', () => {
      const { scrollTop, scrollHeight, clientHeight } = this.scrollContainer;
      const distanceFromBottom = scrollHeight - (scrollTop + clientHeight);
      this.shouldAutoScroll = distanceFromBottom < 80;
    });
  }

  private scrollToBottom(): void {
    requestAnimationFrame(() => {
      this.scrollContainer.scrollTop = this.scrollContainer.scrollHeight;
    });
  }
}
