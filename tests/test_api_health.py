from fastapi.testclient import TestClient

from commercelens.api.main import app


def test_health_reports_version() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.9.0"


def test_readiness_reports_store_and_auth(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMMERCELENS_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("COMMERCELENS_JOBS_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("COMMERCELENS_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("COMMERCELENS_ADMIN_TOKEN", "secret")
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["store_backend"] == "sqlite"
    assert payload["api_key_required"] is True
    assert payload["admin_token_configured"] is True
