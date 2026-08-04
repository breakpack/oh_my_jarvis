from fastapi.testclient import TestClient
from personal_ai_api.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "version": "0.1.0"}
