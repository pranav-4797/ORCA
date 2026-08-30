import { OrcaApiService } from '../../services/orcaApiService';
import { store } from '../../store/appState';
import { showToast } from '../ui/Toast';

/**
 * Authority-facing SAR Boundary Surveillance widget.
 *
 * Shows:
 *  - SAR observation status: LIVE / SIMULATED / UNAVAILABLE / STALE
 *  - Unknown vessels: N / Known: N
 *  - Each unknown vessel with confidence, distance to IMBL, acquisition time, source
 *  - [View on Map] action — pans OceanMap to the detection via viz reload
 *  - Provenance badge + freshness ("Observed X minutes ago")
 *  - Explicit DEMO banner when data is simulated
 *
 * Reuses the existing design system (ECDIS tokens, telemetry widgets).
 * Authority-facing: NOT exposed as the main fisherman interface.
 */
export class SARBoundaryMonitor {
  private element: HTMLElement;
  private data: any = null;
  private statusData: any = null;
  private loading = false;

  constructor() {
    this.element = document.createElement('div');
    this.element.className = 'orca-telemetry-widget';
    this.element.id = 'sar-boundary-monitor';
    this.element.style.borderLeft = '3px solid #ef4444';
    this.render();
    void this.refresh();
  }

  public getElement(): HTMLElement {
    return this.element;
  }

  private async refresh(): Promise<void> {
    try {
      const [status, dets] = await Promise.all([
        OrcaApiService.getSarStatus().catch(() => null),
        OrcaApiService.getSarDetections().catch(() => null),
      ]);
      this.statusData = status;
      this.data = dets;
      this.render();
    } catch {
      // silent — will show UNAVAILABLE
      this.render();
    }
  }

  private async runScan(): Promise<void> {
    if (this.loading) return;
    this.loading = true;
    this.render();
    try {
      const result = await OrcaApiService.runSarScan({ provider: 'demo', useCache: false });
      this.data = result;
      showToast(`SAR scan complete: ${result.total} detections, ${result.unknown} unknown near IMBL`, result.unknown > 0 ? 'info' : 'success');
      // Merge into viz: trigger a map reload via store if we have a session
      const sid = store.vizSessionId || store.activeChatId;
      if (sid) {
        try { await store.loadViz(sid); } catch {}
      } else {
        // No active chat/session yet — inject a synthetic viz id so the map
        // can still render the SAR scan results.
        const fakeId = 'sar-demo-' + Date.now().toString(36);
        store.setSyntheticViz(this.toGeoJson(result), fakeId);
      }
      this.render();
    } catch (e: any) {
      showToast(`SAR scan failed: ${e.message || e}`, 'error');
    } finally {
      this.loading = false;
      this.render();
    }
  }

  private toGeoJson(scan: any): any {
    const features: any[] = [];
    for (const d of scan.detections || []) {
      const ms = d.match_status || '';
      const al = d.alert_level || '';
      let kind = 'sar_other';
      if (ms === 'UNKNOWN' && al === 'HIGH') kind = 'sar_unknown_high';
      else if (ms === 'UNKNOWN') kind = 'sar_unknown';
      else if (ms === 'KNOWN') kind = 'sar_known';
      else if (ms === 'LOW_CONFIDENCE') kind = 'sar_low_confidence';
      features.push({
        type: 'Feature',
        properties: {
          kind,
          detection_id: d.detection_id || d.id,
          confidence: d.confidence,
          distance_to_boundary_km: d.distance_to_boundary_km,
          boundary_segment: d.boundary_segment,
          match_status: ms,
          alert_level: al,
          source: d.source,
          dataset: d.dataset,
          acquisition_timestamp: d.acquisition_timestamp,
          status: d.status,
        },
        geometry: { type: 'Point', coordinates: [d.longitude ?? d.lon, d.latitude ?? d.lat] },
      });
    }
    // Add IMBL lines if available from status
    try {
      const bbox = this.statusData?.boundary?.bbox;
      if (bbox) {
        // boundary line added by backend viz; here we just add detections
      }
    } catch {}
    return { type: 'FeatureCollection', session_id: 'sar-demo', features };
  }

