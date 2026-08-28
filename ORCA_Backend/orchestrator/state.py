"""State and constants for orchestrator — Task 10 split."""
from __future__ import annotations

import operator
import os
from typing import Annotated, List, Optional, TypedDict

from models import (
    AgentTrace,
    DataSource,
    GeofenceStatus,
    Location,
    OrchestratorResponse,
    PFZRecommendation,
    QueryContext,
    RiskAssessment,
    RoutePlan,
    SafetyStatus,
)

# Query depth policy: auto | fast | standard | deep (env-overridable)
QUERY_DEPTH = os.getenv("ORCA_QUERY_DEPTH", "auto").strip().lower() or "auto"
# TTLs (env-overridable) — short for live safety, longer for geocoding
OCEAN_TTL_S = int(os.getenv("ORCA_OCEAN_TTL_S", "120").strip() or 120)
RESPONSE_CACHE_TTL_S = int(os.getenv("ORCA_RESPONSE_CACHE_TTL_S", "60").strip() or 60)
GEOCODE_TTL_S = int(os.getenv("ORCA_GEOCODE_TTL_S", "86400").strip() or 86400)

try:
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover - defensive, keeps the demo alive
    LANGGRAPH_AVAILABLE = False

# Pre-seeded coordinate cache
KNOWN_LOCATIONS = {
    "ratnagiri": Location(name="Ratnagiri Coast", lat=16.9902, lon=73.3120),
    "kochi": Location(name="Kochi Coast", lat=9.9312, lon=76.2673),
    "visakhapatnam": Location(name="Visakhapatnam Coast", lat=17.6868, lon=83.2185),
    "odisha": Location(name="Odisha Coast (Puri)", lat=19.8135, lon=85.8312),
}
DEFAULT_LOCATION = Location(name="Unknown Coast (default demo point)", lat=15.5, lon=73.8)

_geocode_cache: dict[str, Location] = {}

# Degraded-mode messages
_DEGRADED_MESSAGES: dict[str, str] = {
    "en": "Service is running in limited mode right now, please try again shortly or ask in English.",
    "hi": "सेवा फिलहाल सीमित मोड में चल रही है। कृपया थोड़ी देर बाद पुनः प्रयास करें या अंग्रेज़ी में पूछें।",
    "mr": "सेवा सध्या मर्यादित मोडमध्ये चालू आहे. कृपया थोड्या वेळाने पुन्हा प्रयत्न करा किंवा इंग्रजीत विचारा.",
    "ta": "சேவை தற்போது வரையறுக்கப்பட்ட முறையில் இயங்குகிறது. சிறிது நேரம் கழித்து மீண்டும் முயற்சிக்கவும் அல்லது ஆங்கிலத்தில் கேட்கவும்.",
    "te": "సేవ ప్రస్తుతం పరిమిత మోడ్‌లో నడుస్తోంది. దయచేసి కొద్దిసేపటి తర్వాత మళ్లీ ప్రయత్నించండి లేదా ఆంగ్లంలో అడగండి.",
    "bn": "পরিষেবাটি বর্তমানে সীমিত মোডে চলছে। অনুগ্রহ করে কিছুক্ষণ পরে আবার চেষ্টা করুন বা ইংরেজিতে জিজ্ঞাসা করুন।",
    "ml": "സേവനം ഇപ്പോൾ പരിമിത മോഡിൽ പ്രവർത്തിക്കുന്നു. ദയവായി കുറച്ച് സമയത്തിന് ശേഷം വീണ്ടും ശ്രമിക്കുക അല്ലെങ്കിൽ ഇംഗ്ലീഷിൽ ചോദിക്കുക.",
    "kn": "ಸೇವೆ ಪ್ರಸ್ತುತ ಸೀಮಿತ ಮೋಡ್‌ನಲ್ಲಿ ಕಾರ್ಯನಿರ್ವಹಿಸುತ್ತಿದೆ. ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ ಅಥವಾ ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಕೇಳಿ.",
    "gu": "સેવા હાલમાં મર્યાદિત મોડમાં ચાલી રહી છે. કૃપા કરીને થોડા સમય પછી ફરી પ્રયાસ કરો અથવા અંગ્રેજીમાં પૂછો.",
    "or": "ସେବା ବର୍ତ୍ତମାନ ସୀମିତ ମୋଡରେ ଚାଲୁଛି। ଦୟାକରି କିଛି ସମୟ ପରେ ପୁନର୍ବାର ଚେଷ୍ଟା କରନ୍ତୁ କିମ୍ବା ଇଂରାଜୀରେ ପଚାରନ୍ତୁ।",
    "pa": "ਸੇਵਾ ਇਸ ਵੇਲੇ ਸੀਮਤ ਮੋਡ ਵਿੱਚ ਚੱਲ ਰਹੀ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਥੋੜ੍ਹੀ ਦੇਰ ਬਾਅਦ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ ਜਾਂ ਅੰਗਰੇਜ਼ੀ ਵਿੱਚ ਪੁੱਛੋ।",
}

