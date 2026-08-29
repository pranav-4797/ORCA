import { store } from '../../store/appState';
import { Attachment } from '../../types/message';
import { ICONS } from '../../utils/icons';
import { showToast } from '../ui/Toast';
import { generateId, formatFileSize } from '../../utils/helpers';
import { OrcaApiService } from '../../services/orcaApiService';

export class Composer {
  private element: HTMLElement;
  private textarea!: HTMLTextAreaElement;
  private attachments: Attachment[] = [];
  private isRecordingVoice: boolean = false;
  private modeMenuOpen: boolean = false;
  private mediaRecorder: MediaRecorder | null = null;
  private recordChunks: Blob[] = [];
  private recordStream: MediaStream | null = null;
  private speechRecognition: any = null;
  private preRecordText: string = '';
  private liveFinalTranscript: string = '';

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'composer-outer-container';
    this.render();
    store.subscribe(() => this.updateState());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  public focus(): void {
    if (this.textarea) {
      this.textarea.focus();
    }
  }

  public setText(text: string): void {
    if (this.textarea) {
      this.textarea.value = text;
      this.autoResize();
      this.textarea.focus();
    }
  }

  private render(): void {
    const activeAgent = store.getActiveAgent();
    const activeModel = store.activeModel;
    const isStreaming = store.isStreaming;

    this.element.innerHTML = `
      <div class="composer-box" id="composer-dropzone">
        <input type="file" id="file-input" style="display:none;" multiple accept="image/*,.pdf,.txt,.ts,.js,.json,.csv,.md">

        <!-- Attachments Preview Area -->
        <div class="composer-attachments-preview" id="attachments-container" style="${this.attachments.length > 0 ? 'display:flex;' : 'display:none;'}">
          ${this.attachments.map(att => `
            <div class="attachment-chip" data-att-id="${att.id}">
              <span>${ICONS.paperclip}</span>
              <span>${att.name}</span>
              <span style="opacity:0.6;font-size:10px;">(${formatFileSize(att.size)})</span>
              <button class="btn-remove" data-remove-id="${att.id}" title="Remove file">${ICONS.x}</button>
            </div>
          `).join('')}
        </div>

        <!-- Input Textarea Row -->
        <div class="composer-input-row">
          <textarea
            class="composer-textarea"
            id="composer-textarea"
            placeholder="Ask anything, type @ for agents, or drag & drop files..."
            rows="1"
            aria-label="Message prompt input"
          ></textarea>

          ${this.isRecordingVoice ? `
            <div class="voice-recording-overlay">
              <span class="voice-recording-pulse-dot"></span>
              <div class="voice-waveform-visualizer" aria-hidden="true">
                <span class="voice-wave-bar bar-1"></span>
                <span class="voice-wave-bar bar-2"></span>
                <span class="voice-wave-bar bar-3"></span>
                <span class="voice-wave-bar bar-4"></span>
                <span class="voice-wave-bar bar-5"></span>
                <span class="voice-wave-bar bar-6"></span>
                <span class="voice-wave-bar bar-7"></span>
                <span class="voice-wave-bar bar-8"></span>
              </div>
              <span class="voice-recording-label">Live Voice Input — speak maritime query…</span>
              <button class="voice-stop-inline-btn" id="btn-voice-stop-inline" title="Finish voice recording">Done ✓</button>
            </div>
          ` : ''}
        </div>

        <!-- Bottom Toolbar Controls -->
        <div class="composer-toolbar">
          <div class="composer-toolbar-left">
            <button class="icon-btn" id="btn-attach-files" title="Attach Files or Images" aria-label="Attach Files">
              ${ICONS.paperclip}
            </button>

            <!-- Query Routing Pill: auto / panel / direct -->
            <button class="pill-selector ${store.queryMode === 'auto' ? 'mode-auto' : store.queryMode === 'agent' ? 'mode-direct' : 'mode-panel'}"
                    id="btn-pill-mode" title="Choose who answers: AUTO (ORCA picks) / Panel (full deliberation) / Direct specialist">
              <span>${store.queryMode === 'auto' ? '✨' : store.queryMode === 'agent' ? ICONS.user : ICONS.messageSquare}</span>
              <span class="pill-label">${this.modeLabel()}</span>
              <span>${ICONS.chevronDown}</span>
            </button>

            <!-- Agent persona pill -->
            <button class="pill-selector" id="btn-pill-agent" title="Select chat persona" style="color:${activeAgent.avatarColor};">
              <span>${ICONS[activeAgent.icon] || ICONS.bot}</span>
              <span class="pill-label">${activeAgent.shortName || activeAgent.name}</span>
              <span>${ICONS.chevronDown}</span>
            </button>

            <div id="mode-menu-anchor" style="position:relative;display:flex;"></div>
          </div>

          <div class="composer-toolbar-right">
            <!-- Voice Dictate Button -->
            <button class="icon-btn ${this.isRecordingVoice ? 'active' : ''}" id="btn-voice-dictate" title="${this.isRecordingVoice ? 'Stop Recording' : 'Voice Input'}" aria-label="Voice Input">
              ${ICONS.mic}
            </button>

            <!-- Send / Stop Generation Button -->
            ${isStreaming ? `
              <button class="btn-stop-message" id="btn-stop-gen" title="Stop Generation" aria-label="Stop Generation">
                ${ICONS.stop}
              </button>
            ` : `
              <button class="btn-send-message" id="btn-send-msg" title="Send Message (Enter)" aria-label="Send Message">
                ${ICONS.arrowUp}
              </button>
            `}
          </div>
        </div>
      </div>
    `;

    this.textarea = this.element.querySelector('#composer-textarea') as HTMLTextAreaElement;
    this.attachEvents();
  }

