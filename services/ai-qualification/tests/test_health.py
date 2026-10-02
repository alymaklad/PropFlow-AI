def test_healthz_is_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_without_database_is_not_ready(client):
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["checks"]["database"] == "not_configured"
