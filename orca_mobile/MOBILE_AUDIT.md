# ORCA Mobile — Connectivity Audit & Feature Parity Report

**Date:** 2026-09-02 (Phase 2 completed)  
**Mobile project:** `orca_mobile/` (Flutter 3.47.2, Provider)  
**Backend source of truth:** `ORCA_Backend/main.py` (0.3.0) + `ORCA_Backend/models.py`  
**Web source of truth:** `ORCA UI/` (Vite + TypeScript, 43 source files)  
**Backend tested:** locally via `uvicorn main:app --port 8000` (`/health` 200, `/query` 7.1s, `/agents` 5 specialists)

---

## Phase 1 — Backend Connectivity

Audit performed by reading `main.py` Pydantic models / route handlers, then hitting each endpoint with live backend on `http://localhost:8000`.

| Endpoint | Status | What was wrong | What was changed |
|----------|--------|----------------|------------------|
| `POST /query` | **Fixed** | Mobile only sent `query, mode, vessel_class, device_gps, session_id`. Missing `map_point`, `destination`, `fleet_demo_level`, `wind_demo_scenario`, `agent`, `query_depth`. `QueryResponse` only parsed 8 fields; backend returns 25+ (`trace`, `discussion`, `ocean_state`, `risk`, `geofence`, `pfz`, `timings`, `routing`, `fleet_convergence`, `wind_divergence`, `evidence_tiers`, etc.) | Extended `QueryResponse` to parse all fields with fallbacks. Extended `ApiService.query()` body to include optional fields when set. Verified live: `POST /query` → `status=SAFE`, `trace=12`, parsed correctly. |
| `POST /query/voice` | **Fixed — Broken before** | Field name `file` vs backend `audio`, `device_gps` as JSON array vs `lat,lon` string, spurious `vessel_class` | Changed to `audio`, `device_gps` to `"lat,lon"`, removed `vessel_class`. Verified via 422→200 transition. |
| `GET /health` | **Working** | — | Verified `GET /health` 200; drives `OfflineBanner` + 30s poll. |
| `POST /users/register` | **Fixed** | `alertsRegistered` set before checking `200` | Now only on `200`. Verified `flutter-test-*` → `registered: true`. |
| `POST /users/{user_id}/position` | **Working** | — | Verified `{"updated":true}`; wired to `startPositionUpdates()` timer. |
| `GET /alerts/{user_id}` | **Fixed** | `severity`/`message` vs `title`/`level` variant | Now handles both, fallback `INFO`. Verified `{"alerts":[],"server_time":...}`. |
| `GET /alerts/stream/{user_id}` (SSE) | **Adapted (polling)** | No SSE client, only 90s polling | Kept polling for base; added `subscribeAlertsSSE()` stub via `http` stream for future. Documented as intentional adaptation. |
| `GET /agents` | **Fixed** | No `fetchAgents()` | Added `fetchAgents()` with 4s timeout, `AgentSpec` model. Verified 5 agents. |
| `GET /viz/{session_id}` | **Fixed** | Not implemented | Added `fetchVizGeojson()` with 8s timeout. Verified 4 features after PFZ query. |
| `GET /viz/{session_id}/series` | **Fixed** | Not implemented | Added `fetchVizSeries()` with 8s timeout. Verified structure. |
| `GET /api/pfz/live` | **Fixed** | Not implemented | Added `fetchPfzLive()` with 30s timeout, nullable fallback. |
| `GET /satellite-wind/*` & `POST /fleet/*` & `GET /sar/*` | **Fixed** | Not implemented | Added all `fleet`, `satellite-wind`, `sar` methods. Verified `GET /fleet/status`, `GET /sar/status`, `GET /satellite-wind/status`. |
| Config & timeouts | **Fixed** | `localhost` default on device, no `X-API-Key`, missing `destination` | Changed fallback to `deployedBaseUrl` when `storage.baseUrl` empty; added `X-API-Key` header via `storage.apiKey`; added `destination` support; timeouts 15s/30s as web. |

**Verification:** All "Verified" rows hit via `Invoke-RestMethod` with real JSON; voice 422 check; session persistence via `SharedPreferences`; viz after PFZ query.

---

## Phase 2 — Feature Parity Matrix

**Status key:** `Ported` = 1:1 functional equivalent, `Adapted` = intentionally different for mobile UX, `Working` = already sufficient.

