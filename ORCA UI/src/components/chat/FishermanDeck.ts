import { store } from '../../store/appState';
import { ICONS } from '../../utils/icons';

export interface QuickPreset {
  id: string;
  icon: string;
  badge: string;
  title: string;
  prompt: string;
  color: string;
}

export const FISHERMAN_PRESETS: QuickPreset[] = [
  {
    id: 'pfz',
    icon: '🐟',
    badge: 'PFZ HOTSPOT',
    title: 'Fish Zones & Chlorophyll',
    prompt: 'Where is the nearest Potential Fishing Zone (PFZ) with high chlorophyll and thermal front today?',
    color: '#22c55e'
  },
  {
    id: 'waves',
    icon: '🌊',
    badge: '24H SWELL',
    title: 'Wave & Swell Forecast',
    prompt: 'What is the significant wave height, sea swell period, and wind speed forecast for next 24 hours?',
    color: '#0ea5e9'
  },
  {
    id: 'cyclone',
    icon: '⚠️',
    badge: 'LIVE ALERTS',
    title: 'Cyclone & Wind Warnings',
    prompt: 'Are there any active cyclone, depression, or rough sea warning bulletins in this sector?',
    color: '#f59e0b'
  },
  {
    id: 'diving',
    icon: '🤿',
    badge: 'BATHYMETRY',
    title: 'Diving & Depth (UKC)',
    prompt: 'What is the underwater depth, tidal clearance (UKC), and diving visibility near these waters?',
    color: '#10b981'
  }
];

export class FishermanDeck {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'fisherman-action-deck';
    this.render();
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    this.element.innerHTML = `
      <div class="fisherman-deck-scroll">
        ${FISHERMAN_PRESETS.map(p => `
          <button class="fisherman-quick-chip" data-prompt="${p.prompt}" title="${p.prompt}">
            <span class="chip-icon">${p.icon}</span>
            <div class="chip-text-col">
              <span class="chip-badge" style="color:${p.color};">${p.badge}</span>
              <span class="chip-title">${p.title}</span>
            </div>
          </button>
        `).join('')}
      </div>
    `;

    this.attachEvents();
  }

  private attachEvents(): void {
    const buttons = this.element.querySelectorAll('.fisherman-quick-chip');
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        const prompt = btn.getAttribute('data-prompt');
        if (prompt) {
          store.sendMessage(prompt);
        }
      });
    });
  }
}
