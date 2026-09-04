import { store } from '../../store/appState';
import { OrcaApiService } from '../../services/orcaApiService';
import { showToast } from '../ui/Toast';
import { OceanMap } from '../map/OceanMap';

const COPY: Record<string, Record<string, string>> = {
  en: {
    header: 'Quick Actions',
    location: 'Active location',
    change: 'Change',
    pick: 'Pick a location to start',
    pickSub: 'Use a map pin or your current GPS. Quick actions are disabled until you do.',
    pinOnMap: '📍  Pin on Map',
    useGps: '🛰  Use Current Location',
    pfz: 'Nearest PFZ',
    sst: 'Sea Temperature',
    wind: 'Wind',
    tide: 'Tide',
    hint: 'Tap a card to run it. PFZ maps the zone; the others ask ORCA in chat.',
    pinMode: 'Tap the sea to drop a pin…',
    pinSet: 'Pin set',
    gpsSet: 'Using current location',
    noGps: 'No live GPS — pin on the map instead',
  },
  mr: {
    header: 'जलद कृती',
    location: 'सक्रिय स्थान',
    change: 'बदला',
    pick: 'प्रारंभ करण्यासाठी स्थान निवडा',
    pickSub: 'नकाशावर पिन करा किंवा सध्याचे GPS वापरा. ते होईपर्यंत जलद कृती बंद आहेत.',
    pinOnMap: '📍  नकाशावर पिन करा',
    useGps: '🛰  सध्याचे स्थान वापरा',
    pfz: 'जवळचे PFZ',
    sst: 'समुद्र तापमान',
    wind: 'वारा',
    tide: 'भरती',
    hint: 'कृती चालवण्यासाठी कार्डवर टॅप करा. PFZ नकाशावर जाते; बाकी ORCA ला विचारतात.',
    pinMode: 'पिन टाकण्यासाठी समुद्रावर टॅप करा…',
    pinSet: 'पिन सेट झाले',
    gpsSet: 'सध्याचे स्थान वापरले',
    noGps: 'लाइव GPS नाही — नकाशावर पिन करा',
  },
  hi: {
    header: 'त्वरित क्रियाएँ',
    location: 'सक्रिय स्थान',
    change: 'बदलें',
    pick: 'शुरू करने के लिए स्थान चुनें',
    pickSub: 'मानचित्र पर पिन लगाएँ या अपना वर्तमान GPS इस्तेमाल करें। ऐसा करने तक त्वरित क्रियाएँ बंद हैं।',
    pinOnMap: '📍  मानचित्र पर पिन लगाएँ',
    useGps: '🛰  वर्तमान स्थान इस्तेमाल करें',
    pfz: 'निकटतम PFZ',
    sst: 'समुद्र का तापमान',
    wind: 'हवा',
    tide: 'ज्वार',
    hint: 'चलाने के लिए कार्ड पर टैप करें। PFZ मानचित्र पर दिखता है; बाकी ORCA से चैट में पूछते हैं।',
    pinMode: 'पिन गिराने के लिए समुद्र पर टैप करें…',
    pinSet: 'पिन सेट हो गया',
    gpsSet: 'वर्तमान स्थान इस्तेमाल किया',
    noGps: 'लाइव GPS नहीं — मानचित्र पर पिन लगाएँ',
  },
};

interface ActionDef {
  id: 'pfz' | 'sst' | 'wind' | 'tide';
  labelKey: keyof typeof COPY.en;
  icon: string;
}

const ACTIONS: ActionDef[] = [
  { id: 'pfz', labelKey: 'pfz', icon: '🎣' },
  { id: 'sst', labelKey: 'sst', icon: '🌡️' },
  { id: 'wind', labelKey: 'wind', icon: '💨' },
  { id: 'tide', labelKey: 'tide', icon: '🌀' },
];

const NATURAL_QUESTIONS: Record<'sst' | 'wind' | 'tide', Record<string, string>> = {
  sst: {
    en: "What's the sea temperature at {lat},{lon}?",
    mr: '{lat},{lon} येथे समुद्राचे तापमान काय आहे?',
    hi: '{lat},{lon} पर समुद्र का तापमान क्या है?',
  },
  wind: {
    en: "What's the wind at {lat},{lon}?",
    mr: '{lat},{lon} येथे वाऱ्याची स्थिती काय आहे?',
    hi: '{lat},{lon} पर हवा कैसी है?',
  },
  tide: {
    en: "What's the tide at {lat},{lon}?",
    mr: '{lat},{lon} येथे भरती-ओहोटी कशी आहे?',
    hi: '{lat},{lon} पर ज्वार कैसा है?',
  },
};

