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
    const isAuto = store.queryMode === 'auto';
    const isPanel = store.queryMode === 'panel';
    // Auto routing explainability: show last selected agents if available
    const autoLabel = store.getAutoRoutingLabel();
    const autoDesc = autoLabel || 'ORCA chooses the best specialist(s) for your question';

    this.element.innerHTML = `
      <div style="margin-bottom:var(--space-2);display:flex;align-items:center;justify-content:space-between;">
        <span style="font-size:var(--text-xs);font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-tertiary);">
          Answering Mode
        </span>
        <span style="font-size:10px;color:var(--text-tertiary);">${store.queryMode.toUpperCase()}</span>
      </div>

      <!-- AUTO SELECT — default, fast intelligent routing -->
      <div class="agent-card-item ${isAuto ? 'active' : ''}" data-mode="auto" style="${isAuto ? 'border-color:var(--primary);background:rgba(14,124,134,0.08);' : ''}">
        <div class="agent-card-avatar" style="background:linear-gradient(135deg,#0e7c86,#22c55e);color:#fff;">
          ✨
        </div>
        <div class="agent-card-info">
          <div class="agent-card-name">
            <span>✨ AUTO SELECT</span>
            <span class="status-dot online"></span>
          </div>
          <div class="agent-card-role">${isAuto && autoLabel ? autoLabel : 'ORCA chooses the best specialist(s)'}</div>
          <div class="agent-card-desc">${autoDesc}</div>
          <div class="agent-capability-badges">
            <span class="cap-badge">Fast routing</span>
            <span class="cap-badge">Auto specialists</span>
          </div>
        </div>
      </div>

      <!-- PANEL — full deliberation -->
      <div class="agent-card-item ${isPanel ? 'active' : ''}" data-mode="panel" style="margin-top:6px;${isPanel ? 'border-color:var(--primary);' : ''}">
        <div class="agent-card-avatar" style="background:rgba(217,119,6,0.14);color:#D97706;">
          ${ICONS.messageSquare}
        </div>
        <div class="agent-card-info">
          <div class="agent-card-name">
            <span>ORCA Panel — full discussion</span>
            <span class="status-dot ${isPanel ? 'online' : 'idle'}"></span>
          </div>
          <div class="agent-card-role">Every relevant specialist discusses, then reconciles</div>
          <div class="agent-card-desc">Demo / deep analysis — includes round-table debate</div>
        </div>
      </div>

      <div style="margin:10px 0 6px 0;display:flex;align-items:center;gap:8px;">
        <span style="font-size:var(--text-xs);font-weight:600;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-tertiary);">
          Specialists (direct)
        </span>
        <span style="flex:1;height:1px;background:var(--border-default);"></span>
      </div>

      <div style="display:flex;flex-direction:column;gap:8px;">
        ${store.agents.map(agent => AgentCard.render(agent, agent.id === activeAgentId && store.queryMode !== 'auto' && store.queryMode !== 'panel')).join('')}
      </div>

      <!-- Backend addressable specialists (PFZ, Hazard, etc.) for direct mode -->
      <div style="margin-top:8px;display:flex;flex-direction:column;gap:6px;">
        ${store.backendAgents.map(spec => {
          const selected = store.queryMode === 'agent' && store.directAgentKey === spec.key;
          return `
          <div class="agent-card-item ${selected ? 'active' : ''}" data-backend-key="${spec.key}" style="padding:8px 10px;${selected ? 'border-color:var(--primary);background:rgba(14,124,134,0.06);' : ''}">
            <div class="agent-card-avatar" style="width:28px;height:28px;font-size:12px;background:var(--bg-surface);color:var(--text-secondary);">
              ${ICONS.user}
            </div>
            <div class="agent-card-info">
              <div class="agent-card-name" style="font-size:13px;">
                <span>${spec.name}</span>
                ${selected ? '<span class="status-dot online"></span>' : ''}
              </div>
              <div class="agent-card-desc" style="font-size:11px;">${spec.description}</div>
            </div>
          </div>`;
        }).join('')}
      </div>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    const autoCard = this.element.querySelector('[data-mode="auto"]');
    autoCard?.addEventListener('click', () => {
      store.setQueryMode('auto');
      showToast('AUTO SELECT — ORCA will pick the best specialist(s)', 'success');
    });
    const panelCard = this.element.querySelector('[data-mode="panel"]');
    panelCard?.addEventListener('click', () => {
      store.setQueryMode('panel');
      showToast('Panel mode — full deliberation with round-table', 'info');
    });
    const cards = this.element.querySelectorAll('.agent-card-item[data-agent-id]');
    cards.forEach(card => {
      card.addEventListener('click', () => {
        const agentId = card.getAttribute('data-agent-id');
        if (agentId) {
          store.selectAgent(agentId);
          // Also switch to direct mode if user explicitly picks a persona via this list? Keep persona selection separate.
          showToast(`Switched active agent to ${store.getActiveAgent().name}`, 'info');
        }
      });
    });
    const backendCards = this.element.querySelectorAll('[data-backend-key]');
    backendCards.forEach(card => {
      card.addEventListener('click', () => {
        const key = card.getAttribute('data-backend-key');
        if (key) {
          store.setQueryMode('agent');
          store.setDirectAgent(key);
          const spec = store.backendAgents.find(s => s.key === key);
          showToast(`Direct mode: ${spec?.name || key} will answer`, 'info');
        }
      });
    });
  }
}
