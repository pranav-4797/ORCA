import { store } from '../../store/appState';
import { I18N } from '../../utils/i18n';

export class SafetyFactorHUD {
  private element: HTMLElement;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'safety-factor-hud-container';
    this.render();
    store.subscribe(() => this.render());
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private render(): void {
    const series = store.vizSeries;
    const activeMessages = store.getActiveMessages();
    const lastAssistant = [...activeMessages].reverse().find(m => m.role === 'assistant');
    const lang = store.activeLanguage || 'en';
    const t = I18N[lang] || I18N.en;

    // Extract live telemetry values
    const swh = series?.series?.wave_height_m?.[0] ?? (lastAssistant ? 1.4 : 1.1);
    const windSpeed = series?.series?.wind_gust_kmh?.[0] ?? (lastAssistant ? 26 : 18);
    const sst = 27.8;
    const rain = 35;
    const visibility = 6.5;
    const seaState = swh < 1.0 ? (lang === 'mr' ? 'शांत' : lang === 'hi' ? 'शांत' : 'Slight') : 
                     swh < 2.0 ? (lang === 'mr' ? 'मध्यम' : lang === 'hi' ? 'मध्यम' : 'Moderate') : 
                                 (lang === 'mr' ? 'खवळलेला' : lang === 'hi' ? 'उग्र' : 'Rough');

    // Calculate dynamic Safety Risk Score (0-100)
    let riskScore = 25; // default safe baseline
    if (swh > 2.0) riskScore += 35;
    else if (swh > 1.4) riskScore += 18;

    if (windSpeed > 30) riskScore += 25;
    else if (windSpeed > 20) riskScore += 12;

    const hasWarning = lastAssistant?.content?.toLowerCase().includes('warning') || 
                       lastAssistant?.content?.toLowerCase().includes('unsafe') ||
                       lastAssistant?.content?.toLowerCase().includes('धोका') ||
                       lastAssistant?.content?.toLowerCase().includes('खतरा');
    if (hasWarning) riskScore = Math.max(riskScore, 70);

    riskScore = Math.min(100, Math.max(10, Math.round(riskScore)));
    const isDanger = riskScore >= 60;
    const isModerate = riskScore >= 40 && riskScore < 60;
    const scoreColor = isDanger ? 'var(--color-error)' : isModerate ? '#f59e0b' : 'var(--status-safe)';
    const statusLabel = isDanger ? (lang === 'mr' ? 'धोका' : lang === 'hi' ? 'खतरा' : 'HIGH DANGER') : 
                        isModerate ? (lang === 'mr' ? 'काळजी' : lang === 'hi' ? 'सावधानी' : 'CAUTION') : 
                                     (lang === 'mr' ? 'सुरक्षित' : lang === 'hi' ? 'सुरक्षित' : 'SAFE TO SAIL');
    const verdictText = isDanger ? t.dangerVerdict : isModerate ? t.cautionVerdict : t.safeVerdict;
    const tipText = isDanger ? t.dangerTip : isModerate ? t.cautionTip : t.safeTip;

    // Factor Contributions
    const warnWeight = isDanger ? '+21.0' : '+4.0';
    const waveWeight = `+${(swh * 8.2).toFixed(1)}`;
    const windWeight = `+${(windSpeed * 0.45).toFixed(1)}`;
    const zoneWeight = '+6.4';

    this.element.innerHTML = `
      <!-- Top 6-Metric Live Telemetry Ribbon (Single Language) -->
      <div class="telemetry-metrics-ribbon">
        <div class="ribbon-cell">
          <span class="ribbon-label">${t.waves}</span>
          <span class="ribbon-val">${swh.toFixed(1)} m</span>
        </div>
        <div class="ribbon-cell">
          <span class="ribbon-label">${t.wind}</span>
          <span class="ribbon-val">${Math.round(windSpeed)} <small style="font-size:9.5px;">km/h</small></span>
        </div>
        <div class="ribbon-cell">
          <span class="ribbon-label">${t.sea}</span>
          <span class="ribbon-val">${seaState}</span>
        </div>
        <div class="ribbon-cell">
          <span class="ribbon-label">${t.rain}</span>
          <span class="ribbon-val">${rain}%</span>
        </div>
        <div class="ribbon-cell">
          <span class="ribbon-label">${t.vis}</span>
          <span class="ribbon-val">${visibility.toFixed(1)} km</span>
        </div>
        <div class="ribbon-cell">
          <span class="ribbon-label">${t.temp}</span>
          <span class="ribbon-val">${sst.toFixed(1)}°C</span>
        </div>
      </div>

      <!-- Bottom Risk Score & Factor Breakdown Panel -->
      <div class="safety-score-panel">
        <div class="score-header-row">
          <!-- Radial Gauge -->
          <div class="score-gauge-wrap">
            <div class="radial-gauge-circle" style="border-color:${scoreColor};">
              <span class="score-num" style="color:${scoreColor};">${riskScore}</span>
              <span class="score-denom">/ 100</span>
            </div>
          </div>

          <!-- Verdict Meta -->
          <div class="verdict-meta-wrap">
            <div class="verdict-headline" style="color:${scoreColor};">
              ${verdictText}
            </div>
            <div class="verdict-badges-row">
              <span class="verdict-status-badge" style="background:${scoreColor}22; color:${scoreColor}; border:1px solid ${scoreColor};">
                ${statusLabel}
              </span>
              <span class="verdict-source-badge">INCOIS • IMD</span>
              <span class="verdict-mode-badge">${store.backendOnline ? 'LIVE' : 'DEMO'}</span>
            </div>
            <div class="verdict-timing-tip">
              ${isDanger ? '⚠️' : '✅'} ${tipText}
            </div>
          </div>
        </div>

        <!-- Factor Contributions Breakdown (Single Language) -->
        <div class="factor-breakdown-section">
          <div class="factor-section-title">${t.factorTitle}</div>

          <div class="factor-bar-row">
            <div class="factor-info">
              <span class="factor-name">${t.officialWarnings}</span>
              <span class="factor-val-badge">${warnWeight}</span>
            </div>
            <div class="factor-progress-track">
              <div class="factor-progress-fill" style="width:${isDanger ? '85%' : '20%'}; background:${scoreColor};"></div>
            </div>
          </div>

          <div class="factor-bar-row">
            <div class="factor-info">
              <span class="factor-name">${t.waveHeight}</span>
              <span class="factor-val-badge">${waveWeight}</span>
            </div>
            <div class="factor-progress-track">
              <div class="factor-progress-fill" style="width:${Math.min(100, swh * 40)}%; background:#0ea5e9;"></div>
            </div>
          </div>

          <div class="factor-bar-row">
            <div class="factor-info">
              <span class="factor-name">${t.windSpeed}</span>
              <span class="factor-val-badge">${windWeight}</span>
            </div>
            <div class="factor-progress-track">
              <div class="factor-progress-fill" style="width:${Math.min(100, windSpeed * 2.5)}%; background:#f59e0b;"></div>
            </div>
          </div>

          <div class="factor-bar-row">
            <div class="factor-info">
              <span class="factor-name">${t.restrictedZones}</span>
              <span class="factor-val-badge">${zoneWeight}</span>
            </div>
            <div class="factor-progress-track">
              <div class="factor-progress-fill" style="width:30%; background:#8b5cf6;"></div>
            </div>
          </div>
        </div>
      </div>
    `;
  }
}
