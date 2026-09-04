"""
Tourism Agent -- coordinates coastal POI discovery with live safety verdicts.

Workflow:
1. Fetch nearby POIs via CoastalPoiConnector.
2. For each POI, establish the local marine state via OceanStateAgent.
3. Use the OceanStateReading to determine a safety verdict via HazardAgent.
4. Merge these into a TourismPoi result.

Following the "honest data" philosophy: if any stage (POI fetch or safety check)
fails, the result is reported as unavailable rather than simulated.
"""

from __future__ import annotations
import logging
import time
from typing import Optional

from models import (
    AgentTrace,
    DataSource,
    Location,
    OceanStateReading,
    SafetyStatus,
    TourismPoi,
)
import data_connectors.coastal_poi as coastal_poi
from agents.ocean_state_agent import OceanStateAgent
from agents.hazard_agent import HazardAgent

logger = logging.getLogger("orca.tourism")

class TourismAgent:
    name = "TourismAgent"

    def __init__(self):
        # Instantiate dependencies
        self._ocean_agent = OceanStateAgent()
        self._hazard_agent = HazardAgent()

    def run(
        self,
        location: Location,
        time_window: str = "today",
        vessel_class: str = "small_fishing_boat",
    ) -> tuple[list[TourismPoi], AgentTrace]:
        start = time.perf_counter()

        try:
            # 1. Fetch POIs
            pois_raw = coastal_poi.get_coastal_pois(location.lat, location.lon)
        except coastal_poi.CoastalPoiUnavailableError as exc:
            logger.error("Coastal POI connector unavailable: %s", exc)
            return [], AgentTrace(
                agent_name=self.name,
                action="Attempted to fetch coastal POIs",
                result_summary=f"POI service unavailable: {exc}",
                data_sources=["unavailable"],
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        results: list[TourismPoi] = []

        # 2. Process each POI for safety
        for poi in pois_raw:
            poi_loc = Location(name=poi["name"], lat=poi["lat"], lon=poi["lon"])

            try:
                # Get Ocean State for this POI
                reading, _ = self._ocean_agent.run(poi_loc, time_window)

                # Get Hazard verdict based on that state
                risk, _ = self._hazard_agent.run(reading, vessel_class=vessel_class)

                results.append(TourismPoi(
                    name=poi["name"],
                    type=poi["type"],
                    lat=poi["lat"],
                    lon=poi["lon"],
                    status=risk.status,
                    reasoning=risk.headline,
                    confidence=risk.confidence,
                ))
            except Exception as exc:
                logger.warning("Safety check failed for POI %s: %s", poi["name"], exc)
                # If safety check fails, we still show the POI but with a caution/unavailable status
                results.append(TourismPoi(
                    name=poi["name"],
                    type=poi["type"],
                    lat=poi["lat"],
                    lon=poi["lon"],
                    status=SafetyStatus.CAUTION,
                    reasoning="Safety verdict unavailable for this location.",
                    confidence=0.0,
                ))

        duration_ms = (time.perf_counter() - start) * 1000
        trace = AgentTrace(
            agent_name=self.name,
            action="Fetched coastal POIs and merged live safety verdicts",
            result_summary=f"Found {len(results)} POIs; safety checks performed for each.",
            data_sources=[DataSource.LIVE, DataSource.DERIVED_LIVE],
            duration_ms=duration_ms,
        )

        return results, trace
