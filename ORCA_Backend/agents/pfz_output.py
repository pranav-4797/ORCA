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


def format_pfz_answer(pfz, verdict: str | None = "CAUTION", narrative: str | None = None) -> str | None:
    """PFZ answer in the documented format — official when INCOIS_LIVE, estimated otherwise.

    Returns a formatted answer for any PFZ (official, derived, simulated) with honest
    source tagging, so the user always sees Target Coordinates. Only wordsmithing
    lives here — all numbers come directly from the PFZRecommendation.

    ``narrative`` — optional LLM-generated, query-specific opening paragraph. When
    provided it REPLACES the deterministic ``intro`` sentence so the top of the
    answer reads conversationally (spec Parts B/C). The structured cards, target
    coordinates, quick-summary and source line are always preserved unchanged.
    """
    if pfz is None:
        return None
    source = getattr(pfz, "source", None)
    src_val = getattr(source, "value", source) if source else "unknown"
    is_official = src_val == "incois_live"

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

    # Nearest landmark (reverse-geocoded, zoom=14) — friendlier than raw lat/lon alone
    # If reverse is too generic (e.g. "India" for 35km offshore), fallback to the
    # advisory's landing centre (nearest port) — far more useful to a fisher.
    landmark = getattr(pfz, "nearest_landmark", None)
    _generic_landmarks = {"india", "arabian sea", "indian ocean", "bay of bengal", "laccadive sea", "sea"}
    is_generic = isinstance(landmark, str) and landmark.strip().lower() in _generic_landmarks
    if is_generic:
        landmark = None
    if not landmark:
        # Fallback: nearest INCOIS landing centre for this PFZ (the port the advisory is issued for)
        lc_fb = lc or {}
        fb_name = (lc_fb.get("name") or "").strip()
        fb_state = (lc_fb.get("state") or "").strip()
        if fb_name and fb_name.lower() not in ("unknown", "null"):
            if fb_state:
                landmark = f"{fb_name}, {fb_state}"
            else:
                landmark = fb_name
        else:
            # Last resort: reference location (e.g. "Kochi Coast") — still better than "India"
            ref_name = getattr(getattr(pfz, "reference_location", None), "name", None)
            if ref_name and ref_name.lower() not in ("unknown coast (default demo point)", "unknown"):
                # Shorten "Kochi Coast" -> "Kochi"
                short = ref_name.replace(" Coast", "").strip()
                landmark = short
            else:
                landmark = None
    landmark_line = ""
    landmark_summary = ""
    if landmark:
        # Format as "≈15.2 km off Alibaug, Maharashtra" — distance already known
        landmark_line = f"* 📍 Nearest landmark: ≈{dist_km:.1f} km off {landmark}\n"
        landmark_summary = f"* 📍 Nearest landmark: ≈{dist_km:.1f} km off {landmark}\n"
        landmark_sentence = f" near {landmark}"
    else:
        landmark_sentence = ""

    if is_official:
        source_line = f"* 📡 Source: {OFFICIAL_SOURCE}\n\nThis recommendation is based on the latest official PFZ data available from INCOIS."
        intro = f"The nearest official INCOIS Potential Fishing Zone (PFZ) is approximately {dist_km:.1f} km from your current location, on a {bearing:.0f}° ({bearing_word(bearing)}) bearing{landmark_sentence}."
    else:
        src_txt = "Derived from live SST front" if src_val == "derived_from_live_data" else "Simulated estimate"
        source_line = f"* 📡 Source: {src_txt} — no official INCOIS advisory issued within 150 km of your location today (honest fallback).\n\nThis is an estimated zone based on live sea-surface data, not an official advisiory. Use with caution and check local conditions."
        intro = f"The nearest estimated Potential Fishing Zone (PFZ) is approximately {dist_km:.1f} km from your current location, on a {bearing:.0f}° ({bearing_word(bearing)}) bearing{landmark_sentence}."
    # LLM-generated conversational narrative REPLACES the templated intro when available.
    if narrative and narrative.strip():
        intro = narrative.strip()
    return (
        "🛡️ IMPORTANT\n\n"
        f"🔶 VERDICT: {verdict_txt} — {verdict_brief(verdict_txt)}\n\n"
        f"{intro}\n\n"
        "🎯 Target Coordinates\n\n"
        f"{landmark_line}"
        f"* Latitude: {abs(lat):.4f}° {lat_s}\n"
        f"* Longitude: {abs(lon):.4f}° {lon_s}\n\n"
        "📋 Quick Summary\n\n"
        f"{landmark_summary}"
        f"* 📍 Distance from you: {dist_km:.1f} km\n"
        f"* 🧭 Direction: {bearing_word(bearing)} ({bearing:.0f}°)\n"
        f"* 🌊 Water depth: {depth_txt}\n"
        f"{source_line}"
    )