"""
SAR-Based Dark Vessel Detection — Data Models

Every SAR observation carries explicit provenance so downstream consumers
can honestly label REAL vs SIMULATED vs UNAVAILABLE.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class SARSource(str, Enum):
    BHOONIDHI = "BHOONIDHI"
    ORCA_SIMULATION = "ORCA_SIMULATION"
    UNAVAILABLE = "UNAVAILABLE"


class SARStatus(str, Enum):
    REAL = "REAL"
    SIMULATED = "SIMULATED"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


class MatchStatus(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    NOT_NEAR_BOUNDARY = "NOT_NEAR_BOUNDARY"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class AlertLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Provenance — required on every SARObservation
# ---------------------------------------------------------------------------
@dataclass
class SARProvenance:
    source: str = SARSource.UNAVAILABLE.value
    dataset: str = "UNKNOWN"
    product_id: str = ""
    acquisition_time: str = ""  # ISO-8601 UTC
    processing_time: str = ""   # ISO-8601 UTC
    status: str = SARStatus.UNAVAILABLE.value
    # Human-readable note for the authority dashboard
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Detection — one vessel candidate from SAR imagery
# ---------------------------------------------------------------------------
@dataclass
class SARDetection:
    detection_id: str
    latitude: float
    longitude: float
    acquisition_timestamp: str  # ISO-8601 UTC when SAR captured this
    confidence: float           # 0..1
    source: str = SARSource.ORCA_SIMULATION.value
    dataset: str = "DEMO_SAR"
    product_id: str = ""
    distance_to_boundary_km: float = 999.9
    boundary_segment: str = ""
    boundary_type: str = ""  # IMBL / MPA
    is_near_boundary: bool = False
    matched_vessel_id: Optional[str] = None
    match_status: str = MatchStatus.UNKNOWN.value
    alert_level: str = AlertLevel.NONE.value
    status: str = SARStatus.SIMULATED.value
    # Processing pipeline trace (for explainability)
    processing_trace: list = field(default_factory=list)
    # Age in minutes (computed at query time)
    age_minutes: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # aliases for API spec compatibility
        d["lat"] = d["latitude"]
        d["lon"] = d["longitude"]
        d["id"] = d["detection_id"]
        return d


# ---------------------------------------------------------------------------
# Observation — one SAR product / scan result
# ---------------------------------------------------------------------------
@dataclass
class SARObservation:
    observation_id: str
    status: str = SARStatus.SIMULATED.value
    source: str = SARSource.ORCA_SIMULATION.value
    dataset: str = "DEMO_SAR"
    product_id: str = ""
    acquisition_time: str = ""  # ISO-8601 UTC
    processing_time: str = ""   # ISO-8601 UTC
    boundary_radius_km: float = 10.0
    detections: list = field(default_factory=list)  # list[SARDetection]
    provenance: SARProvenance = field(default_factory=SARProvenance)
    is_stale: bool = False
    # Summary counts (computed)
    total_detections: int = 0
    known_count: int = 0
    unknown_count: int = 0

    def to_dict(self) -> dict:
        return {
            "observation_id": self.observation_id,
            "status": self.status,
            "source": self.source,
            "dataset": self.dataset,
            "product_id": self.product_id,
            "acquisition_time": self.acquisition_time,
            "processing_time": self.processing_time,
            "boundary_radius_km": self.boundary_radius_km,
            "is_stale": self.is_stale,
            "total_detections": self.total_detections,
            "known_count": self.known_count,
            "unknown_count": self.unknown_count,
            "provenance": self.provenance.to_dict() if hasattr(self.provenance, "to_dict") else asdict(self.provenance),
            "detections": [d.to_dict() if hasattr(d, "to_dict") else asdict(d) for d in self.detections],
        }


# ---------------------------------------------------------------------------
# Known Vessel — ORCA's own activity record to match against
# ---------------------------------------------------------------------------
@dataclass
class KnownVessel:
    vessel_id: str
    latitude: float
    longitude: float
    timestamp: float  # epoch seconds
    source: str = "ORCA_FLEET"  # ORCA_FLEET | ORCA_USER | SIMULATED_FLEET
    is_simulated: bool = False
    # Optional session/user label (minimal identity, privacy-preserving)
    label: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Scan Result — full pipeline output: observation + matching + alerts
# ---------------------------------------------------------------------------
@dataclass
class SARScanResult:
    observation: SARObservation
    detections: list = field(default_factory=list)  # list[SARDetection]
    alerts: list = field(default_factory=list)      # list[dict]
    # Summary
    total: int = 0
    known: int = 0
    unknown: int = 0
    near_boundary: int = 0
    # Config used
    config: dict = field(default_factory=dict)
    # Timing
    processing_time_ms: float = 0.0
    # Cache hit?
    cache_hit: bool = False

    def to_dict(self) -> dict:
        return {
            "observation_id": self.observation.observation_id,
            "status": self.observation.status,
            "source": self.observation.source,
            "dataset": self.observation.dataset,
            "product_id": self.observation.product_id,
            "acquisition_time": self.observation.acquisition_time,
            "processing_time": self.observation.processing_time,
            "is_stale": self.observation.is_stale,
            "provenance": self.observation.provenance.to_dict() if hasattr(self.observation.provenance, "to_dict") else asdict(self.observation.provenance),
            "config": self.config,
            "total": self.total,
            "total_detections": self.total,
            "known": self.known,
            "unknown": self.unknown,
            "near_boundary": self.near_boundary,
            "known_count": self.known,
            "unknown_count": self.unknown,
            "cache_hit": self.cache_hit,
            "processing_time_ms": self.processing_time_ms,
            "detections": [d.to_dict() if hasattr(d, "to_dict") else asdict(d) for d in self.detections],
            "alerts": self.alerts,
        }
