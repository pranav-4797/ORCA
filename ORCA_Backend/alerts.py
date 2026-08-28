"""
Alert bus -- in-memory store of proactive alerts per user/session plus a
simple pub-sub used by the SSE stream endpoint.

The Proactive Monitor Agent pushes alerts here; the API layer serves them
(GET /alerts/{user_id} poll or GET /alerts/stream/{user_id} SSE).

Design: process-local (single uvicorn worker for the demo). For multi-worker
production swap internals for Redis pub/sub -- callers don't change.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Alert:
    user_id: str
    kind: str                 # "hazard" | "geofence" | "info"
    severity: str             # "UNSAFE" | "CAUTION" | "INFO"
    title: str
    message: str              # already composed in the user's language
    language: str = "en"
    created_at: float = field(default_factory=time.time)
    delivered_sms: bool = False
    sms_error: str = ""

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "language": self.language,
            "created_at": self.created_at,
            "delivered_sms": self.delivered_sms,
        }


_MAX_PER_USER = 50

_lock = threading.Lock()
_alerts: dict[str, deque] = {}
_subscribers: dict[str, list[asyncio.Queue]] = {}


def publish(alert: Alert) -> None:
    """Store an alert and wake any waiting SSE subscribers."""
    with _lock:
        _alerts.setdefault(alert.user_id, deque(maxlen=_MAX_PER_USER)).append(alert)
        queues = list(_subscribers.get(alert.user_id, []))
    for q in queues:
        try:
            q.put_nowait(alert)
        except Exception:
            pass


def fetch(user_id: str, since_ts: float = 0.0) -> list[Alert]:
    with _lock:
        return [a for a in _alerts.get(user_id, ()) if a.created_at > since_ts]


def subscribe(user_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    with _lock:
        _subscribers.setdefault(user_id, []).append(q)
    return q


def unsubscribe(user_id: str, q: asyncio.Queue) -> None:
    with _lock:
        subs = _subscribers.get(user_id, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            _subscribers.pop(user_id, None)


# ---------------------------------------------------------------------------
# Twilio SMS -- life-safety delivery channel (PDF Sec. 12/15.2). Uses
# Twilio's REST endpoint directly via urllib so no extra dependency is
# needed. Disabled honestly when credentials are absent.
#
# India note: production SMS to Indian numbers requires TRAI DLT
# registration; the demo path is Twilio trial mode with pre-verified
# recipients (see project documentation Sec. 19).
# ---------------------------------------------------------------------------

def send_sms(to_number: str, message: str) -> tuple[bool, str]:
    """Returns (sent_ok, sid_or_error). No-ops (False, 'sms_disabled') when
    TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER are unset."""
    import base64
    import os
    import urllib.parse
    import urllib.request

    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    if not (sid and token and from_number):
        return False, "sms_disabled"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    body = urllib.parse.urlencode({
        "To": to_number,
        "From": from_number,
        "Body": message[:1500],
    }).encode()
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
            return True, payload.get("sid", "")
    except Exception as exc:
        return False, str(exc)[:300]


def sms_enabled() -> bool:
    import os
    return bool(os.getenv("TWILIO_ACCOUNT_SID", "").strip()
                and os.getenv("TWILIO_AUTH_TOKEN", "").strip()
                and os.getenv("TWILIO_FROM_NUMBER", "").strip())
