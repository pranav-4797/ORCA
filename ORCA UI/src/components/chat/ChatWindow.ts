import { store } from '../../store/appState';
import { MessageList } from './MessageList';
import { Composer } from './Composer';
import { showToast } from '../ui/Toast';
import { I18N } from '../../utils/i18n';
import { ICONS } from '../../utils/icons';

export class ChatWindow {
  private element: HTMLElement;
  private scrollContainer: HTMLElement;
  private messageList: MessageList;
  private composer: Composer;
  private shouldAutoScroll = true;

  constructor() {
    this.element = document.createElement('main');
    this.element.className = 'chat-console-pane';

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

  public getElement(): HTMLElement {
    return this.element;
  }

  public getComposer(): Composer {
    return this.composer;
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
