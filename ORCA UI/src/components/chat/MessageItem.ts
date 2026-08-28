import { Message } from '../../types/message';
import { store } from '../../store/appState';
import { renderMarkdown } from '../../utils/markdown';
import { formatTime, copyToClipboard } from '../../utils/helpers';
import { ICONS } from '../../utils/icons';
import { showToast } from '../ui/Toast';

interface VerdictData {
  status: 'safe' | 'caution' | 'critical' | 'unsafe' | 'info';
  title: string;
  summary: string;
  metrics: { label: string; value: string }[];
  provenance: string[];
  conflict?: string;
  cleanContent: string;
}

export class MessageItem {
  private element: HTMLElement;
  private message: Message;

  constructor(message: Message) {
    this.message = message;
    this.element = document.createElement('div');
    this.element.className = `message-wrapper ${message.role}`;
    this.render();
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  public update(newMessage: Message): void {
    this.message = newMessage;
    this.render();
  }

  private render(): void {
    const isUser = this.message.role === 'user';
    const isStreaming = this.message.isStreaming;

    if (isUser) {
      this.renderUserMessage();
    } else {
      this.renderAssistantMessage(isStreaming || false);
    }

    this.attachEvents();
  }

  private renderUserMessage(): void {
    const formattedTime = formatTime(this.message.timestamp);

    this.element.innerHTML = `
      <div class="message-bubble-user animate-fade-in">
        ${this.message.attachments && this.message.attachments.length > 0 ? `
          <div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap;">
            ${this.message.attachments.map(att => `
              <div class="attachment-chip" style="font-size:11px;">
                <span>${ICONS.paperclip}</span>
                <span>${att.name}</span>
              </div>
            `).join('')}
          </div>
        ` : ''}
        <div class="user-msg-content">${renderMarkdown(this.message.content)}</div>
        <div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:6px;font-size:11px;color:var(--text-tertiary);">
          <span>${formattedTime}</span>
          <button class="msg-action-btn btn-edit-msg" title="Edit Message">${ICONS.edit}</button>
        </div>
      </div>
    `;
  }

  private parseVerdict(rawContent: string): VerdictData | null {
    if (!rawContent) return null;

    // 1) PREFER structured status from backend if available (authoritative, no text inference).
    // MessageItem is called with this.message which now carries .status; check it first.
    const structuredStatus = (this.message as any)?.status as string | undefined;
    if (structuredStatus) {
      const norm = structuredStatus.trim().toUpperCase();
      // Exact normalized matching — NEVER substring match SAFE inside UNSAFE.
      const exactTitleAndStatus = this.statusToVerdict(norm, rawContent);
      if (exactTitleAndStatus) return exactTitleAndStatus;
    }

    // Detect verdict patterns: e.g. > [!IMPORTANT] > 🟢 **VERDICT: SAFE** — ...
    const verdictRegex = /(?:>\s*\[!IMPORTANT\]\s*\n>\s*)?(?:[🟢🟠🔴⚪ℹ️●]\s*)?\*{0,2}(?:VERDICT|Overall\s*Status):\s*(SAFE(?:\s*TO\s*SAIL)?(?:\s*\(ALL\s*CLEAR\))?|CAUTION|UNSAFE|CRITICAL|INFO)\*{0,2}(?:\s*—\s*([^\n\r]+))?/i;
    const match = rawContent.match(verdictRegex);

    if (!match) {
      // Fallback: only trigger on explicit full phrase, but still avoid UNSAFE->SAFE misclass.
      // Require that UNSAFE not appear near SAFE TO SAIL.
      const upper = rawContent.toUpperCase();
      const hasUnsafe = /\bUNSAFE\b/.test(upper) || /\bCRITICAL\b/.test(upper);
      if (hasUnsafe) {
        return {
          status: 'critical',
          title: '🔴 CRITICAL HAZARD · DO NOT VENTURE',
          summary: 'Hazardous conditions detected — do not venture out.',
          metrics: this.extractMetrics(rawContent),
          provenance: this.extractProvenance(rawContent),
          cleanContent: rawContent.replace(/(?:>\s*\[!IMPORTANT\]\s*\n(?:>\s*[^\n]+\n*)+)/i, '').trim() || rawContent,
        };
      }
      if (/SAFE\s*TO\s*SAIL/i.test(rawContent)) {
        return {
          status: 'safe',
          title: '🟢 ALL CLEAR · SAFE TO SAIL',
          summary: 'Conditions within standard navigational and maritime safety thresholds.',
          metrics: this.extractMetrics(rawContent),
          provenance: this.extractProvenance(rawContent),
          cleanContent: rawContent,
        };
      }
      return null;
    }

    // Normalize matched status: strip extra qualifiers for exact comparison
    const rawMatched = match[1].toUpperCase().trim().replace(/\s+/g, ' ');
    // Exact matching first — order matters: UNSAFE/CRITICAL before SAFE to avoid substring bug.
    // "UNSAFE".includes("SAFE") === true, so we never use includes() for SAFE.
    let status: 'safe' | 'caution' | 'critical' | 'unsafe' | 'info' = 'info';
    let title = 'MISSION ADVISORY';

    // Use exact equality checks against normalized variants
    const isUnsafe = rawMatched === 'UNSAFE' || rawMatched === 'CRITICAL';
    const isCaution = rawMatched === 'CAUTION';
    const isSafe = rawMatched === 'SAFE' || rawMatched === 'SAFE TO SAIL' || rawMatched === 'SAFE TO SAIL (ALL CLEAR)' || rawMatched === 'SAFE (ALL CLEAR)';

    if (isUnsafe) {
      status = 'critical';
      title = '🔴 CRITICAL HAZARD · DO NOT VENTURE';
    } else if (isCaution) {
      status = 'caution';
      title = '🟠 CAUTION · MARGINAL CONDITIONS';
    } else if (isSafe) {
      status = 'safe';
      title = '🟢 ALL CLEAR · SAFE TO SAIL';
    } else {
      // Fallback: handle slight variants but still avoid substring SAFE-in-UNSAFE by word boundary
      const hasUnsafeWord = /\bUNSAFE\b/.test(rawMatched) || /\bCRITICAL\b/.test(rawMatched);
      const hasCautionWord = /\bCAUTION\b/.test(rawMatched);
      const hasSafeWord = /\bSAFE\b/.test(rawMatched);
      if (hasUnsafeWord) {
        status = 'critical';
        title = '🔴 CRITICAL HAZARD · DO NOT VENTURE';
      } else if (hasCautionWord) {
        status = 'caution';
        title = '🟠 CAUTION · MARGINAL CONDITIONS';
      } else if (hasSafeWord) {
        status = 'safe';
        title = '🟢 ALL CLEAR · SAFE TO SAIL';
      }
    }

    const summary = match[2] ? match[2].trim() : 'Operational assessment from multi-agent ocean telemetry.';

    // Remove raw markdown blockquote callout if present at the start
    let cleanContent = rawContent.replace(/(?:>\s*\[!IMPORTANT\]\s*\n(?:>\s*[^\n]+\n*)+)/i, '').trim();

    return {
      status,
      title,
      summary,
      metrics: this.extractMetrics(rawContent),
      provenance: this.extractProvenance(rawContent),
      cleanContent,
    };
  }

  private statusToVerdict(normalized: string, rawContent: string): VerdictData | null {
    // Exact matching for structured status — authoritative
    const upper = normalized.trim().toUpperCase();
    let status: 'safe' | 'caution' | 'critical' | 'unsafe' | 'info' = 'info';
    let title = 'MISSION ADVISORY';
    if (upper === 'UNSAFE' || upper === 'CRITICAL') {
      status = 'critical';
      title = '🔴 CRITICAL HAZARD · DO NOT VENTURE';
    } else if (upper === 'CAUTION') {
      status = 'caution';
      title = '🟠 CAUTION · MARGINAL CONDITIONS';
    } else if (upper === 'SAFE' || upper === 'SAFE TO SAIL' || upper === 'SAFE TO SAIL (ALL CLEAR)' || upper === 'SAFE_TO_SAIL') {
      status = 'safe';
      title = '🟢 ALL CLEAR · SAFE TO SAIL';
    } else if (upper === 'INFO') {
      status = 'info';
      title = 'ℹ️ MISSION ADVISORY';
    } else {
      return null;
    }
    // For structured verdict, summary comes from first line of content or generic
    const verdictLine = rawContent.match(/(?:VERDICT|Overall\s*Status):\s*[^\n]+/i);
    const summary = verdictLine ? verdictLine[0].replace(/.*?:\s*/,'').replace(/\*{1,2}/g,'').trim().slice(0,160) : (
      status === 'safe' ? 'Conditions within safe thresholds.' :
      status === 'caution' ? 'Borderline conditions — proceed with caution.' :
      status === 'critical' ? 'Hazardous conditions — do not venture out.' :
      'Operational assessment.'
    );
    let cleanContent = rawContent.replace(/(?:>\s*\[!IMPORTANT\]\s*\n(?:>\s*[^\n]+\n*)+)/i, '').trim() || rawContent;
    return {
      status,
      title,
      summary: summary || 'Operational assessment from multi-agent ocean telemetry.',
      metrics: this.extractMetrics(rawContent),
      provenance: this.extractProvenance(rawContent),
      cleanContent,
    };
  }

  private extractMetrics(text: string): { label: string; value: string }[] {
    const metrics: { label: string; value: string }[] = [];

    // Wave Height
    const waveMatch = text.match(/(?:wave\s*height|waves?)[:\s]+(\d+(?:\.\d+)?\s*m(?:eters?)?)/i);
    if (waveMatch) {
      metrics.push({ label: 'Sig Wave Height', value: waveMatch[1] });
    }

    // Wind Speed / Gusts
    const windMatch = text.match(/(?:wind\s*(?:speed|gusts?)?|gusts?)[:\s]+(\d+(?:\.\d+)?\s*(?:kts|knots|km\/h|m\/s))/i);
    if (windMatch) {
      metrics.push({ label: 'Wind / Gusts', value: windMatch[1] });
    }

    // Swell Period
    const swellMatch = text.match(/(?:swell\s*period|swell)[:\s]+(\d+(?:\.\d+)?\s*s(?:ec)?)/i);
    if (swellMatch) {
      metrics.push({ label: 'Swell Period', value: swellMatch[1] });
    }

    // Sea Surface Temp (SST)
    const sstMatch = text.match(/(?:SST|sea\s*temp(?:erature)?)[:\s]+(\d+(?:\.\d+)?\s*°C)/i);
    if (sstMatch) {
      metrics.push({ label: 'Sea Temp (SST)', value: sstMatch[1] });
    }

    return metrics;
  }

  private extractProvenance(text: string): string[] {
    const sources: string[] = [];
    if (/open-meteo/i.test(text)) sources.push('LIVE OPEN-METEO');
    if (/incois/i.test(text)) sources.push('INCOIS SATELLITE');
    if (/imd/i.test(text)) sources.push('IMD WARNING FEED');
    if (/uhslc|harmonic|tide/i.test(text)) sources.push('UHSLC HARMONIC');
    if (sources.length === 0) sources.push('ORCA TELEMETRY');
    return sources;
  }

  private renderAssistantMessage(isStreaming: boolean): void {
    const agent = store.agents.find(a => a.id === this.message.agentId) || store.getActiveAgent();
    const formattedTime = formatTime(this.message.timestamp);
    const modelPill = this.message.modelUsed || agent.defaultModel;

    // Pure Minimalist Animation while awaiting response (no card/panel box) — friend's UI improvement, preserved
    if ((!this.message.content || !this.message.content.trim()) && isStreaming) {
      this.element.innerHTML = `
        <div class="message-avatar orca-brand-avatar">
          <img src="/favicon.svg" alt="ORCA" class="message-avatar-favicon" />
        </div>

        <div class="orca-pure-loader animate-fade-in">
          <dotlottie-player
            src="/loading.lottie"
            background="transparent"
            speed="1"
            style="width: 38px; height: 38px;"
            loop
            autoplay>
          </dotlottie-player>
          <div class="orca-sonar-spinner" aria-hidden="true"></div>
        </div>
      `;
      return;
    }

    const verdictData = this.parseVerdict(this.message.content);
    const displayContent = verdictData ? verdictData.cleanContent : this.message.content;
    const renderedHtml = renderMarkdown(displayContent);

    this.element.innerHTML = `
      <div class="message-avatar orca-brand-avatar">
        <img src="/favicon.svg" alt="ORCA" class="message-avatar-favicon" />
      </div>

      <div class="message-workspace-ai">
        <div class="message-meta-header">
          <div class="message-sender-name">
            <span>${agent.name}</span>
            <span class="message-model-pill">${modelPill}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            ${this.message.tokens ? `
              <span title="Prompt: ${this.message.tokens.promptTokens} | Completion: ${this.message.tokens.completionTokens}" style="font-size:11px;font-family:var(--font-mono);color:var(--text-tertiary);">
                ${this.message.tokens.totalTokens} tokens
              </span>
            ` : ''}
            <span>${formattedTime}</span>
          </div>
        </div>

        ${verdictData ? `
          <div class="verdict-hud-card ${verdictData.status}">
            <div class="verdict-hud-top">
              <div class="verdict-badge-row">
                <span class="verdict-pulse-dot"></span>
                <span class="verdict-status-title">${verdictData.title}</span>
              </div>
              <div class="verdict-provenance-row">
                ${verdictData.provenance.map(p => `
                  <span class="provenance-chip">${ICONS.database || '●'} ${p}</span>
                `).join('')}
              </div>
            </div>

            <div style="font-size:13px;color:var(--text-secondary);font-weight:500;">
              ${verdictData.summary}
            </div>

            ${verdictData.metrics.length > 0 ? `
              <div class="verdict-metrics-grid">
                ${verdictData.metrics.map(m => `
                  <div class="verdict-metric-item">
                    <span class="metric-label">${m.label}</span>
                    <span class="metric-val">${m.value}</span>
                  </div>
                `).join('')}
              </div>
            ` : ''}
          </div>
        ` : ''}

        <div class="ai-msg-body">
          ${renderedHtml}
          ${isStreaming ? `<span class="streaming-cursor"></span>` : ''}
        </div>

        ${!isStreaming && this.message.content.length > 0 ? `
          <div class="message-actions-toolbar">
            <button class="msg-action-btn btn-speak-msg" title="Listen to spoken advisory audio">
              <span class="speak-icon">🔊</span>
              <span class="speak-label">Listen</span>
            </button>
            <button class="msg-action-btn btn-copy-msg" title="Copy response">
              ${ICONS.copy}
              <span>Copy</span>
            </button>
            <button class="msg-action-btn btn-regen-msg" title="Regenerate response">
              ${ICONS.refresh}
              <span>Regenerate</span>
            </button>
            <button class="msg-action-btn btn-like-msg ${this.message.reactions?.type === 'like' ? 'active' : ''}" title="Good response">
              ${ICONS.thumbsUp}
            </button>
            <button class="msg-action-btn btn-dislike-msg ${this.message.reactions?.type === 'dislike' ? 'active' : ''}" title="Bad response">
              ${ICONS.thumbsDown}
            </button>
          </div>
        ` : ''}
      </div>
    `;
  }

  private attachEvents(): void {
    // Copy code snippet buttons
    const codeCopyButtons = this.element.querySelectorAll('.code-copy-btn');
    codeCopyButtons.forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const code = decodeURIComponent(btn.getAttribute('data-code') || '');
        if (code) {
          await copyToClipboard(code);
          const label = btn.querySelector('.copy-label');
          if (label) label.textContent = 'Copied!';
          setTimeout(() => {
            if (label) label.textContent = 'Copy';
          }, 2000);
          showToast('Code copied to clipboard', 'success');
        }
      });
    });

    // Speak / Listen audio button (Fishermen & Divers Audio HUD)
    const speakBtn = this.element.querySelector('.btn-speak-msg');
    speakBtn?.addEventListener('click', () => {
      if ('speechSynthesis' in window) {
        if (window.speechSynthesis.speaking) {
          window.speechSynthesis.cancel();
          const icon = speakBtn.querySelector('.speak-icon');
          const label = speakBtn.querySelector('.speak-label');
          if (icon) icon.textContent = '🔊';
          if (label) label.textContent = 'Listen';
          return;
        }

        const cleanText = this.message.content
          .replace(/[#*_`~>-]/g, '')
          .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
          .replace(/http\S+/g, '');

        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.rate = 0.95; // Clear maritime pace
        utterance.pitch = 1.0;

        const icon = speakBtn.querySelector('.speak-icon');
        const label = speakBtn.querySelector('.speak-label');
        if (icon) icon.textContent = '⏹️';
        if (label) label.textContent = 'Stop';

        utterance.onend = () => {
          if (icon) icon.textContent = '🔊';
          if (label) label.textContent = 'Listen';
        };

        utterance.onerror = () => {
          if (icon) icon.textContent = '🔊';
          if (label) label.textContent = 'Listen';
        };

        window.speechSynthesis.speak(utterance);
        showToast('Speaking advisory aloud...', 'info');
      } else {
        showToast('Speech audio is not supported in this browser.', 'error');
      }
    });

    // Copy full response button
    const copyMsgBtn = this.element.querySelector('.btn-copy-msg');
    copyMsgBtn?.addEventListener('click', async () => {
      await copyToClipboard(this.message.content);
      showToast('Full response copied to clipboard', 'success');
    });

    // Regenerate button
    const regenBtn = this.element.querySelector('.btn-regen-msg');
    regenBtn?.addEventListener('click', () => {
      store.regenerateResponse(this.message.id);
      showToast('Regenerating response...', 'info');
    });

    // Likes & Dislikes
    const likeBtn = this.element.querySelector('.btn-like-msg');
    likeBtn?.addEventListener('click', () => {
      store.setMessageReaction(this.message.id, 'like');
      showToast('Thanks for your feedback!', 'success');
    });

    const dislikeBtn = this.element.querySelector('.btn-dislike-msg');
    dislikeBtn?.addEventListener('click', () => {
      store.setMessageReaction(this.message.id, 'dislike');
      showToast('Feedback noted to improve future responses.', 'info');
    });

    // Edit user message
    const editBtn = this.element.querySelector('.btn-edit-msg');
    editBtn?.addEventListener('click', () => {
      const newPrompt = prompt('Edit your message:', this.message.content);
      if (newPrompt && newPrompt.trim() && newPrompt !== this.message.content) {
        store.editMessage(this.message.id, newPrompt.trim());
      }
    });

    // Toggle activity steps accordion
    const activityToggle = this.element.querySelector('.btn-toggle-activity');
    activityToggle?.addEventListener('click', () => {
      const stepList = this.element.querySelector('.activity-step-list') as HTMLElement;
      if (stepList) {
        const isHidden = stepList.style.display === 'none';
        stepList.style.display = isHidden ? 'flex' : 'none';
      }
    });
  }
}

// Exported helpers for unit testing — exact matching logic, no substring SAFE-in-UNSAFE bug.
export function parseVerdictForTest(rawContent: string, structuredStatus?: string): VerdictData | null {
  const dummy = new MessageItem({
    id: 'test',
    chatId: 'test',
    role: 'assistant',
    content: rawContent,
    timestamp: Date.now(),
    status: structuredStatus as any,
  } as any);
  // Use the instance's parseVerdict via private access (type-cast)
  return (dummy as any).parseVerdict(rawContent) as VerdictData | null;
}

export function verdictStatusFromStructured(status: string): 'safe' | 'caution' | 'critical' | 'info' {
  const u = status.trim().toUpperCase();
  if (u === 'UNSAFE' || u === 'CRITICAL') return 'critical';
  if (u === 'CAUTION') return 'caution';
  if (u === 'SAFE' || u === 'SAFE TO SAIL' || u === 'SAFE TO SAIL (ALL CLEAR)') return 'safe';
  return 'info';
}