  private viewOnMap(d: any): void {
    const lat = d.latitude ?? d.lat;
    const lon = d.longitude ?? d.lon;
    if (lat == null || lon == null) return;
    // Create a single-point GeoJSON and push to store so OceanMap pans
    const single = {
      type: 'FeatureCollection',
      session_id: `sar-view-${d.detection_id || Date.now()}`,
      features: [
        {
          type: 'Feature',
          properties: {
            kind: d.alert_level === 'HIGH' ? 'sar_unknown_high' : d.match_status === 'KNOWN' ? 'sar_known' : 'sar_unknown',
            detection_id: d.detection_id || d.id,
            confidence: d.confidence,
            distance_to_boundary_km: d.distance_to_boundary_km,
            boundary_segment: d.boundary_segment,
            match_status: d.match_status,
            alert_level: d.alert_level,
            source: d.source,
            dataset: d.dataset,
            acquisition_timestamp: d.acquisition_timestamp,
            status: d.status,
          },
          geometry: { type: 'Point', coordinates: [lon, lat] },
        },
        // Include all detections as context (faded)
        ...((this.data?.detections || []).filter((x: any) => (x.detection_id || x.id) !== (d.detection_id || d.id)).slice(0, 10).map((x: any) => ({
          type: 'Feature',
          properties: {
            kind: x.match_status === 'KNOWN' ? 'sar_known' : x.alert_level === 'HIGH' ? 'sar_unknown_high' : 'sar_unknown',
            detection_id: x.detection_id || x.id,
            match_status: x.match_status,
            alert_level: x.alert_level,
          },
          geometry: { type: 'Point', coordinates: [x.longitude ?? x.lon, x.latitude ?? x.lat] },
        })) ),
      ],
    };
    // Use store's synthetic viz which sets mapPanelOpen=true and notifies — ensures
    // the map panel auto-expands on first click (benefits from AgentPanel persistent fix).
    try {
      store.setSyntheticViz(single, single.session_id);
      // Ensure the outer AgentPanel is visible on desktop/mobile so the map is actually seen
      if (!store.agentPanelOpen) store.toggleAgentPanel(true);
    } catch {
      // Fallback direct inject if store method unavailable
      (store as any).vizGeojson = single;
      (store as any).vizSessionId = single.session_id;
      (store as any).mapPanelOpen = true;
      try { (store as any).notify?.(); } catch {}
    }
    showToast(`Centered map on ${d.detection_id || 'vessel'} — ${(d.distance_to_boundary_km ?? 0).toFixed(1)} km from IMBL`, 'info');
    // Scroll map into view on mobile
    const mapEl = document.querySelector('.ocean-map-widget');
    if (mapEl) mapEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  private provenanceBadge(): string {
    const s = this.data?.status || this.statusData?.latest?.summary?.status || 'UNAVAILABLE';
    const source = this.data?.source || this.statusData?.latest?.summary?.source || 'UNAVAILABLE';
    const isStale = this.data?.is_stale || this.statusData?.latest?.summary?.is_stale;
    const dataset = this.data?.dataset || '';
    if (s === 'SIMULATED') return `<span class="cap-badge" style="background:#fef3c7;color:#92400e;border-color:#f59e0b;">⚠ DEMO — SIMULATED SAR DATA</span> <span class="cap-badge" style="background:#fef2f2;color:#991b1b;">${source} · ${dataset}</span>`;
    if (s === 'REAL') {
      const staleTag = isStale ? ' <span class="cap-badge" style="background:#fef3c7;color:#92400e;">STALE</span>' : '';
      return `<span class="cap-badge" style="background:#dcfce7;color:#166534;border-color:#22c55e;">● REAL SAR OBSERVATION</span> <span class="cap-badge">${source} · ${dataset}</span>${staleTag}`;
    }
    if (s === 'UNAVAILABLE') return `<span class="cap-badge" style="background:#f1f5f9;color:#475569;">DATA UNAVAILABLE</span> <span class="cap-badge">${this.statusData?.providers?.bhoonidhi?.note?.slice(0,60) || 'No SAR observation'}</span>`;
    return `<span class="cap-badge">${s} · ${source}</span>`;
  }

  private render(): void {
    const status = this.data?.status || this.statusData?.latest?.summary?.status || 'UNAVAILABLE';
    const source = this.data?.source || this.statusData?.latest?.summary?.source || '';
    const total = this.data?.total ?? this.data?.total_detections ?? this.statusData?.latest?.summary?.total ?? 0;
    const known = this.data?.known ?? this.data?.known_count ?? 0;
    const unknown = this.data?.unknown ?? this.data?.unknown_count ?? 0;
    const acqTime: string = this.data?.acquisition_time || this.statusData?.latest?.summary?.acquisition_time || '';
    const isStale = this.data?.is_stale || false;
    const freshness = acqTime ? this.freshnessLabel(acqTime) : '—';
    const dets: any[] = this.data?.detections || [];

    const statusColor = status === 'REAL' ? 'var(--status-safe)' : status === 'SIMULATED' ? '#d97706' : 'var(--text-tertiary)';
    const statusIcon = status === 'REAL' ? '🛰 LIVE' : status === 'SIMULATED' ? '🧪 SIMULATED' : '⚪ UNAVAILABLE';
    const staleNote = isStale ? '<span style="color:#d97706;font-weight:600;">STALE — not real-time</span>' : '';

    // Authority header
    this.element.innerHTML = `
      <div class="widget-section-header" style="border-bottom:1px solid var(--border-subtle);padding-bottom:8px;margin-bottom:8px;">
        <span class="label-caps" style="display:flex;align-items:center;gap:6px;font-weight:700;color:${statusColor};">🛰 SAR BOUNDARY MONITOR — AUTHORITY</span>
        <span class="status-pill ${status === 'REAL' ? 'safe' : status === 'SIMULATED' ? 'info' : 'critical'}" style="font-size:10px;">
          <span class="dot"></span><span class="data-mono-bold">${statusIcon}</span>
        </span>
      </div>

      <div style="font-size:11px;color:var(--text-secondary);line-height:1.5;margin-bottom:10px;">
        Independent SAR surveillance near India's maritime boundary. Compares SAR vessel detections against ORCA's known activity.<br>
        <span style="color:var(--text-tertiary);">Unknown = unmatched vessel, not "illegal" — <em>Requires authority verification.</em></span>
      </div>

      <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">${this.provenanceBadge()}</div>

      <div class="telemetry-data-grid" style="margin-bottom:10px;">
        <div class="data-cell" style="background:var(--bg-surface-hover);border-radius:6px;padding:8px;border:1px solid var(--border-subtle);">
          <span class="cell-label">UNKNOWN VESSELS</span>
          <span class="cell-val-mono" style="font-size:18px;font-weight:800;color:${unknown>0?'#ef4444':'var(--status-safe)'};">${unknown}</span>
        </div>
        <div class="data-cell" style="background:var(--bg-surface-hover);border-radius:6px;padding:8px;border:1px solid var(--border-subtle);">
          <span class="cell-label">KNOWN VESSELS</span>
          <span class="cell-val-mono" style="font-size:18px;font-weight:800;color:var(--status-safe);">${known}</span>
        </div>
        <div class="data-cell" style="background:var(--bg-surface-hover);border-radius:6px;padding:8px;border:1px solid var(--border-subtle);">
          <span class="cell-label">TOTAL SCAN</span>
          <span class="cell-val-mono" style="font-size:18px;font-weight:800;">${total}</span>
        </div>
        <div class="data-cell" style="background:var(--bg-surface-hover);border-radius:6px;padding:8px;border:1px solid var(--border-subtle);">
          <span class="cell-label">OBSERVED</span>
          <span class="cell-val-mono" style="font-size:11px;">${freshness}</span>
          <span style="font-size:10px;color:var(--text-tertiary);">${staleNote}</span>
        </div>
      </div>

      <div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;">
        <button class="btn-send-message" id="sar-btn-scan" style="width:auto;padding:6px 14px;font-size:12px;font-weight:700;border-radius:6px;display:inline-flex;align-items:center;gap:6px;${this.loading?'opacity:0.6;pointer-events:none;':''}" title="Run SAR boundary scan (Demo mode, no credentials)">
          ${this.loading ? '⏳ Scanning...' : '🛰 Run SAR Boundary Scan'}
        </button>
        <button class="icon-btn" id="sar-btn-refresh" style="font-size:11px;padding:4px 8px;width:auto;height:auto;" title="Refresh status">↻ Refresh</button>
        <button class="icon-btn" id="sar-btn-clear" style="font-size:11px;padding:4px 8px;width:auto;height:auto;" title="Clear SAR cache">Clear</button>
      </div>

      <div id="sar-details" style="display:flex;flex-direction:column;gap:8px;max-height:420px;overflow-y:auto;">
        ${dets.length === 0 ? `<div style="font-size:11px;color:var(--text-tertiary);padding:6px;">No SAR detections yet. Click <em>Run SAR Boundary Scan</em> to generate the SIH demo scenario (5 vessels, 1 unknown near IMBL).</div>` : dets.map((d: any) => this.detectionCard(d)).join('')}
      </div>

      <div style="font-size:10px;color:var(--text-tertiary);margin-top:10px;line-height:1.4;border-top:1px dashed var(--border-subtle);padding-top:6px;">
        Boundary radius ${this.statusData?.config?.boundary_radius_km ?? 10} km • Match radius ${this.statusData?.config?.match_radius_km ?? 2} km / ${this.statusData?.config?.match_window_minutes ?? 60} min • Stale &gt; ${this.statusData?.config?.stale_minutes ?? 120} min<br>
        <em>GEOINT disclaimer: Boundaries are simplified DEMO geometry — NOT FOR NAVIGATION.</em> Provenance always labeled REAL/SIMULATED/UNAVAILABLE.
      </div>
    `;

    this.element.querySelector('#sar-btn-scan')?.addEventListener('click', () => this.runScan());
    this.element.querySelector('#sar-btn-refresh')?.addEventListener('click', () => this.refresh());
    this.element.querySelector('#sar-btn-clear')?.addEventListener('click', async () => {
      try { await OrcaApiService.clearSar(); this.data = null; this.render(); showToast('Cleared SAR cache', 'success'); } catch {}
    });
    // Per-detection view buttons
    this.element.querySelectorAll('[data-sar-view]').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = (btn as HTMLElement).getAttribute('data-sar-view');
        const det = dets.find((x: any) => (x.detection_id || x.id) === id);
        if (det) this.viewOnMap(det);
      });
    });
  }

  private detectionCard(d: any): string {
    const isUnknown = d.match_status === 'UNKNOWN';
    const isHigh = d.alert_level === 'HIGH';
    const isLowConf = d.match_status === 'LOW_CONFIDENCE';
    const borderColor = isHigh ? '#ef4444' : isUnknown ? '#f59e0b' : isLowConf ? '#94a3b8' : '#22c55e';
    const bg = isHigh ? 'rgba(239,68,68,0.08)' : isUnknown ? 'rgba(245,158,11,0.08)' : 'rgba(34,197,94,0.06)';
    const icon = isHigh ? '🔴' : isUnknown ? '🟠' : isLowConf ? '⚪' : '🟢';
    const confidencePct = typeof d.confidence === 'number' ? `${(d.confidence*100).toFixed(0)}%` : '--';
    const freshness = d.acquisition_timestamp ? this.freshnessLabel(d.acquisition_timestamp) : '—';
    const age = d.age_minutes != null ? `${d.age_minutes} min ago` : freshness;

    return `
      <div style="border:1px solid ${borderColor};border-left:3px solid ${borderColor};background:${bg};border-radius:8px;padding:10px;display:flex;flex-direction:column;gap:6px;">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
          <span style="font-family:var(--font-mono);font-size:11px;font-weight:700;color:${borderColor};">${icon} ${d.match_status || 'UNKNOWN'} ${isHigh?'— HIGH':isUnknown?'':''}</span>
          <span class="cap-badge" style="font-size:10px;">conf ${confidencePct}</span>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;">
          <div><span style="color:var(--text-tertiary);font-size:10px;">DETECTION ID</span><br><span style="font-family:var(--font-mono);font-weight:600;">${d.detection_id || d.id}</span></div>
          <div><span style="color:var(--text-tertiary);font-size:10px;">DISTANCE TO IMBL</span><br><span style="font-family:var(--font-mono);font-weight:700;color:${isHigh?'#ef4444':isUnknown?'#d97706':'var(--text-primary)'};">${(d.distance_to_boundary_km ?? 0).toFixed(1)} km</span></div>
          <div><span style="color:var(--text-tertiary);font-size:10px;">COORDINATES</span><br><span style="font-family:var(--font-mono);">${(d.latitude ?? d.lat ?? 0).toFixed(3)}, ${(d.longitude ?? d.lon ?? 0).toFixed(3)}</span></div>
          <div><span style="color:var(--text-tertiary);font-size:10px;">OBSERVED</span><br><span style="font-family:var(--font-mono);font-size:11px;">${age}</span></div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:4px;font-size:10px;">
          <span class="cap-badge">${d.source || 'SIM'} · ${d.dataset || ''}</span>
          <span class="cap-badge">${(d.boundary_segment || '').slice(0,28)}</span>
          <span class="cap-badge">${d.status || ''}</span>
          ${d.matched_vessel_id ? `<span class="cap-badge" style="background:#dcfce7;color:#166534;">matched: ${d.matched_vessel_id.slice(0,14)}</span>` : isUnknown ? `<span class="cap-badge" style="background:#fef3c7;color:#92400e;">No matching ORCA vessel</span>` : ''}
        </div>
        ${isUnknown ? `<div style="font-size:11px;color:#92400e;background:#fffbeb;border:1px solid #fcd34d;border-radius:6px;padding:6px;">🚨 <strong>Unknown vessel near maritime boundary</strong> — SAR confidence ${confidencePct}, ${(d.distance_to_boundary_km ?? 0).toFixed(1)} km from IMBL. No matching ORCA vessel within configured window. <strong>Requires authority verification.</strong><br><span style="font-size:10px;color:var(--text-tertiary);">Unknown / unmatched — not a determination of illegality.</span></div>` : ''}
        ${!isUnknown && d.match_status === 'KNOWN' ? `<div style="font-size:11px;color:#166534;">✓ Matched to ORCA activity ${d.matched_vessel_id ? `(${d.matched_vessel_id.slice(0,16)})` : ''} — no alert.</div>` : ''}
        ${isLowConf ? `<div style="font-size:11px;color:#475569;">Low confidence (${confidencePct}) — not surfaced as UNKNOWN. Verify with higher-resolution SAR.</div>` : ''}
        <button data-sar-view="${d.detection_id || d.id}" style="align-self:flex-start;margin-top:2px;padding:4px 10px;font-size:11px;border:1px solid var(--border-default);border-radius:999px;background:var(--bg-surface);cursor:pointer;">📍 View on Map</button>
      </div>
    `;
  }

  private freshnessLabel(iso: string): string {
    try {
      const t = new Date(iso).getTime();
      if (isNaN(t)) return iso.slice(0,16);
      const diffMin = Math.round((Date.now() - t) / 60000);
      if (diffMin < 1) return 'Just now';
      if (diffMin < 60) return `Observed ${diffMin} min ago`;
      const h = Math.floor(diffMin/60);
      const m = diffMin%60;
      return `Observed ${h}h ${m}m ago`;
    } catch { return iso.slice(0,16); }
  }
}
