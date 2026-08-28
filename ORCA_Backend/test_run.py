"""
Quick end-to-end test -- runs the LangGraph-orchestrated agent pipeline
against sample queries covering every specialist (Ocean-State, Hazard, PFZ,
Geospatial) plus multilingual input, and prints the full response including
the explainability trace and each agent's reasoning note.

Run with: python3 test_run.py
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows cp1252-safe

from models import Location
from orchestrator import Orchestrator

# (query, device_gps, destination)
SAMPLE_QUERIES = [
    ("Is it safe to go fishing near Ratnagiri tomorrow morning?", None, None),
    ("Where is the nearest potential fishing zone near Kochi today?", None, None),
    (
        "What is the safest route for my boat? I am 10 km off the Odisha coast.",
        [19.90, 85.60],                       # device GPS at sea
        Location(name="Gopalpur Offshore", lat=19.55, lon=84.95),
    ),
    ("Am I close to any restricted maritime boundary?", [9.35, 79.85], None),  # near IMBL
    ("Is it safe to venture into the sea near Kochi today?", None, None),
    # Free-text place NOT in any hardcoded table -- exercises live geocoding:
    ("Is it safe to go fishing near Gopalpur tomorrow morning?", None, None),
    ("उद्या सकाळी मासेमारीसाठी जाणं सुरक्षित आहे का?", None, None),  # Marathi: safety tomorrow morning
]


def main():
    orchestrator = Orchestrator()

    for q, gps, dest in SAMPLE_QUERIES:
        print("=" * 80)
        print(f"QUERY: {q}")
        if gps:
            print(f"DEVICE GPS: {gps}")
        if dest:
            print(f"DESTINATION: {dest.name} ({dest.lat}, {dest.lon})")
        print("-" * 80)

        response = orchestrator.handle_query(q, device_gps=tuple(gps) if gps else None,
                                             destination=dest)

        print(f"LANGUAGE : {response.language}")
        print(f"STATUS   : {response.status.value}")
        print(f"ANSWER   : {response.answer}")
        if response.conflicts:
            print("CONFLICTS FLAGGED BY SYNTHESIS AGENT:")
            for c in response.conflicts:
                print(f"   ! {c}")
        print("REASONING:")
        for r in response.reasoning:
            print(f"   - {r}")
        if response.pfz:
            p = response.pfz
            print(f"PFZ      : {p.distance_from_reference_km} km @ bearing {p.bearing_deg} deg "
                  f"-> ({p.center_lat}, {p.center_lon}) [{p.source.value}]")
        if response.geofence:
            g = response.geofence
            print(f"GEOFENCE : clear={g.clear}, nearest boundary {g.nearest_boundary_km} km")
            for h in g.hits:
                inside = "INSIDE" if h.inside_zone else f"{h.distance_to_boundary_km} km"
                print(f"   ! {h.zone_name} [{h.zone_type}] {inside}")
        if response.route:
            r = response.route
            print(f"ROUTE    : {r.estimated_distance_km} km via {len(r.waypoints)} waypoints; "
                  f"avoiding {len(r.avoided_zones)} zone(s)")
        if response.ocean_state and response.ocean_state.field_sources:
            print("FIELD PROVENANCE:")
            for key in ("sst_celsius", "wave_height_m", "wind_gust_kmh",
                        "chlorophyll_mg_m3", "tide_level_m"):
                src = response.ocean_state.field_sources.get(key, "?")
                marker = "SIM" if src == "simulated" else src[:14]
                print(f"   [{marker:<14}] {key:<18} = {getattr(response.ocean_state, key)}")
        print("AGENT CONVERSATION:")
        if response.ocean_state and response.ocean_state.reasoning_note:
            print(f"   [OceanState] {response.ocean_state.reasoning_note[:160]}...")
        if response.risk and response.risk.reasoning_note:
            print(f"   [Hazard]     {response.risk.reasoning_note[:160]}...")
        if response.pfz and response.pfz.reasoning_note:
            print(f"   [PFZ]        {response.pfz.reasoning_note[:160]}...")
        if response.geofence and response.geofence.reasoning_note:
            print(f"   [GeoSpatial] {response.geofence.reasoning_note[:160]}...")
        print("EXPLAINABILITY TRACE:")
        for t in response.trace:
            print(f"   [{t.agent_name}] {t.action} ({t.duration_ms:.0f}ms)")
        print()


if __name__ == "__main__":
    main()