  private modeLabel(): string {
    if (store.queryMode === 'auto') {
      const autoLabel = store.getAutoRoutingLabel();
      return autoLabel ? autoLabel : 'Auto · ORCA picks';
    }
    if (store.queryMode === 'agent') {
      const spec = store.backendAgents.find(a => a.key === store.directAgentKey);
      return spec ? `${spec.name.replace(' Agent', '')} · direct` : 'Direct agent';
    }
    return 'Panel · all discuss';
  }

  private updateState(): void {
    const isStreaming = store.isStreaming;
    const sendBtnContainer = this.element.querySelector('.composer-toolbar-right');

    // Query-routing pill label + tint (auto/panel/direct)
    const modePill = this.element.querySelector('#btn-pill-mode');
    if (modePill) {
      const label = modePill.querySelector('.pill-label');
      if (label && label.textContent !== this.modeLabel()) label.textContent = this.modeLabel();
      modePill.classList.toggle('mode-auto', store.queryMode === 'auto');
      modePill.classList.toggle('mode-panel', store.queryMode === 'panel');
      modePill.classList.toggle('mode-direct', store.queryMode === 'agent');
      const iconSpan = modePill.querySelector('span');
      if (iconSpan) {
        iconSpan.innerHTML = store.queryMode === 'auto' ? '✨' : (store.queryMode === 'agent' ? ICONS.user : ICONS.messageSquare);
      }
    }

    const agentPill = this.element.querySelector('#btn-pill-agent .pill-label');
    const activeAgent = store.getActiveAgent();
    if (agentPill) {
      agentPill.textContent = activeAgent.shortName || activeAgent.name;
    }

    // Re-render the mode dropdown only while it is open
    if (this.modeMenuOpen) {
      this.renderModeMenu();
    }

    // Update stop / send button
    if (sendBtnContainer) {
      const existingStop = this.element.querySelector('#btn-stop-gen');
      const existingSend = this.element.querySelector('#btn-send-msg');

      if (isStreaming && !existingStop) {
        if (existingSend) existingSend.remove();
        const stopBtn = document.createElement('button');
        stopBtn.className = 'btn-stop-message';
        stopBtn.id = 'btn-stop-gen';
        stopBtn.title = 'Stop Generation';
        stopBtn.innerHTML = ICONS.stop;
        stopBtn.addEventListener('click', () => {
          store.stopGeneration();
          showToast('Generation stopped', 'info');
        });
        sendBtnContainer.appendChild(stopBtn);
      } else if (!isStreaming && !existingSend) {
        if (existingStop) existingStop.remove();
        const sendBtn = document.createElement('button');
        sendBtn.className = 'btn-send-message';
        sendBtn.id = 'btn-send-msg';
        sendBtn.title = 'Send Message (Enter)';
        sendBtn.innerHTML = ICONS.arrowUp;
        sendBtn.addEventListener('click', () => this.handleSend());
        sendBtnContainer.appendChild(sendBtn);
      }
    }
  }

