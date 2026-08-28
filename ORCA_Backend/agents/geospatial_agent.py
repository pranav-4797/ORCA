"""
Geospatial Reasoning Agent

Two related jobs under one agent (per project documentation Section 8):

1. GEOFENCE -- check the user's stated/GPS position against the static
   boundary database (`data/marine_boundaries.geojson`): International
   Maritime Boundary Line segments digitized from published bilateral
   treaties, and Marine Protected Area buffers. Tier 2: real, static,
   clearly labeled simplified geometry. Point-in-polygon and distance
   math are implemented here in pure Python (no GDAL dependency).

2. ROUTE -- plan a safe route from the user's own live device GPS to a
   destination, detouring around restricted zones flagged by this agent
   and hazard zones passed in from sibling agents. The bathymetry grid
   (GEBCO) lookup is an explicit TODO; the geometry is real.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from heapq import heappush, heappop

import data_connectors.bathymetry as bathymetry
import llm_client
from models import (
    AgentTrace,
    DataSource,
    GeofenceStatus,
    Location,
    RestrictedZoneHit,
    RoutePlan,
)
_ENABLE_LLM_NOTE = os.getenv("ORCA_ENABLE_LLM_REASONING", "").strip().lower() in ("1", "true", "yes")

logger = logging.getLogger("orca.geospatial")

_BOUNDARIES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "marine_boundaries.geojson")
_APPROACH_BUFFER_KM = 15.0  # "approaching a boundary" alert buffer
_ROUTE_SAMPLE_KM = 5.0      # waypoint sampling interval for zone checks
_ASTAR_CELL_KM = 4.0        # A* grid resolution
_ASTAR_MIN_DEPTH_M = 10.0   # cells shallower than this are blocked (small craft)
_ASTAR_MAX_CELLS = 120_000  # hard cap on grid size before falling back


def _load_boundaries() -> list[dict]:
    try:
        with open(_BOUNDARIES_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("features", [])
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Could not load boundary database: %s", exc)
        return []


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _point_in_ring(lat, lon, ring: list[list[float]]) -> bool:
    """Ray casting. ring coords are [lon, lat] pairs."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and \
                (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _dist_to_segment_km(lat, lon, a: list[float], b: list[float]) -> float:
    """Approximate distance from point to segment [lon,lat]-[lon,lat]."""
    # Work in local flat projection (fine at these scales).
    k = 111.32
    px = (lon - a[0]) * k * math.cos(math.radians(lat))
    py = (lat - a[1]) * k
    qx = (b[0] - a[0]) * k * math.cos(math.radians((a[1] + b[1]) / 2))
    qy = (b[1] - a[1]) * k
    seg2 = qx * qx + qy * qy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, (px * qx + py * qy) / seg2))
    dx = px - t * qx
    dy = py - t * qy
    return math.hypot(dx, dy)


