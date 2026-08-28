"""
Shared schemas for ORCA's agent backend.

Every agent consumes and produces these types. Keeping one shared contract
is what lets the Orchestrator route data between agents without each agent
needing to know the internals of another.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SafetyStatus(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    UNSAFE = "UNSAFE"


class DataSource(str, Enum):
    """Tags every data point with where it actually came from.

    This is what lets the final response honestly say "real" vs "simulated"
    data was used -- the same distinction called out on the architecture slide.
    """
    BHUVAN_LIVE = "bhuvan_live"
    IMD_CAP_LIVE = "imd_cap_live"  # keyless IMD CAP alerts feed
    IMD_LIVE = "imd_live"
    MOSDAC_LIVE = "mosdac_live"
    INCOIS_LIVE = "incois_live"
    LIVE = "live"  # keyless live feed (Open-Meteo Marine/Weather)
    TIDE_GAUGE_MODEL = "tide_gauge_model"  # harmonic fit on real UHSLC gauge obs
    DERIVED_LIVE = "derived_from_live_data"  # computed FROM live fields (not invented)
    STATIC_DERIVED = "static_derived"
    SIMULATED = "simulated"


@dataclass
class Location:
    name: str
    lat: float
    lon: float


@dataclass
class QueryContext:
    """What the Orchestrator hands to every agent it dispatches to."""
    raw_query: str
    location: Location
    time_window: str  # e.g. "today", "tomorrow_morning", "2026-08-24"
    session_id: str
    language: str = "en"  # detected by the Language/Intent Agent (BCP-47-ish code)
    # Optional live inputs from the client (Tier 1 -- the user's own device).
    device_gps: Optional[tuple] = None      # (lat, lon) or None
    destination: Optional[Location] = None  # for route_plan queries
    # Explicit local hour override ("tomorrow at 10 am" -> 10). None = the
    # window's default hour.
    target_hour: Optional[int] = None
    # Vessel class selects the safety-threshold envelope (hazard agent).
    vessel_class: str = "small_fishing_boat"


@dataclass
class ExceedanceWindow:
    """One time interval where a metric crosses a safety threshold.

    Produced by the Ocean-State Agent from the hourly forecast series so
    answers can cite WHEN conditions worsen, not just a single value
    (PDF Sec. 15.1 example: 'waves reach 2.8 m between 6-10 AM').
    """
    metric: str            # "wave_height_m" | "wind_gust_kmh"
    threshold: float       # the crossed threshold value
    start_local: str       # ISO local wall-clock, e.g. "2026-08-26T14:00"
    end_local: str
    peak_value: float
    unit: str              # "m" | "km/h"


@dataclass
class TideExtreme:
    """One high/low tide event predicted from the harmonic fit (Tier 2)."""
    kind: str              # "high" | "low"
    time_local: str        # ISO local wall clock at the location's offset
    height_m: float


@dataclass
class TrendPoint:
    date: str              # ISO date of the observation
    sst_celsius: Optional[float] = None
    chlorophyll_mg_m3: Optional[float] = None


@dataclass
class TrendAnalysis:
    """Output of the Trend Agent: historical SST/chlorophyll correlation."""
    location_name: str
    window_months: int
    points: list = field(default_factory=list)          # [TrendPoint]
    sst_trend_per_month: float = 0.0                    # deg C / month (linear fit)
    chl_trend_per_month: float = 0.0                    # mg/m3 / month
    sst_chl_correlation: Optional[float] = None         # Pearson r over common dates
    interpretation_note: str = ""                       # LLM or template narrative
    field_sources: dict = field(default_factory=dict)
    reasoning_note: str = ""


@dataclass
class OceanStateReading:
    """Output of the Ocean-State Agent."""
    location: Location
    timestamp: datetime
    sst_celsius: float
    chlorophyll_mg_m3: float
    wave_height_m: float
    wind_speed_kmh: float
    wind_gust_kmh: float
    tide_level_m: float
    source: DataSource
    confidence: float  # 0.0 - 1.0
    # Natural-language note written by the agent's LLM layer, interpreting
    # the structured numbers above in its own words. Empty when the LLM
    # layer is unavailable (fallback path).
    reasoning_note: str = ""
    # Per-field honesty metadata: maps field name -> "live" | "simulated" so
    # responses can state exactly which values are real and which are not,
    # instead of blanket-tagging the whole reading.
    field_sources: dict = field(default_factory=dict)
    # Threshold-crossing intervals computed from the hourly forecast series
    # (temporal exceedance reasoning, PDF Sec. 15.1). Empty when no threshold
    # is crossed in the fetched window.
    exceedance_windows: list = field(default_factory=list)   # [ExceedanceWindow]
    # Next high/low tide events + range from the harmonic model (P1 #14).
    tide_extremes: list = field(default_factory=list)        # [TideExtreme]
    # Hourly series for charting (/viz endpoints). Keys are metric names,
    # values are {"times": [...], "values": [...]} local ISO strings.
    hourly_series: dict = field(default_factory=dict)


@dataclass
class HazardFlag:
    label: str
    detail: str
    threshold_crossed: str


@dataclass
class PFZRecommendation:
    """Output of the PFZ Agent: nearest potential fishing zone.

    Tier 3 today: when the Bhuvan WMS GetFeatureInfo call is unavailable,
    the zone is derived deterministically from the (simulated) chlorophyll
    and SST fields -- every field is tagged in `field_sources` so responses
    stay honest about what is live vs derived.
    """
    reference_location: Location
    center_lat: float
    center_lon: float
    distance_from_reference_km: float
    bearing_deg: float  # compass bearing from reference point to zone centre
    sst_at_zone_celsius: float
    chlorophyll_at_zone_mg_m3: float
    source: DataSource
    confidence: float
    reasoning_note: str = ""
    field_sources: dict = field(default_factory=dict)
    # Ranked secondary zones from the region scan (P1 #12). Each entry:
    # {"center_lat", "center_lon", "distance_km", "bearing_deg",
    #  "sst_celsius", "rank"}.
    alternates: list = field(default_factory=list)


@dataclass
class RestrictedZoneHit:
    """One boundary/zone flagged by the Geospatial Reasoning Agent."""
    zone_name: str
    zone_type: str            # "IMBL" | "MPA" | ...
    inside_zone: bool
    distance_to_boundary_km: float


@dataclass
class GeofenceStatus:
    """Output of the Geospatial Reasoning Agent's geofence check."""
    reference_location: Location
    hits: list[RestrictedZoneHit] = field(default_factory=list)
    nearest_boundary_km: float = float("inf")
    clear: bool = True  # True when nothing restricted within the alert buffer
    reasoning_note: str = ""