def _degraded_message_for(lang: str) -> str:
    return _DEGRADED_MESSAGES.get(lang, _DEGRADED_MESSAGES["en"])

def _contains_indic_script(text: str) -> bool:
    for ch in text or "":
        cp = ord(ch)
        if 0x0900 <= cp <= 0x0D7F:
            return True
        if 0x0A00 <= cp <= 0x0AFF or 0x0B00 <= cp <= 0x0BFF or 0x0C00 <= cp <= 0x0CFF:
            return True
    return False

# Romanized (Latin-script) regional language keywords — Task 2 extension
# 10-15 distinctive transliterated words per language, NOT English overlap.
# These are used only when LLM is unavailable to catch queries like
# "kal subah machli pakadna safe hai kya" which is ASCII but Hindi.

ROMANIZED_KEYWORDS: dict[str, list[str]] = {
    # Hindi (hi) — Devanagari romanized
    "hi": [
        "surakshit", "suraksha", "machli", "machhli", "machhara", "samundar",
        "samundra", "toofan", "khatra", "chetavni", "leher", "hawa",
        "kinara", "mausam", "jaal", "machuara",
    ],
    # Marathi (mr)
    "mr": [
        "surakshit", "maasa", "samudra", "vadal", "dhoka", "ishara",
        "lahari", "vaara", "kinara", "maasaemari", "hawaman", "kolivada",
        "maase", "dhokadayak",
    ],
    # Tamil (ta)
    "ta": [
        "paadukappu", "meen", "kadal", "apayam", "echcharikkai", "alai",
        "kaatru", "karai", "meenpidippu", "vaanilai", "puyal", "suzhal",
        "meenpidippa", "kadalora",
    ],
    # Telugu (te)
    "te": [
        "bhadrata", "chepa", "samudram", "pramadam", "hechcharika", "alalu",
        "gali", "teeram", "chepala", "vaatavaranam", "toofan", "chakravatam",
        "samudra", "chepalu",
    ],
    # Bengali (bn)
    "bn": [
        "nirapad", "machh", "samudra", "bipad", "satarkata", "dheu",
        "hawa", "upakul", "jal", "abhawa", "jhor", "ghurnijhar",
        "machher", "samudre",
    ],
    # Malayalam (ml)
    "ml": [
        "suraksha", "meen", "kadal", "apakadam", "munnaicharika", "thira",
        "kaattu", "karavan", "meenpiditham", "kalavastha", "kottumkaatu",
        "chakravatam", "kadalora", "meenukal",
    ],
    # Kannada (kn)
    "kn": [
        "suraksha", "meenu", "samudra", "apaya", "hechcharike", "ale",
        "gaali", "karavali", "meenugarike", "havamana", "bharane", "chakravata",
        "samudrada", "meenugalu",
    ],
    # Gujarati (gu)
    "gu": [
        "surakshit", "machhli", "samudra", "khatro", "chetavni", "lahari",
        "hawa", "kinaro", "machhimari", "havaman", "vavazodu", "chakravat",
        "dariyo", "machhal",
    ],
    # Odia (or) — romanized
    "or": [
        "suraksha", "machha", "samudra", "bipad", "satarka", "dheu",
        "pabana", "kula", "jal", "panipaga", "jhada", "batya",
        "samudrakula", "macha",
    ],
    # Punjabi (pa)
    "pa": [
        "surakhia", "machhi", "samundar", "khatra", "chetavni", "lehar",
        "hawa", "kinara", "machhi", "mausam", "toofan", "chakravat",
        "jal", "samundra",
    ],
}

