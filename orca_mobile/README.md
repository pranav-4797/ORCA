# ORCA Mobile — Marine Safety Assistant (Full Parity)

Flutter mobile companion for **ORCA** (Marine EcOsystem Reasoning with Collaborative Agents) — SIH 2026, PS-26176 (ISRO). Full-parity port of `ORCA UI/` (Vite + React + Leaflet) adapted for mobile.

## Quick Start

```bash
cd orca_mobile
flutter pub get
flutter run                 # Chrome (web) for desktop demo, or Android device/emulator
flutter run -d chrome       # forces web phone-frame (412×892) — looks like mobile on desktop
```

Backend must be running for live data:

```bash
cd ORCA_Backend
pip install -r requirements.txt
python -m uvicorn main:app --port 8000  # → http://localhost:8000
```

## Backend URL Configuration

The app picks the backend in this priority:

1. **In-app:** `System` tab → **Backend URL** field (persisted in `SharedPreferences` as `orca_base_url`). Change it live, no rebuild.
2. **Fallback:** `lib/config/api_config.dart` → `defaultBaseUrl` (`http://localhost:8000` for simulator/emulator) and `deployedBaseUrl` (`https://orca-backend-1i5u.onrender.com` on Render, free tier — may be cold on first request).
3. **Override:** If `ORCA_API_KEY` env is set on backend, set the same key via `Settings → Backend URL` companion field (`storage.apiKey`) — sent as `X-API-Key` on every request.

> On a physical Android device, `localhost` is the phone itself — use `10.0.2.2` (emulator) or the deployed URL. The in-app field avoids rebuilding.

## Features (Full Parity — no longer base-only)

### Chat & core
- Streaming chat with **markdown** rendering, **verdict callouts** (exact SAFE-in-UNSAFE fix), fleet/wind cards
- Composer: text + `@agent` routing pill (AUTO/PANEL/single specialist backed by `GET /agents`), file picker, stop generation, *send on Enter* toggle (wired)
- Voice **in/out**: `speech_to_text` dictation + multipart `audio` Whisper upload + `flutter_tts` spoken reply in detected language
- Empty state with 4 prompt starters + fisherman quick chips
- Per-message `answered_by` badge + `session_id` multi-turn memory (follow-ups like "same place, tomorrow evening")
- 3-message guest limit before sign-in (mock)

### Agent transparency
- Agent activity strip: live `trace` steps with duration
- Round-table discussion transcript (challenge/clarify/agree/concede + consensus)
- Query-routing pill: AUTO (fast) / PANEL (full deliberation) / direct specialist

### Map & visualizations
- Operational picture map: `flutter_map` (OSM base, PFZ live toggle), query point, PFZ/fleet/route/IMBL/SAR markers, tap-to-set `map_point`, `GET /viz/{session_id}`
- 48h wave/gust series via `fl_chart` with threshold shading + tide chips (`GET /viz/{session_id}/series`)
- Safety Factor HUD (6 factors)
- Marine WMS base OSM; INCOIS SST/wind/current tiles stubbed — see `MOBILE_AUDIT.md` adaptation note

### Authority / SAR
- SAR Boundary Monitor own tab: `GET /sar/status|/detections|/scan|/demo`, provider badge (DEMO/REAL), detection list (HIGH/MEDIUM alert)

### Innovation
- Fleet Convergence demo: `fleet_demo_level` chip → sent on next `/query`
- Wind Divergence demo: `wind_demo_scenario` chip → sent on next `/query`

### Account, roles, settings
- Auth mock: `Sign in with Google (mock)` → local `currentUser`, guest limit
- Role selection: 6 categories (General, Fisherman, Trawler, Coast Guard, Port, Scientist) with `USER_CATEGORIES` parity, per-role vessel class
- Settings: console view switcher (Overview/Ask ORCA/Authority/System), language **en/mr/hi** (web baseline) + extends, switch role, data reset, **send on Enter** + **audio feedback** toggles (now wired, web bug fixed), fleet/wind demo chips, backend URL, clear chat
- Multi-language UI via `l10n/strings.dart` (10 languages, web ships 3)

### Navigation & workspace
- Sidebar drawer: chat history (pinned first), new/rename/pin/delete, local persistence (`SharedPreferences`), search filter
- Search in drawer (adapted from web modal)
- Header with chat title, `AUTO → agent` indicator, offline badge
- Toast overlay (offline, guest limit, language switch)
- Fisherman deck chips on Overview + Chat
- Proactive alerts feed (polling 90s, SSE stub `subscribeAlertsSSE()`)

