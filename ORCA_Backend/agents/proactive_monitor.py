"""
Proactive Monitor Agent (PS component #10).

The only ORCA component that is NOT query-triggered: an independent
asyncio timer loop that, for every registered user's saved location,
re-polls the Hazard and Geospatial agents and pushes an alert into the
alert bus (chat SSE + optional Twilio SMS) WITHOUT anyone asking --
exactly the PDF Sec. 6/15.2 design.

Dedup: each user keeps a signature of the hazards last reported. An alert
fires only when a NEW hazard flag appears, severity escalates, or the
vessel crosses into the geofence approach buffer -- so a user whose seas
stay rough is not spammed every poll.

Reuse: this is NOT a re-implementation. It calls the same OceanStateAgent,
HazardAgent and GeospatialAgent.run() used by the query pipeline, so a
proactive warning is backed by identical live data and thresholds.
"""

from __future__ import annotations

import asyncio
import logging
import time

import alerts as alert_bus
from models import Location

logger = logging.getLogger("orca.monitor")

DEFAULT_POLL_SECONDS = 900  # 15 min; PDF Sec. 15.2 "timer loop"

# Users registry: in-process demo store.
# {user_id: {"phone", "name", "lat", "lon", "location_name", "language",
#            "sms_critical_only"}}
_users: dict[str, dict] = {}
_user_lock = asyncio.Lock()


def list_users() -> list[dict]:
    return [{**u, "user_id": uid} for uid, u in _users.items()]


async def register_user(user_id: str, lat: float, lon: float,
                        name: str = "", phone: str = "",
                        location_name: str = "", language: str = "en",
                        sms_critical_only: bool = True) -> dict:
    async with _user_lock:
        entry = {
            "name": name or user_id,
            "phone": phone,
            "lat": float(lat),
            "lon": float(lon),
            "location_name": location_name or f"{lat:.2f}, {lon:.2f}",
            "language": language or "en",
            "sms_critical_only": bool(sms_critical_only),
            "registered_at": time.time(),
        }
        _users[user_id] = entry
        return {**entry, "user_id": user_id}


async def unregister_user(user_id: str) -> bool:
    async with _user_lock:
        return _users.pop(user_id, None) is not None


def update_position(user_id: str, lat: float, lon: float,
                    location_name: str = "") -> bool:
    """Live vessel position update (device GPS heartbeat)."""
    if user_id not in _users:
        return False
    _users[user_id]["lat"] = float(lat)
    _users[user_id]["lon"] = float(lon)
    if location_name:
        _users[user_id]["location_name"] = location_name
    return True


