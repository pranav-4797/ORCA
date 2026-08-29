import { OceanMap } from './OceanMap';
import { SafetyFactorHUD } from './SafetyFactorHUD';
import { store } from '../../store/appState';

export class OperationalPicture {
  private element: HTMLElement;
  private oceanMap: OceanMap;
  private safetyHUD: SafetyFactorHUD;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'operational-picture-console';
    
    this.oceanMap = new OceanMap();
    this.safetyHUD = new SafetyFactorHUD();

    this.render();
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

    // Bottom Telemetry & Safety HUD Section
    const hudSection = document.createElement('div');
    hudSection.className = 'console-hud-section';
    hudSection.appendChild(this.safetyHUD.getElement());

    this.element.appendChild(mapSection);
    this.element.appendChild(hudSection);
  }
}
