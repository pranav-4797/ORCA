"""
Unit test for ORCA /health endpoint.
Verifies:
1. GET /health returns HTTP 200.
2. Response is JSON.
3. Response body is {"status": "ok"}.
4. Endpoint responds without requiring auth headers.
"""

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def test_health_endpoint():
    # Test GET
    get_res = client.get("/health")
    assert get_res.status_code == 200, f"GET expected 200, got {get_res.status_code}"
    data = get_res.json()
    assert data == {"status": "ok"}, f"Expected {{'status': 'ok'}}, got {data}"
    print("[PASS] GET /health returned 200 OK with payload {'status': 'ok'}")

    # Test HEAD (used by UptimeRobot by default)
    head_res = client.head("/health")
    assert head_res.status_code == 200, f"HEAD expected 200, got {head_res.status_code}"
    print("[PASS] HEAD /health returned 200 OK")


if __name__ == "__main__":
    test_health_endpoint()
