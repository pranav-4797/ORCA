import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';

export class AgentActivity {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'agent-activity-widget';
    this.render();
    store.subscribe(() => this.render());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const execState = store.executionState;
    const isLive = store.isStreaming;
    const isOpen = store.activityPanelOpen || isLive;
    const hasSteps = execState.steps.length > 0;

    this.element.innerHTML = `
      <div class="activity-toggle-row" style="display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--space-2);">
        <button class="activity-toggle-btn" style="display:flex;align-items:center;gap:6px;background:none;border:none;cursor:pointer;padding:2px 0;">
          <span style="font-size:var(--text-xs);font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:var(--text-tertiary);">
            Agent Trace ${hasSteps ? `(${execState.steps.length})` : ''}
          </span>
          <span style="font-size:10px;color:var(--text-tertiary);">${isOpen ? '▾' : '▸'}</span>
        </button>
        <span class="agent-status-badge">
          <span class="status-dot ${isLive ? 'thinking' : 'idle'}"></span>
          <span>${execState.state}</span>
        </span>
      </div>
      ${isOpen ? `
      <div class="activity-card">
        <div class="activity-header">
          <div class="activity-title">
            <span style="color:var(--accent-primary);">${ICONS.brain}</span>
            <span>${execState.currentAction}</span>
          </div>
        </div>
        <div class="activity-step-list" style="display:flex;">
          ${hasSteps ? execState.steps.map(step => `
            <div class="activity-step-item">
              <span class="step-indicator ${step.status}">
                ${step.status === 'completed' ? ICONS.check : (step.status === 'error' ? ICONS.x : '●')}
              </span>
              <div style="flex:1;">
                <div style="display:flex;align-items:center;justify-content:space-between;">
                  <span style="font-weight:500;color:var(--text-primary);">${step.title}</span>
                  ${step.durationMs ? `<span style="font-size:10px;color:var(--text-tertiary);">${step.durationMs}ms</span>` : ''}
                </div>
                ${step.description ? `<div style="font-size:11px;color:var(--text-tertiary);margin-top:2px;">${step.description}</div>` : ''}
              </div>
            </div>
          `).join('') : `
            <div style="padding:12px;text-align:center;font-size:12px;color:var(--text-tertiary);">
              Trace appears here while agents run.
            </div>
          `}
        </div>
      </div>
      ` : `<div style="font-size:11px;color:var(--text-tertiary);">Trace hidden — click to expand.</div>`}
    `;
    const btn = this.element.querySelector('.activity-toggle-btn') as HTMLElement | null;
    btn?.addEventListener('click', () => store.toggleActivityPanel());
  }
}
