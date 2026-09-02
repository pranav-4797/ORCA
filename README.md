# ORCA fixes — this session

Four files changed. Drop each one into the matching path in your repo
(overwriting the existing file), or apply `CHANGES.diff` with `git apply`
from your repo root.

| File in this folder      | Goes to                                                  |
|---------------------------|-----------------------------------------------------------|
| `pfz_agent.py`             | `ORCA_Backend/agents/pfz_agent.py`                        |
| `response_agent.py`        | `ORCA_Backend/agents/response_agent.py`                   |
| `orchestrator__init__.py`  | `ORCA_Backend/orchestrator/__init__.py`                   |
| `OceanMap.ts`               | `ORCA UI/src/components/map/OceanMap.ts`                 |

## 1. PFZ map lines not showing (`OceanMap.ts`)

The "skip re-render" shortcut only compared the *data* (geojson + PFZ
token), never whether a render had actually happened. If the map's canvas
wasn't mounted yet the first time PFZ data loaded, the map silently stayed
empty forever after — even once it became visible — because the shortcut
thought "nothing changed" and skipped drawing. Fixed by also requiring
`this.map` to exist and already have layers before taking the shortcut.

## 2. SST/weather queries always "simulated" (`orchestrator/__init__.py`)

`ORCA_OCEAN_FUTURE_TIMEOUT_S` (the orchestrator's hard cutoff for the whole
ocean-state fetch) defaulted to **22s**, but the INCOIS connector's own
worst-case retry chain (3 dates × 2 time formats × 8s timeout, per field)
can take up to **48s**. Any time INCOIS was slow rather than fully down,
the orchestrator gave up first and served the simulated fallback. Bumped
the default to **30s**. Turn on `ORCA_DEBUG_INCOIS=true` to see exactly
which field is slow/failing if you want to tune further.

## 3. Mumbai → Andhra Pradesh PFZ bug (`pfz_agent.py`)

The existing `_MAX_CENTRE_DIST_KM = 150` safety cap only validated the
*landing centre's* distance. The coordinates actually shown to the user
come from a separate step, `_nearest_point_on_lines()`, which scans
**every PFZ line segment in the entire nationwide INCOIS dataset** with no
distance cap and no state filter — bypassing the 150 km check entirely.
That's how a query near Mumbai could surface a point near Andhra Pradesh
while still reporting a small, misleading distance. Fixed by applying the
same cap to that result; if it fails, the code falls back to the
already-capped landing-centre advisory position instead. Added logging
(resolved location / advisory region / selected PFZ) so any future
occurrence is diagnosable from the logs.

## 4. PFZ answers were template-only, never AI-narrated (`response_agent.py` + `orchestrator/__init__.py`)

`generate_context_summary()` already supported PFZ data, but two separate
code paths — the fast/deterministic orchestrator path and
`ResponseAgent.run()` — returned the structured PFZ template immediately,
before ever reaching the summary call. Added a shared `_pfz_narrative()`
helper and wired it into both paths, so PFZ answers now get a
query-specific AI opening line prepended above the **unchanged** structured
template (cards, coordinates, scores, source chip all stay exactly as they
were).

## Verified

- All three backend files: `python3 -m py_compile` clean, `pyflakes` shows
  no new warnings (only pre-existing ones untouched by this change).
- `OceanMap.ts`: full `tsc --noEmit` on the whole frontend passes clean.
- Not verified against your live INCOIS feed or a live LLM call — my
  sandbox can't reach `gemini.incois.gov.in` or your Groq key. Please
  smoke-test the Mumbai query and a PFZ query after deploying.