export class QuickActionsDock {
  private element: HTMLElement;
  private oceanMap: OceanMap | null;
  /** When true the next map click commits a pin and exits this mode. */
  private pinArmed = false;
  private onSelectGps: (() => void) | null = null;

  constructor(oceanMap?: OceanMap) {
    this.oceanMap = oceanMap || null;
    this.element = document.createElement('div');
    this.element.className = 'quick-actions-dock';
    this.render();
    store.subscribe(() => this.render());
  }

  public getElement(): HTMLElement { return this.element; }
  public setOceanMap(map: OceanMap) { this.oceanMap = map; }

  /** Lets the map component (or any caller) flip on the "next click = pin" flag. */
  public setPinArmed(armed: boolean) {
    this.pinArmed = armed;
    this.render();
  }

  private render() {
    const lang = (store.activeLanguage || 'en') as 'en' | 'mr' | 'hi';
    const t = COPY[lang] || COPY.en;
    const loc = store.activeLocation;

    if (!loc) {
      this.element.innerHTML = this._renderPicker(t, lang);
      this._wirePicker();
      return;
    }

    const latStr = `${loc.lat.toFixed(2)}°N`;
    const lonStr = `${loc.lon.toFixed(2)}°E`;
    const sourceLabel = loc.source === 'map_pin'
      ? (lang === 'mr' ? 'नकाशावर पिन' : lang === 'hi' ? 'मानचित्र पिन' : 'Map pin')
      : (lang === 'mr' ? 'सध्याचे GPS' : lang === 'hi' ? 'वर्तमान GPS' : 'Current GPS');

    this.element.innerHTML = `
      <div class="qad-location">
        <div class="qad-pin-icon">📍</div>
        <div class="qad-location-text">
          <div class="qad-location-label">${this._escape(loc.label || sourceLabel)}</div>
          <div class="qad-coords">${latStr}, ${lonStr} <span class="qad-source">· ${sourceLabel}</span></div>
        </div>
        <button class="qad-change-btn" type="button" data-action="change">${t.change}</button>
      </div>
      ${this.pinArmed ? `<div class="qad-pin-banner">${t.pinMode}</div>` : ''}
      <div class="qad-grid">
        ${ACTIONS.map(a => `
          <button class="qad-action qad-action-${a.id}" type="button" data-action="${a.id}">
            <div class="qad-action-icon">${a.icon}</div>
            <div class="qad-action-label">${this._escape(t[a.labelKey])}</div>
          </button>
        `).join('')}
      </div>
      <div class="qad-hint">${this._escape(t.hint)}</div>
    `;

    this._wireActions();
    this._wireChange();
  }

  private _renderPicker(t: Record<string, string>, lang: 'en' | 'mr' | 'hi'): string {
    const hasGps = !!(store.gpsCoords &&
      (store.gpsStatus === 'granted' || store.gpsStatus === 'cached'));
    const noGps = !hasGps
      ? `<div class="qad-no-gps">${this._escape(t.noGps)}</div>`
      : '';
    return `
      <div class="qad-picker">
        <div class="qad-picker-title">${this._escape(t.pick)}</div>
        <div class="qad-picker-sub">${this._escape(t.pickSub)}</div>
        ${noGps}
        <button class="qad-pick-btn qad-pick-pin" type="button" data-pick="pin">${this._escape(t.pinOnMap)}</button>
        <button class="qad-pick-btn qad-pick-gps" type="button" data-pick="gps" ${hasGps ? '' : 'disabled'}>${this._escape(t.useGps)}</button>
      </div>
    `;
  }