# Flatten for quick check and map lowercased word -> language
_ROMANIZED_WORD_TO_LANG: dict[str, str] = {}
for _lang, _words in ROMANIZED_KEYWORDS.items():
    for _w in _words:
        _lw = _w.lower()
        # Keep first language for duplicate words like "surakshit" (hi/mr/gu) -> hi
        if _lw not in _ROMANIZED_WORD_TO_LANG:
            _ROMANIZED_WORD_TO_LANG[_lw] = _lang

def _contains_romanized_regional_language(text: str) -> bool:
    """
    True if text contains any romanized regional keyword as a whole word.
    Case-insensitive, word-boundary aware, Latin-script only.
    Does not flag English queries because list contains no English words
    like 'safe', 'cyclone', 'fish', etc. — only transliterated forms.
    """
    if not text or not text.strip():
        return False
    # Quick ASCII check — romanized is ASCII, but we still need to scan
    low = text.lower()
    # Split into words by non-alphabetic to handle punctuation
    import re
    words = set(re.findall(r"[a-zA-Z]+", low))
    # Also check multi-word phrases like "machli pakadna" — we split those into individual words already,
    # but some keywords are multi-word? In our list, most are single words; a few are phrases like "machhi fadhna" not present.
    # For now, check single-word hits; also check substring with word boundaries for robustness
    for w in words:
        if w in _ROMANIZED_WORD_TO_LANG:
            return True
    # Additional: check if any keyword appears as substring with word boundaries (for hyphenated etc.)
    for kw in _ROMANIZED_WORD_TO_LANG:
        # Use word boundary regex for each kw
        if re.search(r"\b" + re.escape(kw) + r"\b", low):
            return True
    return False

def _detect_romanized_language(text: str) -> str | None:
    """Return language code for first romanized keyword found, else None."""
    if not text:
        return None
    low = text.lower()
    import re
    words = re.findall(r"[a-zA-Z]+", low)
    for w in words:
        if w in _ROMANIZED_WORD_TO_LANG:
            return _ROMANIZED_WORD_TO_LANG[w]
    for kw, lang in _ROMANIZED_WORD_TO_LANG.items():
        if re.search(r"\b" + re.escape(kw) + r"\b", low):
            return lang
    return None

def resolve_location(place_name: str) -> Location:
    key = " ".join((place_name or "").strip().lower().split())
    if key in KNOWN_LOCATIONS:
        return KNOWN_LOCATIONS[key]
    if key in _geocode_cache:
        return _geocode_cache[key]
    if key and key != "unknown":
        try:
            import data_connectors.geocode as geocode
            hit = geocode.geocode(key)
        except Exception as exc:
            import logging
            logging.getLogger("orca.orchestrator").warning(
                "geocoding '%s' failed (%s); using default location",
                place_name, exc,
            )
            return DEFAULT_LOCATION
        if hit:
            lat, lon, display = hit
            loc = Location(name=display.split(",")[0].strip() + " Coast", lat=lat, lon=lon)
            _geocode_cache[key] = loc
            return loc
    return DEFAULT_LOCATION

KNOWN_TIME_WINDOWS = ["today", "tomorrow", "tomorrow_morning"]

SPECIALIST_REGISTRY = {
    "ocean_state": {
        "name": "Ocean-State Agent",
        "description": (
            "Live SST, wave height, wind and gusts, harmonic tides and "
            "chlorophyll for any Indian coastal point"
        ),
        "requires": [],
    },
    "hazard": {
        "name": "Hazard Agent",
        "description": (
            "Threshold-based safety verdicts plus live IMD cyclone/marine "
            "CAP alert checks (consumes a fresh ocean reading)"
        ),
        "requires": ["ocean_state"],
    },
    "pfz": {
        "name": "PFZ Agent",
        "description": (
            "Nearest potential fishing zones derived from live sea-surface "
            "temperature fronts around you"
        ),
        "requires": [],
    },
    "geospatial": {
        "name": "Geospatial Agent",
        "description": (
            "IMBL/MPA boundary geofencing and weather-aware safe-route "
            "planning from your GPS or destination"
        ),
        "requires": [],
    },
    "trend": {
        "name": "Trend Agent",
        "description": (
            "Months-long SST/chlorophyll trend analysis with correlation "
            "for 'why has X changed' questions"
        ),
        "requires": [],
    },
}

