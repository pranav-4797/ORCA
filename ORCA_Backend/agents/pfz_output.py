"""
User-facing formatting for the official INCOIS / SAMUDRA PFZ finding.

Shared by the Response Agent (LLM path) and the Orchestrator's fast
deterministic path so every official-PFZ answer renders the SAME exact
template regardless of routing depth. Only wordsmithing lives here --
all numbers come directly from the PFZRecommendation the agent produced
(NO fabrication, no LLM in this module).

Only official advisories (DataSource.INCOIS_LIVE) get this template. The
derived/simulated fallbacks keep the existing honest concision.
"""

from __future__ import annotations

OFFICIAL_SOURCE = "Official INCOIS Marine Fisheries (SAMUDRA) live advisory"

# 8-point compass rose with spoken names (225 deg -> "South-West").
_COMPASS = [
    "North", "North-East", "East", "South-East",
    "South", "South-West", "West", "North-West",
]

_VERDICT_BRIEF = {
    "SAFE": "Conditions are favourable for fishing.",
    "CAUTION": "Borderline conditions; proceed carefully.",
    "UNSAFE": "Unsafe conditions; avoid venturing out.",
    "EXTREME": "Severe conditions; do not venture out.",
    "CRITICAL": "Severe conditions; do not venture out.",
}

# Keywords mirroring orchestrator/planning.py PFZ_LOOKUP routing so the
# exact-template answer is only used when the user actually asked where
# the fish are (never hijacks a safety-check answer).
_PFZ_LOOKUP_KEYWORDS = (
    "fishing zone", "fish zone", "fish zones", "pfz",
    "where to fish", "where can i fish", "nearest fishing",
    "fishing spot", "fishing grounds", "where are the fish",
)


def is_pfz_lookup_query(raw_query: str) -> bool:
    """True when the user's question is asking for a fishing zone."""
    q = (raw_query or "").lower()
    return any(k in q for k in _PFZ_LOOKUP_KEYWORDS)


def bearing_word(deg: float) -> str:
    """225.0 -> 'South-West'."""
    if deg is None:
        return "North"
    return _COMPASS[int((float(deg) % 360) / 45) % 8]


def verdict_brief(verdict: str | None) -> str:
    return _VERDICT_BRIEF.get(
        str(verdict or "").upper(), "Borderline conditions; proceed carefully."
    )


def format_pfz_answer(pfz, verdict: str | None = "CAUTION") -> str | None:
    """Official INCOIS PFZ answer in the documented format.

    Returns None when the finding is a derived/simulated fallback so callers
    keep their honest wording.
    """
    if pfz is None:
        return None
    source = getattr(pfz, "source", None)
    if getattr(source, "value", source) != "incois_live":
        return None

    dist_km = float(getattr(pfz, "distance_from_reference_km", 0.0))
    bearing = float(getattr(pfz, "bearing_deg", 0.0))
    lat = float(getattr(pfz, "center_lat", 0.0))
    lon = float(getattr(pfz, "center_lon", 0.0))
    lc = getattr(pfz, "landing_center", None) or {}
    depth = lc.get("advisory_depth_m")
    try:
        depth_txt = f"{float(depth):g} m"
    except (TypeError, ValueError):
        depth_txt = f"{depth} m" if depth is not None else "not reported in feed"

    verdict_txt = str(verdict or "CAUTION").upper()
    lat_s, lon_s = ("N", "E") if (lat, lon) else ("N", "E")
    if lat < 0:
        lat_s = "S"
    if lon < 0:
        lon_s = "W"

    return (
        "🛡️ IMPORTANT\n\n"
        f"🔶 VERDICT: {verdict_txt} — {verdict_brief(verdict_txt)}\n\n"
        f"The nearest official INCOIS Potential Fishing Zone (PFZ) is approximately "
        f"{dist_km:.1f} km from your current location, on a "
        f"{bearing:.0f}° ({bearing_word(bearing)}) bearing.\n\n"
        "🎯 Target Coordinates\n\n"
        f"* Latitude: {abs(lat):.4f}° {lat_s}\n"
        f"* Longitude: {abs(lon):.4f}° {lon_s}\n\n"
        "📋 Quick Summary\n\n"
        f"* 📍 Distance from you: {dist_km:.1f} km\n"
        f"* 🧭 Direction: {bearing_word(bearing)} ({bearing:.0f}°)\n"
        f"* 🌊 Water depth: {depth_txt}\n"
        f"* 📡 Source: {OFFICIAL_SOURCE}\n\n"
        "This recommendation is based on the latest official PFZ data available "
        "from INCOIS."
    )