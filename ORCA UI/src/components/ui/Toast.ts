import { ICONS } from '../../utils/icons';

export class ToastManager {
  private static instance: ToastManager;
  private container: HTMLElement;

  private constructor() {
    let el = document.getElementById('toast-container');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast-container';
      document.body.appendChild(el);
    }
    this.container = el;
  }

  public static getInstance(): ToastManager {
    if (!ToastManager.instance) {
      ToastManager.instance = new ToastManager();
    }
    return ToastManager.instance;
  }

  public show(message: string, type: 'success' | 'error' | 'info' = 'info', durationMs = 3000): void {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    let iconHtml = ICONS.zap;
    if (type === 'success') iconHtml = ICONS.check;
    if (type === 'error') iconHtml = ICONS.x;

    toast.innerHTML = `
      <span class="toast-icon">${iconHtml}</span>
      <span class="toast-message">${message}</span>
    `;

    this.container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(8px)';
      toast.style.transition = 'opacity 200ms ease, transform 200ms ease';
      setTimeout(() => toast.remove(), 200);
    }, durationMs);
  }
}

export const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info', durationMs = 3000) => {
  ToastManager.getInstance().show(message, type, durationMs);
};