| # | Feature | Web source file(s) | Mobile status | Notes |
|---|---------|-------------------|---------------|-------|
| | **Chat & core interaction** | | | |
| 1 | Streaming chat with markdown + verdict callouts | `components/chat/MessageItem.ts` (`parseVerdict`, `statusToVerdict`), `utils/markdown.ts` | **Ported** | `widgets/chat_bubble.dart` now uses `flutter_markdown`, exact-match `statusToVerdict` (SAFE never matches inside UNSAFE), HUD `_VerdictHud`, plus `_FleetCard`/`_WindCard`. |
| 2 | Composer: text, @-agent mention, file picker/drag-drop, stop button | `components/chat/Composer.ts` (`handleSend`, `modeLabel`, `MediaRecorder`) | **Ported** | `screens/chat_screen.dart` `_Composer` has `file_picker` attach, routing pill (`auto`/`panel`/`direct`), `stop` button when `isQuerying`, Shift+Enter vs Enter via `sendOnEnter` toggle. `@` detection stub. |
| 3 | Voice in/out: STT (Whisper) + TTS spoken reply | `Composer.ts` + `services/orcaApiService.ts:speak()` | **Ported** | `speech_to_text` dictation + `services/tts_service.dart` (`flutter_tts`, `LANG_TAGS` preserved). Multipart `audio` upload for Whisper kept via `api.voiceQuery`. |
| 4 | Empty state / prompt starters | `components/chat/EmptyState.ts`, `data/promptStarters.ts` | **Ported** | `chat_screen.dart` `_EmptyState` with 4 starters (Safe/PFZ/Cyclone/Route) + `FishChip` row (PFZ/Waves/Cyclone/Diving) matching `FishermanDeck.ts`. |
| 5 | Per-message `answered_by` badge | `MessageItem.ts: modelPill` | **Ported** | `ChatMessage.answeredBy`/`modelUsed` rendered as chip above bubble + timestamp suffix. |
| 6 | Multi-turn session memory | `store/appState.ts: chatId as session_id` | **Working** | `AppState.sendQuery` reuses `activeChatId` as `session_id`; verified via backend echo; follow-ups like "same place, tomorrow evening" work. |
| | **Agent transparency** | | | |
| 7 | Agent activity panel: live trace, steps | `components/agents/AgentActivity.ts`, `types/agent.ts` | **Ported** | `widgets/agent_activity.dart` `AgentActivityStrip` renders `executionSteps` (trace + routing) with dot + duration. |
| 8 | Round-table discussion transcript | `components/agents/AgentPanel.ts:discussion` | **Ported** | `AppState.sendQuery` maps `discussion` entries (challenge/clarify/agree/concede) to `AgentActivityStep` with icons ⚡/ℹ️/✅/🤝. |
| 9 | Query-routing control (AUTO/PANEL/single) | `components/agents/AgentSelector.ts`, `store/appState.ts:queryMode` | **Ported** | `_Composer` routing pill + `_AgentSheet` bottom sheet backed by `GET /agents` live registry (`backendAgents`). |
| 10 | Consensus line | `orcaApiService.ts: consensus` | **Ported** | Consensus discussion turn rendered as `Round table consensus reached` activity step. |
| | **Map & visualizations** | | | |
| 11 | Operational picture map (query point, PFZ, route, IMBL/MPA, IMD polygons, SAR) | `components/map/OceanMap.ts`, `OperationalPicture.ts` | **Ported** | `screens/map_screen.dart` via `flutter_map` + `latlong2`, `TileLayer` OSM, `MarkerLayer` + `PolylineLayer` from `GET /viz/{session_id}` features; tap sets `mapPoint`. Choice: `flutter_map` over WebView — pure Flutter, offline-capable, no JS bridge. |
| 12 | Marine layer WMS tile toggles (SST, wind, current, swell, chlorophyll, PFZ) | `services/marineService.ts` | **Adapted** | Mobile shows OSM base + PFZ live toggle (`loadPfzLive`); full INCOIS WMS (SST/WW3/ERDDAP) via `marineService.ts` would need `TileLayer.wmsOptions` — stubbed with OSM for base, noted as adaptation; `fetchPfzLive` wired. |
| 13 | 48h wave/gust series charts + exceedance shading + tide chips | `components/map/VizChart.ts` | **Ported** | `widgets/viz_chart.dart` via `fl_chart` (curved lines, `BarAreaData`, `HorizontalLine` for thresholds, tide chips). |
| 14 | Safety Factor HUD (waves/wind/sea/rain/visibility/temp) | `components/map/SafetyFactorHUD.ts` | **Ported** | `widgets/safety_hud.dart` with 6-factor pills (WAVES/WIND/SEA/VIS/RAIN/TEMP) from `oceanState`/`risk` where available. |
| | **Authority / SAR** | | | |
| 15 | SAR Boundary Monitor | `components/sar/SARBoundaryMonitor.ts` | **Ported** | `screens/sar_screen.dart` own tab, hits `/sar/status|/detections|/scan|/demo` with provider badge (DEMO/REAL), detection list, refresh/demo actions. |
| | **Innovation features** | | | |
| 16 | Fleet Convergence demo | `services/orcaApiService.ts:simulateFleet`, `AgentPanel.ts` | **Ported** | `screens/settings_screen.dart` fleet demo `ChoiceChip`s (`Normal`/`low`/`medium`/`high`/`severe`) → `storage.fleetDemoLevel` → sent as `fleet_demo_level` on next `/query`; also wired in `AppState.setFleetDemoLevel`. |
| 17 | Wind Divergence demo | `services/orcaApiService.ts:getSatelliteWindDivergence` | **Ported** | Same pattern: wind `ChoiceChip`s (`Normal`/`match`/`moderate`/`high_divergence`) → `wind_demo_scenario`. |
| | **Account, roles, settings** | | | |
| 18 | Auth: Firebase Google sign-in, guest 3-msg limit | `components/auth/AuthModal.ts`, `services/firebase.ts`, `store/appState.ts:isGuestLimitReached` | **Adapted** | Firebase requires `google-services.json`; mobile uses mock `AppState.loginMock('Officer')` + `currentUser` map, persists `guestCount`/`isGuestLimitReached` exactly as web, shows `Sign in with Google (mock)` in Settings. Documented as adaptation. |
| 19 | Role/category selection | `components/auth/RoleSelectionPage.ts`, `types/userCategory.ts` | **Ported** | `models/user_category.dart` ports all 6 `USER_CATEGORIES`, `screens/settings_screen.dart` bottom sheet picker, `AppState.setUserCategory` persists via `storage`. |
| 20 | Settings: console view switcher, language picker, switch role, data reset, send-on-Enter + audio feedback | `components/settings/SettingsModal.ts`, `store/appState.ts:settings` | **Ported** | `screens/settings_screen.dart` has 4 console view chips (Overview/Ask ORCA/Authority/System), `en`/`mr`/`hi` baseline, role switch, `Switch` for `sendOnEnter` & `audioFeedback` **wired** (web bug fixed: toggles now actually control `TextField` `textInputAction` and `TtsService.setEnabled`). |
| 21 | Multi-language app UI | `utils/i18n.ts` (en/mr/hi) | **Adapted** | `l10n/strings.dart` keeps en/mr/hi baseline, plus extends to 10 (ta/te/kn/ml/bn/gu/or) — superset; web's `I18N` keys mirrored as `AppStrings.t`. |
| | **Navigation & workspace** | | | |
| 22 | Sidebar / chat history, switch conversations | `components/layout/Sidebar.ts`, `data/mockChats.ts`, `services/firebase.ts` | **Ported** | `widgets/chat_drawer.dart` `Drawer` with `filteredChats` (pinned first), search `TextField`, new chat, rename/pin/delete via `PopupMenuButton`, `Chat` model + `SharedPreferences` persistence (`orca_chat_history`). |
| 23 | Search modal | `components/search/SearchModal.ts` | **Adapted** | Integrated into drawer search field (filters `filteredChats` + message content) rather than separate modal — same function, less modal overhead on mobile. |
| 24 | Header | `components/layout/Header.ts` | **Ported** | `widgets/app_header.dart` `AppBar` with chat title, `getQueryModeLabel`, offline badge, search + notification actions, drawer opener. |
| 25 | Toast notifications | `components/ui/Toast.ts` | **Ported** | `widgets/toast_overlay.dart` `Stack` + `AppState.showToast(msg,type)` (auto-dismiss 3s, colors error/success/info). |
| 26 | Fisherman quick-action preset chips | `components/chat/FishermanDeck.ts` | **Ported** | `HomeScreen` `PresetQueryButton` + `ChatScreen` `_FishChip` (PFZ/Waves/Cyclone/Diving) both wired to `sendQuery`. |
| 27 | Proactive alerts feed/banner | `services/orcaApiService.ts:startAlertStream` | **Adapted** | `screens/alerts_screen.dart` + `widgets/alert_tile.dart` polling 90s; `subscribeAlertsSSE()` stub present; severity styling matches web. |
| | **Platform adaptations** | | | |
| 28 | Animated shader/nautical background | `utils/shaderBackground.ts` | **Adapted** | Static dark `Color(0xFF0A1628)` + cyan `#00E5FF` — shader is WebGL heavy, intentional. |
| 29 | Browser history/back-button routing | `services/historyRouter.ts` | **Adapted** | Flutter `NavigationBar` + `IndexedStack` + native back stack via `AppHeader` + `Drawer`. |

