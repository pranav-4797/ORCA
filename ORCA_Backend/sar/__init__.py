"""SAR-Based Dark Vessel Detection — package init."""
from .models import (
    SARSource,
    SARStatus,
    MatchStatus,
    AlertLevel,
    SARDetection,
    SARObservation,
    KnownVessel,
    SARScanResult,
)
from .providers import SARDataProvider, BhoonidhiSARProvider, DemoSARProvider, get_provider
from .engine import run_sar_scan, SARConfig, get_default_config
from .store import sar_store
from .boundary import distance_to_boundary, is_near_boundary, get_boundary_info

__all__ = [
    "SARSource", "SARStatus", "MatchStatus", "AlertLevel",
    "SARDetection", "SARObservation", "KnownVessel", "SARScanResult",
    "SARDataProvider", "BhoonidhiSARProvider", "DemoSARProvider", "get_provider",
    "run_sar_scan", "SARConfig", "get_default_config",
    "sar_store", "distance_to_boundary", "is_near_boundary", "get_boundary_info",
]
