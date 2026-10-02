from fastapi.testclient import TestClient

from app.main import app


def test_v1_requires_api_key(client):
    anonymous = TestClient(app)
    assert anonymous.post("/v1/normalize", json={}).status_code == 401
    wrong = anonymous.post("/v1/score", json={}, headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401


def test_v1_fails_closed_without_configured_key():
    from app.config import Settings, get_settings
    app.dependency_overrides[get_settings] = lambda: Settings(None, None, "fake")
    try:
        r = TestClient(app).post("/v1/score", json={}, headers={"X-API-Key": ""})
        assert r.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_normalize_endpoint(client):
    r = client.post("/v1/normalize", json={
        "name": "Sara", "phone": "+20 100 000 0002", "message": "villa", "budget": "up to 15M",
        "location": "Sheikh Zayed", "property_type": "villa", "bedrooms": 4,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["phone"] == "+201000000002" and body["budget_max"] == 15_000_000


def test_normalize_invalid_lead_is_200_with_errors(client):
    r = client.post("/v1/normalize", json={"name": "No contact", "message": "hi"})
    assert r.status_code == 200
    assert r.json()["valid"] is False and r.json()["errors"] == ["contact_missing"]


def test_normalize_rejects_wrong_types(client):
    assert client.post("/v1/normalize", json={"source": "fax"}).status_code == 422


def test_score_endpoint(client):
    r = client.post("/v1/score", json={
        "budget_max": 15_000_000, "purchase_timeline_months": 2, "property_type": "villa",
        "location": "Sheikh Zayed", "bedrooms": 4, "purchase_intent": "high",
    })
    assert r.status_code == 200
    body = r.json()
    assert (body["total"], body["priority"], body["rules_version"]) == (90, "high", "reference-1")
    assert len(body["components"]) == 5


def test_correlation_id_is_echoed_or_generated(client):
    r = client.get("/healthz", headers={"X-Correlation-ID": "evt-123"})
    assert r.headers["X-Correlation-ID"] == "evt-123"
    generated = client.get("/healthz", headers={"X-Correlation-ID": "bad value!"})
    assert generated.headers["X-Correlation-ID"] != "bad value!"
    assert len(generated.headers["X-Correlation-ID"]) == 36