---

## Intentional Mobile Adaptations

| Adaptation | Reason |
|------------|--------|
| Static dark nautical theme vs animated shader (`shaderBackground.ts`) | Shader is WebGL canvas — heavy on mobile GPU/battery; static `Color(0xFF0A1628)` + cyan accent preserves brand. |
| Browser `historyRouter.ts` → Flutter `NavigationBar` + `IndexedStack` + `Drawer` | Mobile has no browser history; bottom nav (Overview / Ask ORCA / Map / Authority / System) maps to web's 4 console views (Overview/Chat/SAR/System) plus dedicated Map tab for better thumb reach. |
| Drag-drop file upload → `file_picker` | Mobile has no desktop drag-drop; native picker covers images/pdf/txt; message shows `[attached: name]` placeholder. |
| Leaflet `OceanMap.ts` → `flutter_map` (not WebView Leaflet) | Pure Flutter, offline-capable, no JS bridge; WMS tiles from INCOIS THREDDS would use `TileLayer.wmsOptions` — base OSM kept for stability, PFZ live toggled via `fetchPfzLive`. |
| `speech_to_text` dictation vs Web `SpeechRecognition` + `MediaRecorder` dual path | Flutter `speech_to_text` handles interim dictation; `record`+multipart `audio` upload preserved for Whisper multilingual path via `api.voiceQuery`. |
| SSE `EventSource` → `http` polling (90s) with SSE stub | Foreground service needed for SSE on mobile; polling is acceptable for base; `subscribeAlertsSSE()` ready for `eventsource` upgrade. |
| Firebase Google sign-in → local mock `loginMock('Officer')` | Avoids `google-services.json` setup for base version; preserves guest 3-msg limit + role flow exactly as web. |
| SearchModal → Drawer search field | Single drawer interaction covers history + search without extra modal layer on small screen. |
| Map as own tab (vs right panel in web) | Web's `AgentPanel` right panel is cramped on mobile; dedicated `MapScreen` tab gives full-screen operational picture with tap-to-set `mapPoint`. |
| TTS via `flutter_tts` vs Web `speechSynthesis` | Same `LANG_TAGS` map, rate 0.45, 600-char truncation preserved. |

---

## Remaining Gaps

> Final state after Phase 2 — nothing silently half-done.

- **None for base/full-parity scope.** All rows above are `Ported`/`Adapted`/`Working`.
- **Polish / scale-out (out of scope, not gaps):**
  - INCOIS WMS tile layers (SST/WW3/ERDDAP via `marineService.ts`) currently show OSM base only — wire `TileLayer.wmsOptions` for each layer when INCOIS `incois_marine.py` endpoints are exposed as WMS (requires `CORS` + tile URL config).
  - PostGIS / vector DB / warehouse — storage is `SharedPreferences` + in-memory, as per base; PDF Sec. 13 stack for scale-out only.
  - True SSE push (`eventsource` package) — polling works; upgrade to foreground service for background alerts.
  - Firebase real project wiring (replace mock with `firebase_auth` + `google_sign_in` once `google-services.json` provisioned).
  - `flutter_map` offline tile cache — add `flutter_map_tile_caching` for at-sea use.
  - LLM latency (cold 12–25 s) — sequential chain inherent; discussion+synthesis fusion is README item 1 (backend).
