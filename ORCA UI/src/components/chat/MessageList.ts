import { store } from '../../store/appState';
import { MessageItem } from './MessageItem';
import { EmptyState } from './EmptyState';

export class MessageList {
  private element: HTMLElement;
  private messageItemMap: Map<string, MessageItem> = new Map();

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'chat-content-inner';
    this.render();
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  public render(): void {
    const messages = store.getActiveMessages();

    if (messages.length === 0) {
      this.element.innerHTML = '';
      this.messageItemMap.clear();
      const emptyState = new EmptyState();
      this.element.appendChild(emptyState.getElement());
      return;
    }

    // Incremental reconciliation or clean render
    this.element.innerHTML = '';
    this.messageItemMap.clear();

    messages.forEach(msg => {
      const item = new MessageItem(msg);
      this.messageItemMap.set(msg.id, item);
      this.element.appendChild(item.getElement());
    });
  }

  public updateLastMessage(): void {
    const messages = store.getActiveMessages();
    if (messages.length === 0) {
      this.render();
      return;
    }

    const lastMsg = messages[messages.length - 1];
    const existingItem = this.messageItemMap.get(lastMsg.id);

    if (existingItem) {
      existingItem.update(lastMsg);
    } else {
      const item = new MessageItem(lastMsg);
      this.messageItemMap.set(lastMsg.id, item);
      this.element.appendChild(item.getElement());
    }
  }
}