@dataclass
class RoutePlan:
    """Output of the Geospatial Reasoning Agent's safe-route calculation."""
    start_lat: float
    start_lon: float
    dest_lat: float
    dest_lon: float
    waypoints: list = field(default_factory=list)       # [(lat, lon), ...]
    avoided_zones: list[str] = field(default_factory=list)
    estimated_distance_km: float = 0.0
    bathymetry_source: str = "not yet integrated (GEBCO TODO)"
    # Minimum depth (negative metres) sampled along the route; None when
    # bathymetry was unavailable.
    min_depth_m: Optional[float] = None
    shallow_segments: int = 0          # waypoint pairs crossing < MIN_DEPTH cells
    hazard_waypoints: list = field(default_factory=list)  # indices of waypoints in forecast hazard zones
    algorithm: str = "sampled-detour"  # "a-star" once A* runs
    reasoning_note: str = ""


@dataclass
class RiskAssessment:
    """Output of the Hazard/Risk Agent."""
    status: SafetyStatus
    headline: str
    flags: list[HazardFlag] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    evidence_sources: list[DataSource] = field(default_factory=list)
    confidence: float = 1.0
    # Natural-language note written by the agent's LLM layer, explaining the
    # verdict above in its own words. Empty when the LLM is unavailable.
    reasoning_note: str = ""
    # Temporal windows where thresholds are crossed (cited by Response Agent).
    exceedance_windows: list = field(default_factory=list)   # [ExceedanceWindow]
    # IMD CAP polygons covering/near this area, for map overlays (viz).
    # Each entry: {"event", "severity", "area_desc", "polygon": [(lat, lon)]}
    cap_polygons: list = field(default_factory=list)
    # Marine bulletin summary lines (fishermen warnings, squally wind...).
    marine_bulletins: list = field(default_factory=list)


@dataclass
class AgentTrace:
    """One entry in the explainability trace -- what each agent did and why.

    This is the literal implementation of the 'Explainability Trace' step
    from the architecture diagram.
    """
    agent_name: str
    action: str
    result_summary: str
    data_sources: list[DataSource]
    duration_ms: float


@dataclass
class OrchestratorResponse:
    answer: str
    status: SafetyStatus
    reasoning: list[str]
    evidence_sources: list[DataSource]
    trace: list[AgentTrace]
    ocean_state: Optional[OceanStateReading] = None
    risk: Optional[RiskAssessment] = None
    # Cross-agent disagreements flagged by the Synthesis Agent (e.g. an
    # agent's note that contradicts another's structured finding).
    conflicts: list[str] = field(default_factory=list)
    # Round-table transcript from the Discussion Agent: agents talking to
    # each other before reconciliation. Each turn is
    # {"speaker", "addressing", "stance", "point"}; plus a final
    # {"consensus": str} entry appended by the orchestrator.
    discussion: list = field(default_factory=list)
    # How this answer was produced: "panel" (full round-table pipeline) or
    # "agent" (one specialist addressed directly, no discussion round).
    mode: str = "panel"
    answered_by: str = ""
    # Numeric confidence in [0, 1] (PDF Sec 9/16): provenance live-fraction,
    # hazard verdict confidence, and cross-agent agreement, combined.
    confidence_score: float = 0.0
    # Evidence register: each source labelled with its PDF data tier.
    # Entries: {"source": str, "tier": "Tier 1|2|3", "kind": str}
    evidence_tiers: list = field(default_factory=list)
    # Language/Intent Agent's detection -- responses must come back in this.
    language: str = "en"
    # Specialist results (None when the Planner didn't dispatch them).
    pfz: Optional[PFZRecommendation] = None
    geofence: Optional[GeofenceStatus] = None
    route: Optional[RoutePlan] = None
    trend: Optional[TrendAnalysis] = None
    # Region-scan avoid list (P1 #12): combined hazard+geofence zones to stay
    # clear of, each as {"zone", "reason", "distance_km"}.
    avoid_zones: list = field(default_factory=list)
    # Latency telemetry (ms) — total and per-stage breakdown, for optimization verification
    timings: dict = field(default_factory=dict)
    # Auto routing explainability (which agents were selected and why)
    routing: dict = field(default_factory=dict)
    # Fleet Convergence Forecast (Innovation #1) — crowding-adjusted recommendation
    fleet_convergence: Optional[dict] = None
