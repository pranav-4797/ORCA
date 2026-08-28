import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';
import { formatRelativeDate } from '../../utils/helpers';

export class SearchModal {
  private element: HTMLElement;
  private input!: HTMLInputElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'modal-backdrop';
    this.render();
    store.subscribe(() => this.updateVisibility());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private updateVisibility(): void {
    if (store.searchModalOpen) {
      this.element.classList.add('active');
      this.render();
      setTimeout(() => {
        const inputEl = this.element.querySelector('#modal-search-input') as HTMLInputElement;
        inputEl?.focus();
      }, 50);
    } else {
      this.element.classList.remove('active');
    }
  }

  private render(): void {
    const query = store.searchQuery.toLowerCase().trim();

    // Filter chats by title or message contents
    const matchedChats = store.chats.filter(c => {
      if (!query) return true;
      if (c.title.toLowerCase().includes(query)) return true;
      if (c.tags?.some(t => t.toLowerCase().includes(query))) return true;

      // Check messages
      const msgs = store.messages[c.id] || [];
      return msgs.some(m => m.content.toLowerCase().includes(query));
    });

    this.element.innerHTML = `
      <div class="modal-container" style="max-width: 600px;">
        <div class="modal-header" style="padding:12px 16px;border-bottom:1px solid var(--border-subtle);display:flex;align-items:center;gap:10px;">
          <span style="color:var(--text-tertiary);">${ICONS.search}</span>
          <input
            type="text"
            id="modal-search-input"
            value="${store.searchQuery}"
            placeholder="Search conversations, code, and keywords..."
            style="flex:1;font-size:15px;color:var(--text-primary);"
          />
          <button class="icon-btn" id="btn-close-search" title="Close Search" aria-label="Close Search">
            ${ICONS.x}
          </button>
        </div>

        <div class="modal-body" style="padding:10px;max-height:380px;overflow-y:auto;">
          <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-tertiary);padding:4px 8px;margin-bottom:4px;">
            ${query ? `Results (${matchedChats.length})` : 'Recent Conversations'}
          </div>

          <div style="display:flex;flex-direction:column;gap:4px;">
            ${matchedChats.length > 0 ? matchedChats.map((c, idx) => {
              const agent = store.agents.find(a => a.id === c.agentId);
              return `
                <div class="search-result-item ${idx === 0 ? 'selected' : ''}" data-chat-id="${c.id}" style="padding:8px 12px;border-radius:var(--radius-md);background:var(--bg-card);border:1px solid var(--border-subtle);cursor:pointer;display:flex;align-items:center;justify-content:space-between;">
                  <div style="display:flex;align-items:center;gap:10px;min-width:0;">
                    <span style="color:${agent?.avatarColor || 'var(--accent-primary)'};">${ICONS[agent?.icon || 'bot'] || ICONS.messageSquare}</span>
                    <div style="min-width:0;">
                      <div style="font-weight:500;font-size:13.5px;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${c.title}</div>
                      ${c.lastMessagePreview ? `<div style="font-size:11.5px;color:var(--text-tertiary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${c.lastMessagePreview}</div>` : ''}
                    </div>
                  </div>
                  <span style="font-size:11px;color:var(--text-tertiary);flex-shrink:0;margin-left:8px;">${formatRelativeDate(c.updatedAt)}</span>
                </div>
              `;
            }).join('') : `
              <div style="padding:30px 10px;text-align:center;color:var(--text-tertiary);font-size:13px;">
                No matching conversations found for "<strong>${store.searchQuery}</strong>"
              </div>
            `}
          </div>
        </div>

        <div class="modal-footer" style="padding:8px 16px;font-size:11px;color:var(--text-tertiary);display:flex;justify-content:space-between;">
          <span>Use <strong>↑</strong> <strong>↓</strong> to navigate, <strong>Enter</strong> to select</span>
          <kbd style="font-family:var(--font-mono);background:var(--bg-badge);padding:1px 5px;border-radius:3px;border:1px solid var(--border-subtle);">ESC to close</kbd>
        </div>
      </div>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    // Backdrop click
    this.element.addEventListener('click', (e) => {
      if (e.target === this.element) {
        store.toggleSearchModal(false);
      }
    });

    // Close button
    this.element.querySelector('#btn-close-search')?.addEventListener('click', () => {
      store.toggleSearchModal(false);
    });

    // Search input
    const input = this.element.querySelector('#modal-search-input') as HTMLInputElement;
    input?.addEventListener('input', () => {
      store.setSearchQuery(input.value);
    });

    // Item clicks
    const items = this.element.querySelectorAll('.search-result-item');
    items.forEach(item => {
      item.addEventListener('click', () => {
        const chatId = item.getAttribute('data-chat-id');
        if (chatId) {
          store.selectChat(chatId);
          store.toggleSearchModal(false);
        }
      });
    });
  }
}
