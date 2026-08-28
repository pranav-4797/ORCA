import { Agent } from '../../types/agent';
import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';
import { showToast } from '../ui/Toast';

export class AgentCard {
  public static render(agent: Agent, isActive: boolean): string {
    return `
      <div class="agent-card-item ${isActive ? 'active' : ''}" data-agent-id="${agent.id}">
        <div class="agent-card-avatar" style="background-color:${agent.avatarBg};color:${agent.avatarColor};">
          ${ICONS[agent.icon] || ICONS.bot}
        </div>
        <div class="agent-card-info">
          <div class="agent-card-name">
            <span>${agent.name}</span>
            <span class="status-dot ${agent.status}"></span>
          </div>
          <div class="agent-card-role">${agent.role}</div>
          <div class="agent-card-desc">${agent.description}</div>
          <div class="agent-capability-badges">
            ${agent.capabilities.map(cap => `<span class="cap-badge">${cap}</span>`).join('')}
          </div>
        </div>
      </div>
    `;
  }
}

export class AgentSelector {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'agent-selector-widget';
    this.render();
    store.subscribe(() => this.render());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const activeAgentId = store.activeAgentId;

    this.element.innerHTML = `
      <div style="margin-bottom:var(--space-2);display:flex;align-items:center;justify-content:space-between;">
        <span style="font-size:var(--text-xs);font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-tertiary);">
          Available Agents (${store.agents.length})
        </span>
      </div>

      <div style="display:flex;flex-direction:column;gap:8px;">
        ${store.agents.map(agent => AgentCard.render(agent, agent.id === activeAgentId)).join('')}
      </div>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    const cards = this.element.querySelectorAll('.agent-card-item');
    cards.forEach(card => {
      card.addEventListener('click', () => {
        const agentId = card.getAttribute('data-agent-id');
        if (agentId) {
          store.selectAgent(agentId);
          showToast(`Switched active agent to ${store.getActiveAgent().name}`, 'info');
        }
      });
    });
  }
}