  private _wirePicker() {
    this.element.querySelector<HTMLElement>('[data-pick="pin"]')?.addEventListener('click', () => {
      this.pinArmed = true;
      const t = this._t();
      showToast(t.pinMode, 'info');
      // Scroll the map into view so the user can see where to tap.
      const mapEl = document.querySelector('.ocean-map-widget');
      mapEl?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      this.render();
    });
    this.element.querySelector<HTMLElement>('[data-pick="gps"]')?.addEventListener('click', () => {
      if (!store.gpsCoords) {
        void OrcaApiService.acquireLiveGps();
        return;
      }
      store.setActiveLocation({
        lat: store.gpsCoords[0], lon: store.gpsCoords[1],
        source: 'gps',
        label: 'Current GPS',
      });
      // Also pin the map so the next /query gets device_gps on the payload.
      store.setMapPoint([store.gpsCoords[0], store.gpsCoords[1]]);
      showToast(this._t().gpsSet, 'success');
      this.onSelectGps?.();
      this.render();
    });
  }

  private _wireActions() {
    this.element.querySelectorAll<HTMLElement>('[data-action]').forEach(el => {
      const kind = el.dataset.action as 'pfz' | 'sst' | 'wind' | 'tide' | 'change';
      if (kind === 'change') return;
      el.addEventListener('click', () => this._handleAction(kind));
    });
  }

  private _wireChange() {
    this.element.querySelector<HTMLElement>('[data-action="change"]')?.addEventListener('click', () => {
      this.pinArmed = false;
      this.render();
    });
  }

  private async _handleAction(kind: 'pfz' | 'sst' | 'wind' | 'tide') {
    const loc = store.activeLocation;
    if (!loc) return;

    // Personalize: tell the backend which card the fisher touched. This
    // drives the future card ranking. We don't render the score -- it's
    // only used server-side to order the cards.
    void OrcaApiService.tapDashboardCard({
      user_key: store.currentUser?.uid,
      lat: loc.lat, lon: loc.lon,
      language: (store.activeLanguage || 'en') as any,
      card: kind,
    });

    if (kind === 'pfz') {
      // PFZ: map action only -- never a chat message.
      await this._runPfzOnMap(loc);
      return;
    }

    // SST / Wind / Tide: invisibly auto-submit through the existing chat
    // pipeline so the user sees the answer in the chat conversation
    // exactly like they asked the question themselves.
    const lang = (store.activeLanguage || 'en') as 'en' | 'mr' | 'hi';
    const template = NATURAL_QUESTIONS[kind]?.[lang] || NATURAL_QUESTIONS[kind].en;
    const prompt = template
      .replace('{lat}', loc.lat.toFixed(4))
      .replace('{lon}', loc.lon.toFixed(4));

    // The chat pipeline already uses store.mapPoint if set, so the
    // backend's location context is exactly what the user picked here.
    if (!store.mapPoint) {
      store.setMapPoint([loc.lat, loc.lon]);
    }
    void store.sendMessage(prompt, []);
  }

  private async _runPfzOnMap(loc: { lat: number; lon: number }) {
    // Pull the latest dashboard for the tap, then drive the map.
    const snap = store.dashboard as any;
    let pfzCard = snap?.cards?.find((c: any) => c.type === 'pfz');
    if (!pfzCard) {
      // Force a fresh /dashboard so the user always sees the *current*
      // nearest zone, not a stale one from a different point.
      const fresh = await OrcaApiService.fetchDashboard({
        user_key: store.currentUser?.uid,
        lat: loc.lat, lon: loc.lon,
        language: (store.activeLanguage || 'en') as any,
        skip_briefing: true,
      });
      if (fresh) {
        store.setDashboard(fresh, null);
        pfzCard = fresh.cards?.find((c: any) => c.type === 'pfz');
      }
    }
    if (!pfzCard) {
      showToast('No PFZ available right now', 'info');
      return;
    }
    if (this.oceanMap && pfzCard.center) {
      this.oceanMap.flyToPFZ({
        center: [pfzCard.center[0], pfzCard.center[1]],
        distance_km: Number(pfzCard.value) || 0,
        bearing_deg: pfzCard.bearing_deg || 0,
        bearing_compass: pfzCard.bearing_compass || '',
        sst: pfzCard.sst_at_zone_celsius ?? null,
        landmark: pfzCard.landmark ?? null,
        headline: pfzCard.headline || 'Nearest PFZ',
        source: pfzCard.source,
      });
    } else {
      showToast('Map not ready', 'info');
    }
  }

  private _t(): Record<string, string> {
    const lang = (store.activeLanguage || 'en') as 'en' | 'mr' | 'hi';
    return COPY[lang] || COPY.en;
  }

  private _escape(s: string): string {
    return String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string)
    );
  }
}
