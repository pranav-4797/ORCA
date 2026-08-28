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
    response = client.get("/health")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data == {"status": "ok"}, f"Expected {{'status': 'ok'}}, got {data}"
    print("[PASS] Health check test passed: status=200, payload={'status': 'ok'}")


if __name__ == "__main__":
    test_health_endpoint()
