import sys
import os

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_root_health_check():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]
    assert "database" in data
    assert data["project"] == "Campus OD"
    assert "Sri Krishna Arts and Science College" in data["institution"]

def test_v1_status():
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert data["version"] == "v1"

if __name__ == "__main__":
    test_root_health_check()
    print("test_root_health_check passed!")
    test_v1_status()
    print("test_v1_status passed!")
