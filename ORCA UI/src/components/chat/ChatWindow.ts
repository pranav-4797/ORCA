import { store } from '../../store/appState';
import { MessageList } from './MessageList';
import { Composer } from './Composer';

export class ChatWindow {
  private element: HTMLElement;
  private scrollContainer: HTMLElement;
  private messageList: MessageList;
  private composer: Composer;
  private shouldAutoScroll = true;

  constructor() {
    this.element = document.createElement('main');
    this.element.className = 'main-workspace';

    this.scrollContainer = document.createElement('div');
    this.scrollContainer.className = 'chat-scroll-container';

    this.messageList = new MessageList();
    this.composer = new Composer();

    this.scrollContainer.appendChild(this.messageList.getElement());
    this.element.appendChild(this.scrollContainer);
    this.element.appendChild(this.composer.getElement());

    this.setupScrollListener();
    store.subscribe(() => this.handleStateUpdate());
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
