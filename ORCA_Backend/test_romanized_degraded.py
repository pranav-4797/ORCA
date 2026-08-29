"""
Regression for romanized regional queries — Task 2 extension.

Ensures Latin-script transliterated queries like "kal subah machli pakadna safe hai kya"
are caught when LLM is unavailable and routed to degraded-mode message,
same as Indic-script queries. Does not affect English or Indic-script handling.
"""
from unittest.mock import patch
import llm_client
from orchestrator import Orchestrator

# 2-3 romanized examples per language we support with keywords
ROMANIZED_EXAMPLES = {
    "hi": [
        "kal subah machli pakadna safe hai kya",
        "samundar me toofan ka khatra hai kya",
        "machli pakadne jana surakshit hai kya",
    ],
    "mr": [
        "udya sakali maasaemari surakshit ahe ka",
        "samudra madhe vadal cha dhoka ahe ka",
        "maasa pakadne surakshit ahe ka",
    ],
    "ta": [
        "kadalil meen pidippu paadukappu",
        "kadalil puyal apayam irukka",
        "meen pidippa samudra suraksha",
    ],
    "te": [
        "samudram lo chepa patadmu bhadrata",
        "teeram daggara hechcharika unda",
        "samudram lo toofan pramadam unda",
    ],
    "bn": [
        "samudra te nirapad machh dhara jabe ki",
        "samudra te jhor bipad ache ki",
        "jal e machh suraksha ache ki",
    ],
    "ml": [
        "kadalil meen piditham suraksha undo",
        "kadalil thira apakadam undo",
        "samudra kinara suraksha",
    ],
    "kn": [
        "samudra dalli meenugarike suraksha idya",
        "samudra dalli ale apaya ideya",
        "karavali suraksha hecharike",
    ],
    "gu": [
        "samudra ma machhimari surakshit chhe ke",
        "dariyo ma vavazodu khatro chhe",
        "samudra kinaro surakshit chhe",
    ],
    "or": [
        "samudra re machha dhara suraksha achhi ki",
        "samudra re jhada bipad achhi ki",
        "jal re machha suraksha",
    ],
    "pa": [
        "samundar vich machhi surakhia hai ki",
        "samundar vich toofan khatra hai",
        "jal vich machhi surakhia",
    ],
}

def _is_degraded(resp):
    # Check for degraded markers (Hindi/Marathi/Tamil etc. or English limited)
    markers = ["सीमित", "मर्यादित", "limited", "சேவை", "సేవ", "সীমিত", "പരിമിത", "ಸೀಮಿತ", "મર્યાદિત", "ਸੀਮਤ"]
    return any(m in resp.answer for m in markers) or resp.routing.get("routing_mode") == "degraded"

def test_romanized_degraded_per_language():
    o = Orchestrator()
    for lang, queries in ROMANIZED_EXAMPLES.items():
        for q in queries:
            with patch.object(llm_client, "is_available", return_value=False):
                # Also patch planning's llm_client if needed (same module, but patch global is enough)
                resp = o.handle_query(q, mode="auto")
                assert resp is not None, f"Should not crash for {lang} romanized: {q}"
                assert _is_degraded(resp), f"Romanized {lang} query should be degraded when LLM down, got mode={resp.mode} routing={resp.routing} answer={resp.answer[:100]} for '{q}'"
                # Language should be detected as romanized language (or at least not en)
                assert resp.language != "en" or resp.routing.get("routing_mode") == "degraded", f"Language should be regional for romanized {q}"
                # Ensure not confused with English routing (should not have safety_check agents for degraded)
                assert resp.routing.get("routing_mode") == "degraded"

def test_romanized_english_not_degraded():
    """English queries should NOT be degraded even when LLM down."""
    o = Orchestrator()
    from unittest.mock import patch as p
    from models import DataSource, AgentTrace, Location, PFZRecommendation, GeofenceStatus, SafetyStatus
    import datetime
    def fake_ocean(location, time_window="today", target_hour=None, thresholds=None):
        from models import OceanStateReading
        reading = OceanStateReading(location=location, timestamp=datetime.datetime.now(datetime.timezone.utc), sst_celsius=28, chlorophyll_mg_m3=0.8, wave_height_m=1.0, wind_speed_kmh=12, wind_gust_kmh=20, tide_level_m=1.0, source=DataSource.SIMULATED, confidence=0.6, reasoning_note="wave")
        return reading, AgentTrace(agent_name="OceanStateAgent", action="fake", result_summary="wave", data_sources=[DataSource.SIMULATED], duration_ms=5)
    def fake_hazard(ocean_state, vessel_class="small_fishing_boat"):
        from models import RiskAssessment
        risk = RiskAssessment(status=SafetyStatus.SAFE, headline="safe", flags=[], reasoning=[], evidence_sources=[ocean_state.source], confidence=0.9, reasoning_note="safe")
        return risk, AgentTrace(agent_name="HazardAgent", action="fake", result_summary="SAFE", data_sources=[ocean_state.source], duration_ms=2)
    english_queries = [
        "Is it safe to fish near Kochi tomorrow?",
        "Any cyclone warning near Ratnagiri?",
        "Where is the nearest fishing zone near Kochi?",
    ]
    with patch.object(llm_client, "is_available", return_value=False):
        with p('agents.ocean_state_agent.OceanStateAgent.run', side_effect=fake_ocean):
            with p('agents.hazard_agent.HazardAgent.run', side_effect=fake_hazard):
                with p('agents.pfz_agent.PFZAgent.run', side_effect=lambda *a, **k: (PFZRecommendation(reference_location=Location(name="Kochi", lat=9.9, lon=76.2), center_lat=10.0, center_lon=76.3, distance_from_reference_km=12, bearing_deg=45, sst_at_zone_celsius=27.5, chlorophyll_at_zone_mg_m3=0.8, source=DataSource.DERIVED_LIVE, confidence=0.6, reasoning_note="zone"), AgentTrace(agent_name="PFZAgent", action="fake", result_summary="pfz", data_sources=[DataSource.DERIVED_LIVE], duration_ms=1))):
                    with p('agents.geospatial_agent.GeospatialAgent.run', side_effect=lambda *a, **k: ((GeofenceStatus(reference_location=Location(name="Kochi", lat=9.9, lon=76.2), hits=[], nearest_boundary_km=999, clear=True), None), AgentTrace(agent_name="GeospatialAgent", action="fake", result_summary="clear", data_sources=[], duration_ms=1))):
                        for q in english_queries:
                            resp = o.handle_query(q, mode="auto")
                            assert resp.routing.get("routing_mode") != "degraded", f"English query should not be degraded: {q} got {resp.routing}"
                            assert not _is_degraded(resp) or resp.language == "en", f"English query incorrectly degraded: {q}"

def test_romanized_indic_script_unchanged():
    """Indic-script queries should still be degraded as before (not broken by romanized extension)."""
    o = Orchestrator()
    marathi = "उद्या सकाळी मासेमारीसाठी जाणं सुरक्षित आहे का?"
    hindi = "क्या कल सुबह मछली पकड़ने जाना सुरक्षित है?"
    for q in [marathi, hindi]:
        with patch.object(llm_client, "is_available", return_value=False):
            resp = o.handle_query(q, mode="auto")
            assert _is_degraded(resp), f"Indic-script should still be degraded: {q}"
