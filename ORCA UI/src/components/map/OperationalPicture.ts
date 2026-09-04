import { OceanMap } from './OceanMap';
import { SafetyFactorHUD } from './SafetyFactorHUD';
import { store } from '../../store/appState';
import { QuickActionsDock } from '../dashboard/QuickActionsDock';

export class OperationalPicture {
  private element: HTMLElement;
  private oceanMap: OceanMap;
  private safetyHUD: SafetyFactorHUD;
  private quickActions: QuickActionsDock;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'operational-picture-console';

    this.oceanMap = new OceanMap();
    this.safetyHUD = new SafetyFactorHUD();
    // Quick Actions dock -- location-first, four-button instant command panel.
    this.quickActions = new QuickActionsDock(this.oceanMap);

    this.render();
    // Hydrate the dock with a fresh snapshot so the first PFZ tap is instant.
    void store.refreshDashboard({ force: false });
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    this.element.innerHTML = '';

    // Top Map Section
    const mapSection = document.createElement('div');
    mapSection.className = 'console-map-section';
    mapSection.appendChild(this.oceanMap.getElement());

    // Bottom Quick Actions dock -- replaces the briefing/readiness/cards
    // with a location-first four-button instant-command panel.
    const dockSection = document.createElement('div');
    dockSection.className = 'console-dock-section';
    dockSection.appendChild(this.quickActions.getElement());

    this.element.appendChild(mapSection);
    this.element.appendChild(dockSection);
  }
}
