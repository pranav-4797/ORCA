"""
SAR Data Provider Abstraction

                  SARDataProvider
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
      BhoonidhiSARProvider    DemoSARProvider
              │                     │
              ▼                     ▼
        Real SAR data          deterministic demo
"""
from __future__ import annotations

import os
import time
import json
import logging
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from .models import SARObservation, SARDetection, SARProvenance, SARSource, SARStatus

logger = logging.getLogger("orca.sar.provider")

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
class SARDataProvider(ABC):
    """Abstract SAR product provider. Returns SARObservation (detections + provenance)."""

    name: str = "abstract"

    @abstractmethod
    def fetch_observation(
        self,
        area: Optional[dict] = None,
        time_window: str = "today",
    ) -> SARObservation:
        """Fetch one SAR observation (product + detections + provenance)."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """True if this provider can return data without external credentials."""
        ...

    def describe(self) -> dict:
        return {"provider": self.name, "available": self.is_available()}


# ---------------------------------------------------------------------------
# Demo Provider — deterministic, no credentials, no network
# ---------------------------------------------------------------------------
# Demo scenario geometry (near the Palk Strait IMBL for visual relevance)
# Boundary segment roughly at 79.9E; detections scattered so one is very close,
# others are farther — to exercise near/far AND known/unknown.
_DEMO_BBOX = {"lat_min": 9.4, "lat_max": 10.2, "lon_min": 79.6, "lon_max": 80.2}

# Deterministic demo detections (5). 4 of them have matching ORCA vessels nearby,
# 1 is deliberately unmatched -> UNKNOWN high-priority.
# Coordinates are chosen so that ALL 5 are within 10km of IMBL (near Palk Strait segment)
# to reliably demonstrate 5 near-boundary detections: 4 KNOWN + 1 UNKNOWN.
# Distances verified against data/marine_boundaries.geojson (all ~0.5-5.5km).
_DEMO_DETECTIONS_RAW = [
    # id, lat, lon, confidence — commentary
    ("SAR-DEMO-001", 9.950, 79.920, 0.91),  # ~3.9 km from IMBL — HIGH unknown (no matching vessel)
    ("SAR-DEMO-002", 9.980, 79.930, 0.88),  # ~4.4 km — matched
    ("SAR-DEMO-003", 9.920, 79.900, 0.82),  # ~5.1 km — matched
    ("SAR-DEMO-004", 9.880, 79.890, 0.76),  # ~5.3 km — matched
    ("SAR-DEMO-005", 10.020, 79.940, 0.84), # ~5.4 km — matched
]

# Demo known vessels: place ORCA vessels near 002-005 but NOT near 001
_DEMO_KNOWN_VESSELS_OFFSET = {
    "SAR-DEMO-002": (0.006, 0.004),
    "SAR-DEMO-003": (-0.004, 0.005),
    "SAR-DEMO-004": (0.005, -0.004),
    "SAR-DEMO-005": (0.004, 0.006),
    # SAR-DEMO-001 is intentionally left unmatched
}


class DemoSARProvider(SARDataProvider):
    """
    Deterministic demo provider — always available, no credentials.

    Simulates a SAR product that detected 5 vessels near the maritime
    boundary; 4 are matched to ORCA's known fleet, 1 remains UNKNOWN.
    The same input always produces the same detections (via fixed seed),
    which makes integration tests reproducible.

    The detection pipeline is SIMULATED step-by-step (see processing_trace)
    but does NOT pretend to download real SAR imagery.
    """
    name = "demo"
    dataset = "DEMO_SAR_SIMULATED"
    product_prefix = "DEMO_PRODUCT"

    def is_available(self) -> bool:
        return True

    def fetch_observation(
        self,
        area: Optional[dict] = None,
        time_window: str = "today",
    ) -> SARObservation:
        now = datetime.now(timezone.utc)
        # Simulate acquisition 27 minutes ago (fresh, not stale)
        acq = now.timestamp() - 27 * 60
        acq_iso = datetime.fromtimestamp(acq, tz=timezone.utc).isoformat()
        proc_iso = now.isoformat()
        # Product ID is deterministic from area + time_window (like a real product ID)
        area_key = json.dumps(area or _DEMO_BBOX, sort_keys=True)
        product_id = f"{self.product_prefix}_{hashlib.sha256((area_key + time_window).encode()).hexdigest()[:12].upper()}"

        detections: list[SARDetection] = []
        for det_id, lat, lon, conf in _DEMO_DETECTIONS_RAW:
            # Respect area filter if provided (simple bbox check)
            if area:
                if not (area.get("lat_min", -90) <= lat <= area.get("lat_max", 90) and
                        area.get("lon_min", -180) <= lon <= area.get("lon_max", 180)):
                    continue
            d = SARDetection(
                detection_id=det_id,
                latitude=lat,
                longitude=lon,
                acquisition_timestamp=acq_iso,
                confidence=conf,
                source=SARSource.ORCA_SIMULATION.value,
                dataset=self.dataset,
                product_id=product_id,
                status=SARStatus.SIMULATED.value,
                processing_trace=[
                    "SAR Product (simulated) → Preprocessing (simulated) → Sea/Land Mask (simulated) → Candidate Detection (simulated) → Vessel Detection (simulated) → Geolocation (simulated)",
                    "Note: This is a deterministic demo observation — NOT a real satellite acquisition. Replace provider with BhoonidhiSARProvider for live data.",
                ],
            )
            detections.append(d)

        prov = SARProvenance(
            source=SARSource.ORCA_SIMULATION.value,
            dataset=self.dataset,
            product_id=product_id,
            acquisition_time=acq_iso,
            processing_time=proc_iso,
            status=SARStatus.SIMULATED.value,
            note="DEMO — SIMULATED SAR DATA. Not a real satellite observation. For SIH demonstration only.",
        )

        obs = SARObservation(
            observation_id=f"OBS-DEMO-{product_id}",
            status=SARStatus.SIMULATED.value,
            source=SARSource.ORCA_SIMULATION.value,
            dataset=self.dataset,
            product_id=product_id,
            acquisition_time=acq_iso,
            processing_time=proc_iso,
            detections=detections,
            provenance=prov,
            total_detections=len(detections),
        )
        return obs

    def describe(self) -> dict:
        return {
            "provider": self.name,
            "dataset": self.dataset,
            "available": True,
            "status": SARStatus.SIMULATED.value,
            "note": "Deterministic demo — 5 detections, 1 unknown near IMBL. No credentials required.",
        }


# ---------------------------------------------------------------------------
# Bhoonidhi Provider — official ISRO/NRSC EO infrastructure
# ---------------------------------------------------------------------------
class BhoonidhiSARProvider(SARDataProvider):
    """
    Live SAR provider via ISRO/NRSC Bhoonidhi (https://bhoonidhi.nrsc.gov.in).

    Required env vars (never hard-coded):
      BHOONIDHI_API_KEY / BHOONIDHI_USERNAME + BHOONIDHI_PASSWORD  (auth)
      BHOONIDHI_BASE_URL  (default: https://bhoonidhi.nrsc.gov.in/bhoonidhi)

    Preferred datasets (checked in order, no hard RISAT assumption):
      NISAR_SAR  |  Sentinel-1_SAR  |  any SAR collection exposed via Bhoonidhi

    Real usage: POST /bhoonidhi/Search  +  GET /bhoonidhi/Download among others
    (see active NRSC docs at registration — exact path confirmed at key issue).

    When credentials are missing/invalid, is_available() returns False and
    fetch_observation() returns an UNAVAILABLE observation that honestly reports
    that live SAR is not configured, rather than pretending.
    """
    name = "bhoonidhi"
    # Official datasets currently accessible via Bhoonidhi EO catalog
    # Do NOT assume RISAT availability; check live catalog after authentication.
    PREFERRED_DATASETS = [
        "NISAR_SAR",
        "Sentinel-1_SAR",
        "SAR_GENERIC",
    ]

    def __init__(self):
        self.base_url = os.getenv("BHOONIDHI_BASE_URL", "https://bhoonidhi.nrsc.gov.in/bhoonidhi").strip().rstrip("/")
        self.api_key = os.getenv("BHOONIDHI_API_KEY", "").strip()
        self.username = os.getenv("BHOONIDHI_USERNAME", "").strip()
        self.password = os.getenv("BHOONIDHI_PASSWORD", "").strip()
        self.dataset_env = os.getenv("BHOONIDHI_DATASET", "").strip()
        # Cache for token etc.
        self._token: Optional[str] = None
        self._token_expiry: float = 0

    def is_available(self) -> bool:
        # Available only when some credential is configured
        return bool(self.api_key or (self.username and self.password))

    def describe(self) -> dict:
        configured = self.is_available()
        return {
            "provider": self.name,
            "base_url": self.base_url,
            "dataset_configured": self.dataset_env or "(auto: NISAR/Sentinel-1)",
            "available": configured,
            "status": SARStatus.REAL.value if configured else SARStatus.UNAVAILABLE.value,
            "auth": "BHOONIDHI_API_KEY" if self.api_key else ("BHOONIDHI_USERNAME/PASSWORD" if self.username else "NOT_CONFIGURED"),
            "note": "Set BHOONIDHI_API_KEY or BHOONIDHI_USERNAME/PASSWORD to enable live SAR. Without credentials, DemoSARProvider is used.",
        }

    # ------------------------------------------------------------------
    # Auth helpers (best-effort against Bhoonidhi token endpoints)
    # ------------------------------------------------------------------
    def _get_token(self) -> Optional[str]:
        """Fetch/refresh auth token if needed. Returns None when not configured."""
        if self.api_key:
            return self.api_key  # Bearer key directly
        if not (self.username and self.password):
            return None
        # Try token endpoint — exact path varies by Bhoonidhi deployment;
        # we try the documented pattern: POST /Login or /Auth with JSON credentials.
        # If this fails, caller will degrade gracefully to UNAVAILABLE.
        if self._token and time.time() < self._token_expiry:
            return self._token
        import urllib.request, urllib.parse
        for path in ["/Login", "/api/Login", "/Auth", "/api/auth/token"]:
            url = self.base_url + path
            body = json.dumps({"username": self.username, "password": self.password}).encode()
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode())
                    tok = data.get("token") or data.get("access_token") or data.get("data", {}).get("token")
                    if tok:
                        self._token = tok
                        self._token_expiry = time.time() + 3300  # ~55 min
                        logger.info("Bhoonidhi auth token obtained via %s", path)
                        return tok
            except Exception as exc:
                logger.debug("Bhoonidhi auth %s failed: %s", path, exc)
                continue
        return None

    # ------------------------------------------------------------------
    # Product search (metadata only)
    # ------------------------------------------------------------------
    def _search_products(self, token: str, area: Optional[dict], dataset: Optional[str] = None) -> list[dict]:
        import urllib.request
        ds = dataset or self.dataset_env or self.PREFERRED_DATASETS[0]
        bbox = area or _DEMO_BBOX
        # Bhoonidhi Search API: POST with catalog filters (lat/lon bbox, date range, dataset)
        payload = {
            "dataset": ds,
            "bbox": [bbox.get("lon_min", 78.0), bbox.get("lat_min", 7.5), bbox.get("lon_max", 80.5), bbox.get("lat_max", 10.5)],
            "startDate": (datetime.now(timezone.utc).timestamp() - 7*24*3600),  # last 7 days
            "endDate": datetime.now(timezone.utc).timestamp(),
            "maxRecords": 5,
        }
        for path in ["/Search", "/api/Search", "/bhoonidhi/Search"]:
            url = self.base_url + path
            body = json.dumps(payload).encode()
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
            req = urllib.request.Request(url, data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode())
                    # Normalize to list of products
                    products = data.get("products") or data.get("results") or data.get("data") or []
                    if isinstance(products, list) and products:
                        logger.info("Bhoonidhi search %s -> %d products", path, len(products))
                        return products[:5]
            except Exception as exc:
                logger.debug("Bhoonidhi search %s failed: %s", path, exc)
                continue
        return []

    # ------------------------------------------------------------------
    # Vessel detection pipeline (stub — real implementation would use a
    # SAR vessel-detection model on the downloaded GeoTIFF + CFAR etc.)
    # ------------------------------------------------------------------
    def _run_detection_pipeline(self, product: dict, acquisition_time: str) -> list[SARDetection]:
        """
        Real SAR imagery → preprocessing → sea/land mask → candidate detection
        → vessel detection → geolocation.

        This stub implements the pipeline stages as NO-OPs that honestly report
        that automated on-image vessel detection is not yet integrated, so the
        system does NOT pretend that raw SAR pixels are vessels.

        When a product has pre-computed vessel annotations (e.g. NISAR value-added
        product), those would be parsed here. Otherwise returns empty and the
        observation will be UNAVAILABLE rather than invented.

        If a reliable pretrained SAR vessel-detection model is vendored later,
        replace this method with the model inference and keep the provenance.
        """
        # Check for embedded vessel annotations (some Bhoonidhi value-added products)
        # For example: product.get("vessels") or product.get("detections")
        raw = product.get("vessels") or product.get("detections") or product.get("features") or []
        if raw and isinstance(raw, list):
            detections: list[SARDetection] = []
            for idx, v in enumerate(raw[:50]):  # cap
                try:
                    lat = float(v.get("lat") or v.get("latitude") or v["geometry"]["coordinates"][1])
                    lon = float(v.get("lon") or v.get("longitude") or v["geometry"]["coordinates"][0])
                    conf = float(v.get("confidence") or v.get("score") or 0.6)
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        continue
                    if not (0 <= conf <= 1.0):
                        conf = max(0.0, min(1.0, conf))
                    detections.append(SARDetection(
                        detection_id=f"SAR-BHOONIDHI-{product.get('productId','UNK')}-{idx:03d}",
                        latitude=lat,
                        longitude=lon,
                        acquisition_timestamp=acquisition_time,
                        confidence=conf,
                        source=SARSource.BHOONIDHI.value,
                        dataset=product.get("dataset") or self.dataset_env or self.PREFERRED_DATASETS[0],
                        product_id=str(product.get("productId") or product.get("id") or "UNKNOWN"),
                        status=SARStatus.REAL.value,
                        processing_trace=[
                            "SAR Product (BHOONIDHI) → Preprocessing → Sea/Land Mask → CFAR/Detection → Geolocation",
                            "Source: annotated vessel list from Bhoonidhi value-added product (not pixel invention).",
                        ],
                    ))
                except Exception:
                    continue
            if detections:
                return detections
        # No annotated vessels and no local ML model yet — do NOT invent detections.
        logger.warning("Bhoonidhi product %s has no vessel annotations and no local detection model is configured — returning empty detection set", product.get("productId", "?"))
        return []

    # ------------------------------------------------------------------
    def fetch_observation(
        self,
        area: Optional[dict] = None,
        time_window: str = "today",
    ) -> SARObservation:
        now = datetime.now(timezone.utc)
        proc_iso = now.isoformat()

        if not self.is_available():
            prov = SARProvenance(
                source=SARSource.UNAVAILABLE.value,
                dataset="UNAVAILABLE",
                product_id="",
                acquisition_time="",
                processing_time=proc_iso,
                status=SARStatus.UNAVAILABLE.value,
                note="Bhoonidhi credentials not configured. Set BHOONIDHI_API_KEY or BHOONIDHI_USERNAME/PASSWORD. DemoSARProvider is available for local development.",
            )
            return SARObservation(
                observation_id=f"OBS-UNAVAILABLE-{int(time.time())}",
                status=SARStatus.UNAVAILABLE.value,
                source=SARSource.UNAVAILABLE.value,
                dataset="UNAVAILABLE",
                provenance=prov,
                detections=[],
                total_detections=0,
            )

        token = self._get_token()
        if not token:
            prov = SARProvenance(
                source=SARSource.BHOONIDHI.value,
                dataset=self.dataset_env or self.PREFERRED_DATASETS[0],
                product_id="",
                acquisition_time="",
                processing_time=proc_iso,
                status=SARStatus.UNAVAILABLE.value,
                note="Bhoonidhi authentication failed — check BHOONIDHI_API_KEY / USERNAME/PASSWORD.",
            )
            return SARObservation(
                observation_id=f"OBS-AUTHFAIL-{int(time.time())}",
                status=SARStatus.UNAVAILABLE.value,
                source=SARSource.BHOONIDHI.value,
                dataset=prov.dataset,
                provenance=prov,
                detections=[],
            )

        # Search for recent SAR products
        products = self._search_products(token, area)
        if not products:
            # No products in window — honestly report UNAVAILABLE, not simulated
            prov = SARProvenance(
                source=SARSource.BHOONIDHI.value,
                dataset=self.dataset_env or self.PREFERRED_DATASETS[0],
                product_id="",
                acquisition_time="",
                processing_time=proc_iso,
                status=SARStatus.UNAVAILABLE.value,
                note="No SAR products found for the requested area/time window. Try a broader window or check Bhoonidhi catalog availability for the selected dataset.",
            )
            return SARObservation(
                observation_id=f"OBS-NOPRODUCT-{int(time.time())}",
                status=SARStatus.UNAVAILABLE.value,
                source=SARSource.BHOONIDHI.value,
                dataset=prov.dataset,
                provenance=prov,
                detections=[],
            )

        # Use most recent product
        product = products[0]
        acq_time = product.get("acquisitionTime") or product.get("acquisition_time") or product.get("sensingTime") or proc_iso
        if isinstance(acq_time, (int, float)):
            acq_time = datetime.fromtimestamp(acq_time, tz=timezone.utc).isoformat()
        product_id = str(product.get("productId") or product.get("id") or product.get("identifier") or "UNKNOWN")
        dataset = str(product.get("dataset") or product.get("collection") or self.dataset_env or self.PREFERRED_DATASETS[0])

        detections = self._run_detection_pipeline(product, acq_time)

        # If pipeline produced no detections, mark as UNAVAILABLE (don't invent)
        if not detections:
            prov = SARProvenance(
                source=SARSource.BHOONIDHI.value,
                dataset=dataset,
                product_id=product_id,
                acquisition_time=acq_time,
                processing_time=proc_iso,
                status=SARStatus.UNAVAILABLE.value,
                note="SAR product found but automated vessel detection is not yet integrated for raw imagery. Configure a vessel-detection model or use value-added products with vessel annotations.",
            )
            return SARObservation(
                observation_id=f"OBS-NODETECTION-{product_id}",
                status=SARStatus.UNAVAILABLE.value,
                source=SARSource.BHOONIDHI.value,
                dataset=dataset,
                product_id=product_id,
                acquisition_time=acq_time,
                processing_time=proc_iso,
                provenance=prov,
                detections=[],
            )

        prov = SARProvenance(
            source=SARSource.BHOONIDHI.value,
            dataset=dataset,
            product_id=product_id,
            acquisition_time=acq_time,
            processing_time=proc_iso,
            status=SARStatus.REAL.value,
            note=f"Real SAR observation from Bhoonidhi. Dataset={dataset} Product={product_id}",
        )
        return SARObservation(
            observation_id=f"OBS-REAL-{product_id}",
            status=SARStatus.REAL.value,
            source=SARSource.BHOONIDHI.value,
            dataset=dataset,
            product_id=product_id,
            acquisition_time=acq_time,
            processing_time=proc_iso,
            detections=detections,
            provenance=prov,
            total_detections=len(detections),
        )


# ---------------------------------------------------------------------------
# Factory — choose provider by config; fallback to demo when live unavailable
# ---------------------------------------------------------------------------
def get_provider(preferred: Optional[str] = None) -> SARDataProvider:
    """
    Provider selection:

      preferred == "bhoonidhi"  → BhoonidhiSARProvider (may return UNAVAILABLE if not configured)
      preferred == "demo"       → DemoSARProvider (always deterministic)
      preferred == None/"auto"  → Bhoonidhi if available else Demo (graceful fallback, but provenance still honest)
    """
    pref = (preferred or os.getenv("ORCA_SAR_PROVIDER", "auto")).strip().lower()
    if pref == "demo":
        return DemoSARProvider()
    if pref == "bhoonidhi":
        return BhoonidhiSARProvider()
    # auto: try live, fall back to demo but keep honest provenance about the fallback
    # For SIH demo, auto with no credentials → demo
    b = BhoonidhiSARProvider()
    if b.is_available():
        return b
    return DemoSARProvider()