### Explicitly adapted (not literal 1:1)
- Shader nautical background → static dark navy `#0A1628` + cyan `#00E5FF`
- Browser `historyRouter.ts` → `NavigationBar` + `IndexedStack` + native back stack
- Drag-drop → `file_picker`
- Leaflet → `flutter_map`
- SSE `EventSource` → `http` polling (stub ready)
- 5 tabs: Overview / Ask ORCA / Map / Authority / System (web has 4 console views; Map is own tab on mobile for thumb reach)

## Tech Stack

- Flutter 3.47.2 (stable), Android first, iOS-compatible, Chrome web phone-frame for desktop demo
- State: `Provider` (`ChangeNotifier`)
- HTTP: `http` (with `X-API-Key` support)
- Storage: `shared_preferences`
- GPS: `geolocator` + `permission_handler`
- Voice: `speech_to_text` (STT) + `flutter_tts` (TTS)
- Map: `flutter_map` + `latlong2`
- Charts: `fl_chart`
- Markdown: `flutter_markdown`
- Picker: `file_picker`
- ID: `uuid`

## Project Structure

```
lib/
  main.dart                 — entry, Provider(Storage+Api+Tts → AppState), _WebPhoneFrame, MainShell (5 tabs, Header, Drawer, Toast)
  config/api_config.dart    — defaultBaseUrl, deployedBaseUrl, timeouts
  models/
    query_response.dart     — QueryResponse (25+ fields: trace, discussion, ocean_state, risk, timings, routing, fleet, wind, evidence_tiers)
    alert.dart              — OrcaAlert (severity/title/message variants)
    chat.dart               — Chat
    user_category.dart      — USER_CATEGORIES (6 roles)
  services/
    api_service.dart        — all HTTP: /query, /query/voice (audio), /health, /agents, /viz/*, /api/pfz/live, /fleet/*, /satellite-wind/*, /sar/*, /users/*, /alerts/*, subscribeAlertsSSE()
    storage_service.dart    — SharedPreferences wrapper (baseUrl, apiKey, language, vesselClass, userId, chatHistory, queryMode, fleet/wind demo, sendOnEnter, audioFeedback)
    tts_service.dart        — flutter_tts with LANG_TAGS (en-IN, hi-IN, etc.)
  state/app_state.dart      — ChangeNotifier: chats/messages/activeChatId, executionSteps, vizGeojson/Series, queryMode/directAgentKey, backendAgents, backendOnline, gps/mapPoint, userCategory, auth mock, guest limit, toast, fleet/wind demo, shared prefs persistence
  screens/
    home_screen.dart        — Overview: header, location, safety status, SafetyHud, VizChart, scenario grid, quick chips, alerts preview
    chat_screen.dart        — Chat: markdown bubbles, _Composer (routing pill, file picker, voice, stop), _EmptyState starters, AgentActivityStrip, _AgentSheet
    map_screen.dart         — flutter_map: OSM + markers/polylines from viz, tap mapPoint, PFZ toggle, SafetyHud + VizChart below
    sar_screen.dart         — Authority: SAR status, demo scan, detections list
    alerts_screen.dart      — Alerts list (polling) + register
    settings_screen.dart    — System: console tabs, role switch, en/mr/hi, sendOnEnter/audioFeedback switches (wired), fleet/wind chips, backend URL, auth mock, reset
  widgets/
    chat_bubble.dart        — markdown + verdict HUD (exact-match), fleet/wind cards, reasoning expand, TTS listen/copy/regen chips, answered_by
    verdict_badge.dart      — SAFE/CAUTION/UNSAFE/EXTREME badge
    alert_tile.dart         — severity-colored alert card
    preset_query_button.dart— cyan chip
    offline_banner.dart     — offline bar
    app_header.dart         — AppBar (title, queryModeLabel, offline badge)
    chat_drawer.dart        — Drawer: history, search, new/pin/rename/delete, guest/auth footer
    toast_overlay.dart      — Stack toast (auto-dismiss 3s)
    agent_activity.dart     — AgentActivityStrip
    safety_hud.dart         — 6-factor HUD
    viz_chart.dart          — fl_chart line + threshold + tide chips
  l10n/strings.dart         — UI strings (10 locales, web baseline en/mr/hi)
```

## Deliverables

- `MOBILE_AUDIT.md` — Phase 1 backend connectivity (8 endpoints verified live) + Phase 2 feature parity matrix (29 features, fully Ported/Adapted) + intentional adaptations + remaining gaps (none, polish only).
- This Flutter project (full parity, `flutter analyze` clean).
- Updated `README.md` (this file) — full-parity scope, backend URL wiring.

## Known Polish (not gaps)

- INCOIS WMS layers (SST/WW3/ERDDAP) — base OSM only; wire `TileLayer.wmsOptions` when tile URLs exposed.
- SSE foreground service — polling works; upgrade to `eventsource`.
- Firebase real wiring — mock covers UI; add `google-services.json` for prod.
- Offline tile cache — add `flutter_map_tile_caching` for at-sea use.