  private attachEvents(): void {
    // Auto-resize textarea
    this.textarea.addEventListener('input', () => {
      this.autoResize();
    });

    // Enter to send, Shift+Enter for new line
    this.textarea.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.handleSend();
      }
    });

    // Send button click
    const sendBtn = this.element.querySelector('#btn-send-msg');
    sendBtn?.addEventListener('click', () => {
      this.handleSend();
    });

    // Stop button click
    const stopBtn = this.element.querySelector('#btn-stop-gen');
    stopBtn?.addEventListener('click', () => {
      store.stopGeneration();
      showToast('Generation stopped', 'info');
    });

    // Attach File Click & Input
    const attachBtn = this.element.querySelector('#btn-attach-files');
    const fileInput = this.element.querySelector('#file-input') as HTMLInputElement;

    attachBtn?.addEventListener('click', () => {
      fileInput?.click();
    });

    fileInput?.addEventListener('change', (e: Event) => {
      const target = e.target as HTMLInputElement;
      if (target.files) {
        Array.from(target.files).forEach(file => {
          this.attachments.push({
            id: generateId('att'),
            name: file.name,
            size: file.size,
            type: file.type
          });
        });
        this.renderAttachments();
        showToast(`Attached ${target.files.length} file(s)`, 'success');
      }
    });

    // Drag & Drop
    const dropzone = this.element.querySelector('#composer-dropzone') as HTMLElement;
    dropzone?.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.style.borderColor = 'var(--accent-primary)';
      dropzone.style.backgroundColor = 'var(--bg-surface-hover)';
    });

    dropzone?.addEventListener('dragleave', () => {
      dropzone.style.borderColor = '';
      dropzone.style.backgroundColor = '';
    });

    dropzone?.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.style.borderColor = '';
      dropzone.style.backgroundColor = '';
      if (e.dataTransfer?.files) {
        Array.from(e.dataTransfer.files).forEach(file => {
          this.attachments.push({
            id: generateId('att'),
            name: file.name,
            size: file.size,
            type: file.type
          });
        });
        this.renderAttachments();
        showToast(`Added ${e.dataTransfer.files.length} dropped file(s)`, 'success');
      }
    });

    // Voice dictation: real mic capture -> Whisper STT -> same pipeline
    const voiceBtn = this.element.querySelector('#btn-voice-dictate');
    voiceBtn?.addEventListener('click', () => {
      if (this.isRecordingVoice) {
        this.stopRecording();
      } else {
        void this.startRecording();
      }
    });

    const inlineStopBtn = this.element.querySelector('#btn-voice-stop-inline');
    inlineStopBtn?.addEventListener('click', () => {
      this.stopRecording();
    });

    // Query-routing pill: open the panel-vs-direct dropdown
    const modePill = this.element.querySelector('#btn-pill-mode');
    modePill?.addEventListener('click', (e) => {
      e.stopPropagation();
      this.modeMenuOpen = !this.modeMenuOpen;
      if (this.modeMenuOpen) {
        this.renderModeMenu();
      } else {
        this.removeModeMenu();
      }
    });

    // Close the dropdown when clicking anywhere else
    this.outsideClickHandler = (e) => {
      if (!this.modeMenuOpen) return;
      const target = e.target as Node;
      const anchor = this.element.querySelector('#mode-menu-anchor');
      const pill = this.element.querySelector('#btn-pill-mode');
      if (anchor?.contains(target) || pill?.contains(target)) return;
      this.modeMenuOpen = false;
      this.removeModeMenu();
    };
    document.addEventListener('click', this.outsideClickHandler);

    // Agent persona pill click
    const agentPill = this.element.querySelector('#btn-pill-agent');
    agentPill?.addEventListener('click', () => {
      const isMobile = window.innerWidth < 1280;
      if (isMobile) {
        store.toggleMobileAgentDrawer(true);
      } else {
        store.toggleAgentPanel(true);
      }
    });
  }

  private outsideClickHandler: ((e: MouseEvent) => void) | null = null;

  /** Build (or rebuild) the auto/panel-vs-direct dropdown inside the anchor. */
  private renderModeMenu(): void {
    const anchor = this.element.querySelector('#mode-menu-anchor') as HTMLElement | null;
    if (!anchor) return;

    const isAuto = store.queryMode === 'auto';
    const isPanel = store.queryMode === 'panel';
    anchor.innerHTML = `
      <div class="composer-mode-menu" role="menu">
        <div class="mode-menu-title">How should ORCA answer?</div>

        <button class="mode-option ${isAuto ? 'selected' : ''}" data-mode="auto" role="menuitem" style="${isAuto ? 'border-color:var(--primary);background:rgba(14,124,134,0.06);' : ''}">
          <span class="mode-option-icon">✨</span>
          <span class="mode-option-body">
            <span class="mode-option-name">✨ AUTO SELECT — ORCA picks best specialist(s)</span>
            <span class="mode-option-desc">Fast intelligent routing — only needed agents run, no round-table unless complex. Recommended for normal chat.</span>
          </span>
          ${isAuto ? `<span class="mode-option-check">${ICONS.check}</span>` : ''}
        </button>

        <button class="mode-option ${isPanel ? 'selected' : ''}" data-mode="panel" role="menuitem">
          <span class="mode-option-icon">${ICONS.messageSquare}</span>
          <span class="mode-option-body">
            <span class="mode-option-name">ORCA Panel — full discussion</span>
            <span class="mode-option-desc">Every relevant specialist runs, debates the findings together, then reconciles one verdict (demo/deep analysis)</span>
          </span>
          ${isPanel ? `<span class="mode-option-check">${ICONS.check}</span>` : ''}
        </button>

        <div class="mode-divider"></div>
        <div class="mode-menu-title">Ask one specialist directly</div>

        ${store.backendAgents.map(spec => {
          const selected = store.queryMode === 'agent' && store.directAgentKey === spec.key;
          return `
            <button class="mode-option mode-option-agent ${selected ? 'selected' : ''}"
                    data-mode="agent" data-agent-key="${spec.key}" role="menuitem"
                    title="${spec.description}">
              <span class="mode-option-icon">${ICONS.user}</span>
              <span class="mode-option-body">
                <span class="mode-option-name">${spec.name}</span>
                <span class="mode-option-desc">${spec.description}</span>
              </span>
              ${selected ? `<span class="mode-option-check">${ICONS.check}</span>` : ''}
            </button>
          `;
        }).join('')}
      </div>
    `;

    anchor.querySelectorAll('.mode-option').forEach(opt => {
      opt.addEventListener('click', (e) => {
        e.stopPropagation();
        const mode = opt.getAttribute('data-mode') as 'auto' | 'panel' | 'agent';
        const agentKey = opt.getAttribute('data-agent-key');
        store.setQueryMode(mode);
        if (mode === 'agent' && agentKey) {
          store.setDirectAgent(agentKey);
          const spec = store.backendAgents.find(a => a.key === agentKey);
          showToast(`Direct mode: only ${spec?.name || agentKey} will answer`, 'info');
        } else if (mode === 'panel') {
          showToast('Panel mode: agents will discuss before answering', 'success');
        } else if (mode === 'auto') {
          showToast('AUTO SELECT — ORCA will pick the best specialist(s)', 'success');
        }
        this.modeMenuOpen = false;
        this.removeModeMenu();
      });
    });
  }

  private removeModeMenu(): void {
    this.element.querySelector('#mode-menu-anchor')?.replaceChildren();
  }

  private autoResize(): void {
    if (!this.textarea) return;
    this.textarea.style.height = 'auto';
    this.textarea.style.height = Math.min(this.textarea.scrollHeight, 200) + 'px';
  }

  private async startRecording(): Promise<void> {
    if (store.isStreaming) return;
    const SpeechRecognitionCtor: any =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const hasLiveSTT = !!SpeechRecognitionCtor;
    const hasMediaRecorder = !!((navigator.mediaDevices as any)?.getUserMedia && typeof (window as any).MediaRecorder !== 'undefined');
    if (!hasLiveSTT && !hasMediaRecorder) {
      showToast('Voice input is not supported in this browser', 'error');
      return;
    }
    try {
      OrcaApiService.stopSpeaking();
      this.preRecordText = this.textarea?.value || '';
      this.liveFinalTranscript = '';

      // Live interim transcription — Google-style: text appears as you speak
      if (hasLiveSTT) {
        this.speechRecognition = new SpeechRecognitionCtor();
        this.speechRecognition.lang = 'en-IN';
        this.speechRecognition.interimResults = true;
        this.speechRecognition.continuous = true;
        this.speechRecognition.maxAlternatives = 1;
        this.speechRecognition.onresult = (event: any) => {
          let interim = '';
          let finalChunk = '';
          for (let i = event.resultIndex; i < event.results.length; i++) {
            const transcript: string = event.results[i][0].transcript;
            if (event.results[i].isFinal) finalChunk += transcript + ' ';
            else interim += transcript + ' ';
          }
          if (finalChunk) this.liveFinalTranscript += finalChunk;
          const display = (this.preRecordText ? this.preRecordText + ' ' : '') +
            this.liveFinalTranscript + interim;
          this.textarea.value = display;
          this.textarea.focus();
          this.autoResize();
          // move caret to end
          this.textarea.selectionStart = this.textarea.selectionEnd = this.textarea.value.length;
        };
        this.speechRecognition.onerror = (e: any) => {
          if (e.error === 'not-allowed') showToast('Microphone permission denied', 'error');
        };
        this.speechRecognition.onend = () => {
          // if still recording, restart (continuous workaround for some browsers)
          if (this.isRecordingVoice && this.speechRecognition) {
            try { this.speechRecognition.start(); } catch {}
          }
        };
        this.speechRecognition.start();
      }

      // Keep MediaRecorder for Whisper backup (multilingual) — not required if live STT gave a final transcript
      if (hasMediaRecorder) {
        this.recordStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '';
        this.mediaRecorder = new MediaRecorder(
          this.recordStream,
          mime ? { mimeType: mime } : undefined,
        );
        this.recordChunks = [];
        this.mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) this.recordChunks.push(e.data);
        };
        this.mediaRecorder.onstop = () => {
          const capturedText = (this.textarea?.value || '').trim();
          const hasLiveText = this.liveFinalTranscript.trim().length > 0 || capturedText.length > this.preRecordText.trim().length;
          const blob = new Blob(this.recordChunks, { type: mime || 'audio/webm' });
          this.releaseMic(true);
          // Preserve the live transcript across the re-render (render() replaces the textarea element)
          const preserved = capturedText;
          this.isRecordingVoice = false;
          this.render();
          this.textarea = this.element.querySelector('#composer-textarea') as HTMLTextAreaElement;
          if (preserved) {
            this.textarea.value = preserved;
            this.textarea.selectionStart = this.textarea.selectionEnd = preserved.length;
            this.autoResize();
            this.textarea.focus();
          }
          if (hasLiveText && preserved.length > 0) {
            showToast('Captured — review and press Send', 'success');
            return;
          }
          if (blob.size < 1200) {
            showToast('Recording too short — hold the mic while speaking', 'error');
            return;
          }
          showToast('Voice captured — sending to Whisper STT...', 'info');
          void store.sendMessage('', [], { blob });
        };
        this.mediaRecorder.start();
      }

      this.isRecordingVoice = true;
      this.render();
      // re-bind textarea ref lost on re-render, keep focus & value
      this.textarea = this.element.querySelector('#composer-textarea') as HTMLTextAreaElement;
      this.textarea.value = this.preRecordText + (this.preRecordText ? ' ' : '');
      this.textarea.focus();
      this.autoResize();
      showToast(hasLiveSTT ? 'Listening — text appears live as you speak' : 'Listening... tap mic again to send', 'info');
    } catch {
      this.releaseMic(true);
      this.isRecordingVoice = false;
      this.render();
      showToast('Microphone permission denied', 'error');
    }
  }

  private stopRecording(): void {
    const preserved = (this.textarea?.value || '').trim();
    if (this.speechRecognition) {
      try { this.speechRecognition.stop(); } catch {}
    }
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
      // onstop handler will restore preserved text and re-render
      return;
    }
    this.releaseMic(true);
    this.isRecordingVoice = false;
    this.render();
    this.textarea = this.element.querySelector('#composer-textarea') as HTMLTextAreaElement;
    if (preserved) {
      this.textarea.value = preserved;
      this.textarea.selectionStart = this.textarea.selectionEnd = preserved.length;
      this.autoResize();
      this.textarea.focus();
    }
  }

  private releaseMic(keepMicToast = false): void {
    if (this.speechRecognition) {
      try { this.speechRecognition.onend = null; this.speechRecognition.stop(); } catch {}
    }
    this.speechRecognition = null;
    this.recordStream?.getTracks().forEach((t) => t.stop());
    this.recordStream = null;
    this.mediaRecorder = null;
    if (!keepMicToast) {
      this.liveFinalTranscript = '';
      this.preRecordText = '';
    }
  }

  private renderAttachments(): void {
    const container = this.element.querySelector('#attachments-container') as HTMLElement;
    if (!container) return;

    if (this.attachments.length === 0) {
      container.style.display = 'none';
      container.innerHTML = '';
      return;
    }

    container.style.display = 'flex';
    container.innerHTML = this.attachments.map(att => `
      <div class="attachment-chip" data-att-id="${att.id}">
        <span>${ICONS.paperclip}</span>
        <span>${att.name}</span>
        <span style="opacity:0.6;font-size:10px;">(${formatFileSize(att.size)})</span>
        <button class="btn-remove" data-remove-id="${att.id}" title="Remove file">${ICONS.x}</button>
      </div>
    `).join('');

    const removeBtns = container.querySelectorAll('.btn-remove');
    removeBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = btn.getAttribute('data-remove-id');
        this.attachments = this.attachments.filter(a => a.id !== id);
        this.renderAttachments();
      });
    });
  }

  private handleSend(): void {
    const text = this.textarea.value.trim();
    if (!text && this.attachments.length === 0) return;
    if (store.isStreaming) return;

    OrcaApiService.stopSpeaking();
    const attachmentsToSend = [...this.attachments];
    this.textarea.value = '';
    this.attachments = [];
    this.autoResize();
    this.renderAttachments();

    store.sendMessage(text, attachmentsToSend);
  }
}