INTENT_DEFAULT_AGENTS = {
    "safety_check": ["OceanStateAgent", "HazardAgent", "GeospatialAgent"],
    "pfz_lookup": ["PFZAgent", "OceanStateAgent", "GeospatialAgent"],
    "route_plan": ["GeospatialAgent", "OceanStateAgent", "HazardAgent"],
    "geofence_check": ["GeospatialAgent"],
    "hazard_alerts": ["HazardAgent", "OceanStateAgent"],
    "trend_analysis": ["TrendAgent"],
    "zone_scan": ["PFZAgent", "OceanStateAgent", "HazardAgent", "GeospatialAgent"],
}

PLANNING_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "safety_check",
                "pfz_lookup",
                "route_plan",
                "geofence_check",
                "hazard_alerts",
                "trend_analysis",
                "zone_scan",
                "unknown",
            ],
            "description": (
                "The query type. safety_check = is it safe to venture out "
                "(fishing/boating). pfz_lookup = finding fishing zones. "
                "route_plan = navigating somewhere safely. geofence_check = "
                "boundary/restricted-zone proximity. hazard_alerts = active "
                "weather/marine alerts. trend_analysis = analytical questions "
                "about how SST/chlorophyll/fish productivity changed over a "
                "period and why. zone_scan = ranked good/avoid zones around an "
                "area. unknown if nothing fits."
            ),
        },
        "location_name": {
            "type": "string",
            "description": (
                "The coastal place name mentioned in the query (free text -- "
                "any Indian coastal town/village/port/region, e.g. 'Gopalpur', "
                "'Ratnagiri', 'Kochi'). Use 'same' when the query refers back "
                "to the previous location without naming one. Use 'unknown' "
                "only if no place at all is mentioned."
            ),
        },
        "time_window": {
            "type": "string",
            "enum": KNOWN_TIME_WINDOWS,
            "description": "Roughly when the user is asking about.",
        },
        "target_hour": {
            "type": "integer",
            "minimum": 0,
            "maximum": 23,
            "description": (
                "Exact local hour of day (0-23) if the user names one, e.g. "
                "'tomorrow at 10 am' -> 10. Omit entirely when no specific "
                "hour is mentioned."
            ),
        },
        "months_back": {
            "type": "integer",
            "minimum": 3,
            "maximum": 24,
            "description": (
                "For trend_analysis: how many months of history to analyse "
                "(e.g. 'last 3 months' -> 3). Omit for other intents."
            ),
        },
        "agents_needed": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "OceanStateAgent", "HazardAgent",
                    "PFZAgent", "GeospatialAgent", "TrendAgent",
                ],
            },
            "description": (
                "Specialist agents genuinely needed to answer THIS query."
            ),
        },
        "why": {
            "type": "string",
            "description": "One sentence explaining the planning decision.",
        },
    },
    "required": ["intent", "location_name", "time_window", "agents_needed", "why"],
}

class Intent:
    SAFETY_CHECK = "safety_check"
    PFZ_LOOKUP = "pfz_lookup"
    ROUTE_PLAN = "route_plan"
    GEOFENCE_CHECK = "geofence_check"
    HAZARD_ALERTS = "hazard_alerts"
    TREND_ANALYSIS = "trend_analysis"
    ZONE_SCAN = "zone_scan"
    UNKNOWN = "unknown"

class ORCAGraphState(TypedDict, total=False):
    raw_query: str
    session_id: str
    device_gps: Optional[tuple]
    destination: Optional[Location]
    vessel_class: str
    normalized_query: str
    language: str
    language_mode: str
    plan: dict
    plan_mode: str
    routing_mode: str
    routing_reason: str
    complexity: str
    location: Location
    context: QueryContext
    ocean_state: Optional[object]
    risk: Optional[object]
    pfz: Optional[object]
    geofence: Optional[object]
    route: Optional[object]
    trend: Optional[object]
    discussion: Optional[dict]
    synthesis: Optional[dict]
    response: Optional[OrchestratorResponse]
    traces: Annotated[List[AgentTrace], operator.add]
    timings: dict
    query_depth: str
    mode: str
    fleet_convergence: Optional[dict]
    fleet_demo_level: Optional[str]