class GeospatialAgent:
    name = "GeospatialAgent"

    def __init__(self):
        self._features = _load_boundaries()
        self._route_zone_labels: dict[str, bool] = {}

    # ------------------------------------------------------------------
    def run(
        self,
        location: Location,
        device_gps: tuple | None = None,
        destination: Location | None = None,
        hazard_zone_names: list[str] | None = None,
    ) -> tuple[tuple[GeofenceStatus, RoutePlan | None], AgentTrace]:
        start = time.perf_counter()
        ref_lat, ref_lon = device_gps or (location.lat, location.lon)

        geofence = self._check_geofence(ref_lat, ref_lon, location)

        route: RoutePlan | None = None
        if destination is not None:
            route = self._plan_route(
                ref_lat, ref_lon, destination.lat, destination.lon,
                restricted=[h.zone_name for h in geofence.hits],
                hazard_names=hazard_zone_names or [],
            )

        geofence.reasoning_note = self._generate_reasoning_note(geofence, route)

        duration_ms = (time.perf_counter() - start) * 1000
        summary_bits = []
        if geofence.clear:
            summary_bits.append("no restricted boundary within buffer")
        else:
            near = min(geofence.hits, key=lambda h: h.distance_to_boundary_km)
            summary_bits.append(f"NEAR/IN {near.zone_name} ({near.distance_to_boundary_km} km)")
        if route:
            depth_txt = (
                f", min depth {route.min_depth_m} m" if route.min_depth_m is not None else ""
            )
            summary_bits.append(
                f"route {route.estimated_distance_km:.0f} km [{route.algorithm}]"
                f"{depth_txt}, {len(route.avoided_zones)} zone(s) avoided"
            )
        trace = AgentTrace(
            agent_name=self.name,
            action="Checked boundaries"
            + (" and planned safe route (A* + ETOPO depth)" if route else ""),
            result_summary=f"{len(self._features)} zones checked: " + "; ".join(summary_bits),
            data_sources=[DataSource.STATIC_DERIVED]
            + ([DataSource.DERIVED_LIVE] if route else []),
            duration_ms=duration_ms,
        )
        return (geofence, route), trace

    # ------------------------------------------------------------------
    # Geofence check
    # ------------------------------------------------------------------
    def check_geofence_public(self, lat: float, lon: float,
                              location: Location) -> GeofenceStatus:
        """Public wrapper used by the Proactive Monitor Agent."""
        return self._check_geofence(lat, lon, location)

    def _check_geofence(self, lat: float, lon: float, location: Location) -> GeofenceStatus:
        hits: list[RestrictedZoneHit] = []
        nearest = float("inf")
        for feat in self._features:
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})
            name, ztype = props.get("name", "?"), props.get("zone_type", "?")

            if geom.get("type") == "Polygon":
                rings = geom.get("coordinates", [])
                inside = bool(rings) and _point_in_ring(lat, lon, rings[0])
                dist = min(
                    _dist_to_segment_km(lat, lon, rings[0][i], rings[0][(i + 1) % len(rings[0])])
                    for i in range(len(rings[0]))
                ) if rings else float("inf")
            elif geom.get("type") == "LineString":
                pts = geom.get("coordinates", [])
                inside = False
                dist = (
                    min(_dist_to_segment_km(lat, lon, pts[i], pts[i + 1])
                        for i in range(len(pts) - 1))
                    if len(pts) >= 2 else float("inf")
                )
            else:
                continue

            dist = round(float(dist), 1)
            nearest = min(nearest, dist)
            if inside or dist <= _APPROACH_BUFFER_KM:
                hits.append(RestrictedZoneHit(
                    zone_name=name,
                    zone_type=ztype,
                    inside_zone=inside,
                    distance_to_boundary_km=0.0 if inside else dist,
                ))

        return GeofenceStatus(
            reference_location=location,
            hits=hits,
            nearest_boundary_km=nearest if math.isfinite(nearest) else 999.9,
            clear=not hits,
            reasoning_note="",  # filled by LLM layer below
        )

    # ------------------------------------------------------------------
    # Safe-route planning: A* over a local grid with real bathymetry +
    # restricted/hazard-zone penalties; sampled-detour fallback when the
    # grid would be too large or depth data is unavailable.
    # ------------------------------------------------------------------
    def _plan_route(
        self,
        start_lat: float, start_lon: float,
        end_lat: float, end_lon: float,
        restricted: list[str],
        hazard_names: list[str],
    ) -> RoutePlan:
        route = self._astar_route(start_lat, start_lon, end_lat, end_lon)
        if route is None:
            route = self._detour_route(start_lat, start_lon, end_lat, end_lon,
                                       restricted, hazard_names)
        avoided = list(dict.fromkeys(route.avoided_zones))
        avoided.extend(h for h in hazard_names if h not in avoided)
        route.avoided_zones = avoided
        return route

    def _detour_route(
        self,
        start_lat: float, start_lon: float,
        end_lat: float, end_lon: float,
        restricted: list[str],
        hazard_names: list[str],
    ) -> RoutePlan:
        total = _haversine_km(start_lat, start_lon, end_lat, end_lon)
        n_steps = max(2, int(total / _ROUTE_SAMPLE_KM))
        waypoints = [(round(start_lat, 4), round(start_lon, 4))]
        avoided: list[str] = []

        # Sample the direct line; where it clips a restricted zone,
        # push the midpoint sideways perpendicular to the leg as a simple
        # avoidance detour (fallback vs full A*).
        for i in range(1, n_steps):
            f = i / n_steps
            lat = start_lat + (end_lat - start_lat) * f
            lon = start_lon + (end_lon - start_lon) * f
            status = self._check_geofence(lat, lon, Location(name="waypoint", lat=lat, lon=lon))
            clipped = [h.zone_name for h in status.hits]
            if clipped:
                avoided.extend(z for z in clipped if z not in avoided)
                offset_deg = 90.0 if _bearing_deg(start_lat, start_lon, end_lat, end_lon) <= 180 else -90.0
                rad = math.radians(offset_deg)
                waypoints.append((
                    round(lat + 0.09 * math.cos(rad), 4),
                    round(lon + 0.09 * math.sin(rad), 4),
                ))
            else:
                waypoints.append((round(lat, 4), round(lon, 4)))

        waypoints.append((round(end_lat, 4), round(end_lon, 4)))
        avoided.extend(h for h in hazard_names if h not in avoided)

        return RoutePlan(
            start_lat=start_lat,
            start_lon=start_lon,
            dest_lat=end_lat,
            dest_lon=end_lon,
            waypoints=waypoints,
            avoided_zones=avoided,
            estimated_distance_km=round(sum(
                _haversine_km(*waypoints[i], *waypoints[i + 1])
                for i in range(len(waypoints) - 1)
            ), 1),
            algorithm="sampled-detour",
        )

    # ------------------------------------------------------------------
    def _astar_route(self, start_lat: float, start_lon: float,
                     end_lat: float, end_lon: float) -> RoutePlan | None:
        """A* over a local lat/lon grid avoiding restricted zones and
        shallow water (real ETOPO depth checks).

        Returns None when the problem is too large or the depth feed is
        unavailable -- the caller falls back to the sampled detour.
        """
        total_km = _haversine_km(start_lat, start_lon, end_lat, end_lon)
        # Keep A* bounded: long routes would need big grids AND many
        # per-cell geofence checks -- the sampled detour handles those.
        if total_km > 250:
            logger.info("A* skipped: %.0f km leg exceeds 250 km bound", total_km)
            return None
        self._route_zone_labels = {}
        span_km = total_km + 2 * _ASTAR_CELL_KM * 8   # room to go around
        cells_per_side = int(span_km / _ASTAR_CELL_KM)
        if cells_per_side < 3 or cells_per_side ** 2 > _ASTAR_MAX_CELLS:
            logger.info("A* skipped: grid %dx%d too small/large", cells_per_side, cells_per_side)
            return None

        mid_lat = (start_lat + end_lat) / 2
        dlat_cell = _ASTAR_CELL_KM / 111.0
        dlon_cell = _ASTAR_CELL_KM / (111.0 * max(math.cos(math.radians(mid_lat)), 0.2))

        nlat = cells_per_side

        def to_cell(lat: float, lon: float) -> tuple[int, int]:
            ci = round((lat - min(start_lat, end_lat)) / dlat_cell)
            cj = round((lon - min(start_lon, end_lon)) / dlon_cell)
            return max(0, min(nlat - 1, ci)), max(0, min(cells_per_side - 1, cj))

        def to_coords(cell: tuple[int, int]) -> tuple[float, float]:
            return (
                round(min(start_lat, end_lat) + cell[0] * dlat_cell, 4),
                round(min(start_lon, end_lon) + cell[1] * dlon_cell, 4),
            )

        start_cell = to_cell(start_lat, start_lon)
        goal_cell = to_cell(end_lat, end_lon)

        # --- blocked/penalised cells -----------------------------------
        blocked: set[tuple[int, int]] = set()
        penalty: dict[tuple[int, int], float] = {}
        coords_all = [to_coords((i, j)) for i in range(nlat)
                      for j in range(cells_per_side)]

        # Depth checks: batch through the connector (failures -> fallback).
        try:
            depths = bathymetry.get_depths_batch(coords_all)
        except Exception as exc:
            logger.warning("bathymetry unavailable (%s); A* skipped", exc)
            return None
        if len(depths) < len(coords_all) * 0.5:
            logger.info("bathymetry coverage too low (%s/%s cells); A* skipped",
                        len(depths), len(coords_all))
            return None

        shallow_count = 0
        for idx, (la, lo) in enumerate(coords_all):
            key = (round(la, 4), round(lo, 4))
            d = depths.get(key)
            if d is None:
                continue
            if d > -_ASTAR_MIN_DEPTH_M:      # land or shallower than safe draft
                cell = (idx // cells_per_side, idx % cells_per_side)
                blocked.add(cell)
                shallow_count += 1
        logger.info("A* grid: %d cells, %d blocked as land/shallow",
                    len(coords_all), shallow_count)

        for i in range(nlat):
            for j in range(cells_per_side):
                la, lo = to_coords((i, j))
                gf = self._check_geofence(la, lo, Location(name="cell", lat=la, lon=lo))
                if any(h.inside_zone for h in gf.hits):
                    blocked.add((i, j))
                    for h in gf.hits:
                        if h.zone_name not in self._route_zone_labels:
                            self._route_zone_labels[h.zone_name] = True
                elif not gf.clear:
                    penalty[(i, j)] = _APPROACH_BUFFER_KM  # discourage but allow

        if start_cell in blocked or goal_cell in blocked:
            logger.info("start/goal cell blocked; A* skipped")
            return None

        # --- A* search --------------------------------------------------
        def h_cost(cell: tuple[int, int]) -> float:
            la, lo = to_coords(cell)
            return _haversine_km(la, lo, end_lat, end_lon)

        open_heap: list[tuple[float, float, tuple[int, int]]] = []
        heappush(open_heap, (h_cost(start_cell), 0.0, start_cell))
        g_score: dict[tuple[int, int], float] = {start_cell: 0.0}
        came: dict[tuple[int, int], tuple[int, int]] = {}
        closed: set[tuple[int, int]] = set()

        neighbours = [(-1, 0), (1, 0), (0, -1), (0, 1),
                      (-1, -1), (-1, 1), (1, -1), (1, 1)]
        found = False
        while open_heap:
            _f, g, cur = heappop(open_heap)
            if cur == goal_cell:
                found = True
                break
            if cur in closed:
                continue
            closed.add(cur)
            ci, cj = cur
            for di, dj in neighbours:
                ni, nj = ci + di, cj + dj
                if not (0 <= ni < nlat and 0 <= nj < cells_per_side):
                    continue
                nxt = (ni, nj)
                if nxt in blocked or nxt in closed:
                    continue
                a = to_coords(cur)
                b = to_coords(nxt)
                step_cost = _haversine_km(*a, *b)
                step_cost *= 1.414 if (di and dj) else 1.0
                step_cost += penalty.get(nxt, 0.0)
                ng = g + step_cost
                if ng < g_score.get(nxt, float("inf")):
                    g_score[nxt] = ng
                    came[nxt] = cur
                    heappush(open_heap, (ng + h_cost(nxt), ng, nxt))

        if not found:
            logger.info("A* found no path; falling back to detour planner")
            return None

        # Reconstruct.
        path_cells = [goal_cell]
        while path_cells[-1] != start_cell:
            path_cells.append(came[path_cells[-1]])
        path_cells.reverse()
        coords_path = [to_coords(c) for c in path_cells]

        # Thin collinear-ish points to keep waypoint lists sane.
        waypoints: list[tuple[float, float]] = [coords_path[0]]
        min_sep = _ROUTE_SAMPLE_KM
        for pt in coords_path[1:-1]:
            if _haversine_km(*waypoints[-1], *pt) >= min_sep:
                waypoints.append(pt)
        waypoints.append(coords_path[-1])

        depths_along = [
            depths.get((round(la, 4), round(lo, 4))) for la, lo in coords_path
            if depths.get((round(la, 4), round(lo, 4))) is not None
        ]
        min_depth = min(depths_along) if depths_along else None
        shallow_seg = sum(1 for d in depths_along if d > -_ASTAR_MIN_DEPTH_M)

        avoided = sorted(self._route_zone_labels.keys())
        return RoutePlan(
            start_lat=start_lat,
            start_lon=start_lon,
            dest_lat=end_lat,
            dest_lon=end_lon,
            waypoints=waypoints,
            avoided_zones=avoided,
            estimated_distance_km=round(sum(
                _haversine_km(*waypoints[i], *waypoints[i + 1])
                for i in range(len(waypoints) - 1)
            ), 1),
            bathymetry_source=(
                "ETOPO1 via NOAA CoastWatch ERDDAP (live, keyless)"
                if min_depth is not None else "unavailable"
            ),
            min_depth_m=min_depth,
            shallow_segments=shallow_seg,
            algorithm="a-star",
        )

    # ------------------------------------------------------------------
    def _generate_reasoning_note(self, gf: GeofenceStatus, route: RoutePlan | None) -> str:
        hits_text = (
            "; ".join(
                f"{h.zone_name} ({'INSIDE' if h.inside_zone else f'{h.distance_to_boundary_km} km away'})"
                for h in gf.hits
            )
            if gf.hits else "none within buffer"
        )
        # Deterministic note by default
        base = f"Nearest restricted boundary {gf.nearest_boundary_km} km; flags: {hits_text}. Boundary data is static/simplified treaty lines."
        if route:
            base += f" Route {route.estimated_distance_km} km via {len(route.waypoints)} waypoints avoiding {', '.join(route.avoided_zones) or 'nothing'}."
        if not _ENABLE_LLM_NOTE:
            return base
        route_text = (
            f"\nRoute planned: {route.estimated_distance_km} km via "
            f"{len(route.waypoints)} waypoints; avoiding: "
            f"{', '.join(route.avoided_zones) or 'nothing'}"
            if route else "\nNo route requested."
        )
        system_prompt = (
            "You are the Geospatial Reasoning Agent of ORCA. You just ran geofence "
            "checks against treaty-digitized IMBL lines and marine protected area "
            "boundaries (static, simplified data), possibly planning a route. Write "
            "2-3 sentences to the Synthesis Agent like a colleague: state clearly "
            "whether anything restricted is close, and that boundary data is static/"
            "simplified. Use ONLY provided values."
        )
        user_prompt = (
            f"Nearest boundary: {gf.nearest_boundary_km} km.\n"
            f"Flags: {hits_text}.{route_text}\n\nWrite your note."
        )
        try:
            return llm_client.complete(system_prompt, user_prompt, temperature=0.4, max_tokens=250,
                                       timeout=7, attempts=1)
        except llm_client.LLMUnavailableError:
            return base