class ProactiveMonitorAgent:
    """Timer-driven watcher over every registered user's waters."""

    name = "ProactiveMonitorAgent"

    def __init__(self, poll_seconds: int = DEFAULT_POLL_SECONDS):
        self.poll_seconds = max(60, int(poll_seconds))
        self._signatures: dict[str, str] = {}     # user_id -> last hazard sig
        self._task: asyncio.Task | None = None
        # Imported lazily to avoid circulars at module load.
        from agents.geospatial_agent import GeospatialAgent
        from agents.hazard_agent import HazardAgent
        from agents.ocean_state_agent import OceanStateAgent
        self._ocean = OceanStateAgent()
        self._hazard = HazardAgent()
        self._geo = GeospatialAgent()

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._loop())
            logger.info("Proactive Monitor started (poll=%ss)", self.poll_seconds)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def check_now(self, user_id: str) -> list[alert_bus.Alert]:
        """One immediate evaluation for one user (used by tests/registration).
        Returns alerts actually pushed (may be empty when nothing new)."""
        user = _users.get(user_id)
        if user is None:
            return []
        pushed = await self._evaluate_user(user_id, user)
        return [a for a in pushed]

    # ------------------------------------------------------------------
    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.poll_seconds)
                users = list(_users.items())
                for user_id, user in users:
                    try:
                        await self._evaluate_user(user_id, user)
                    except Exception as exc:
                        logger.warning("monitor pass failed for %s: %s",
                                       user_id, exc)
                    await asyncio.sleep(2)  # gentle pacing between users
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("monitor loop error: %s", exc)

    # ------------------------------------------------------------------
    async def _evaluate_user(self, user_id: str, user: dict) -> list:
        loc = Location(name=user["location_name"], lat=user["lat"], lon=user["lon"])
        reading, _trace_o = await asyncio.to_thread(
            self._ocean.run, loc, "today"
        )
        risk, _trace_h = await asyncio.to_thread(self._hazard.run, reading)
        geofence = await asyncio.to_thread(
            self._geo.check_geofence_public, user["lat"], user["lon"], loc
        )

        # ---- dedup signature: which hazards are active right now ----
        parts: list[str] = [f"status={risk.status.value}"]
        for f in risk.flags:
            parts.append(f.label)
        if not geofence.clear:
            nearest = min(geofence.hits, key=lambda h: h.distance_to_boundary_km)
            parts.append(f"geofence:{nearest.zone_name}:{'in' if nearest.inside_zone else 'near'}")
        signature = "|".join(parts)

        prev = self._signatures.get(user_id)
        new_items = set(parts) - set((prev or "").split("|"))
        self._signatures[user_id] = signature
        if prev == signature:
            return []                      # nothing changed -- no spam
        if prev is None and risk.status.value != "UNSAFE" and geofence.clear:
            return []                      # first clean baseline -- stay quiet
        if not new_items and prev is not None and \
                risk.status.value != "UNSAFE":
            return []

        # ---- compose alert in the user's language ----
        title, message = await self._compose(loc, risk, geofence, user["language"])

        critical = risk.status.value == "UNSAFE" or not geofence.clear
        sms_ok, sms_info = False, ""
        if critical and user.get("phone"):
            if not user.get("sms_critical_only") or risk.status.value == "UNSAFE":
                sms_ok, sms_info = alert_bus.send_sms(user["phone"], message[:1500])

        alert = alert_bus.Alert(
            user_id=user_id,
            kind="geofence" if not geofence.clear else "hazard",
            severity=risk.status.value if critical else "INFO",
            title=title,
            message=message,
            language=user["language"],
            delivered_sms=sms_ok,
            sms_error=sms_info if not sms_ok else "",
        )
        alert_bus.publish(alert)
        return [alert]

    # ------------------------------------------------------------------
    async def _compose(self, loc: Location, risk, geofence, language: str):
        flags_text = "; ".join(
            f"{f.label}: {f.detail} ({f.threshold_crossed})" for f in risk.flags
        ) or "no threshold crossed"
        geo_line = ""
        if not geofence.clear:
            near = min(geofence.hits, key=lambda h: h.distance_to_boundary_km)
            state = "INSIDE" if near.inside_zone else f"{near.distance_to_boundary_km} km from"
            geo_line = f" Boundary proximity: you are {state} {near.zone_name}."
        title = ("UNSAFE conditions" if risk.status.value == "UNSAFE"
                 else "Boundary proximity alert" if geo_line else "Conditions updated")

        facts = (
            f"Location: {loc.name}. Overall verdict: {risk.status.value}. "
            f"Hazard findings: {flags_text}.{geo_line} "
            f"Write a short urgent safety ALERT of 2-3 sentences."
        )

        lang_names = {
            "en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil",
            "te": "Telugu", "bn": "Bengali", "ml": "Malayalam", "kn": "Kannada",
            "gu": "Gujarati", "or": "Odia", "pa": "Punjabi",
        }
        try:
            import llm_client
            msg = llm_client.complete(
                system_prompt=(
                    "You are ORCA's Proactive Safety Monitor pushing an "
                    "UNPROMPTED alert to a fisherman's phone/chat. Use ONLY "
                    f"the provided facts. Write in {lang_names.get(language, language)}. "
                    "No agent names. Start with the most urgent fact."
                ),
                user_prompt=facts,
                temperature=0.3,
                max_tokens=300,
            )
            return title, msg
        except Exception:
            base = f"[Alert] {loc.name}: verdict {risk.status.value}. {flags_text}.{geo_line}"
            return "Safety alert", base
