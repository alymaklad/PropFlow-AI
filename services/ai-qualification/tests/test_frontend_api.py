import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.routers import public
from tests.conftest import ROOT, TEST_API_KEY, TEST_DATABASE_URL, TEST_WEBHOOK_SECRET, needs_db

SEED = (ROOT / "database" / "seeds" / "properties.sql").read_text()
STAFF = "staff-test-token"


@pytest.fixture
def web(migrated_db, monkeypatch):
    migrated_db.execute(SEED)
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=TEST_DATABASE_URL, api_key=TEST_API_KEY, llm_provider="fake",
        webhook_hmac_secret=TEST_WEBHOOK_SECRET, staff_token=STAFF)
    forwarded = []
    monkeypatch.setattr(public, "forward_to_intake",
                        lambda s, payload, **kw: forwarded.append((payload, kw)) or (202, {}))
    public._hits.clear()
    yield {"client": TestClient(app), "forwarded": forwarded, "db": migrated_db}
    app.dependency_overrides.clear()


def inquiry(**kw):
    return {"submission_id": str(uuid.uuid4()), "name": "Sara Hassan",
            "email": "sara@example.com", "property_type": "villa", "location": "Sheikh Zayed",
            "bedrooms": 4, "budget_max": 15_000_000, "timeline": "within_3_months",
            "purchase_stage": "ready_to_buy", "message": "Garden please", **kw}


@needs_db
def test_listings_are_verified_and_filterable(web):
    body = web["client"].get("/public/listings").json()
    ids = {item["listing_id"] for item in body["listings"]}
    assert "NC-APT-105" not in ids and "NC-APT-106" not in ids and "SZ-VIL-205" not in ids
    assert body["freshness_days"] == 14 and "Sheikh Zayed" in body["locations"]
    zayed = web["client"].get("/public/listings", params={
        "location": "Sheikh Zayed", "property_type": "villa", "bedrooms": 4,
        "budget_max": 15_000_000}).json()["listings"]
    assert [x["listing_id"] for x in zayed] == ["SZ-VIL-202", "SZ-VIL-201"]


@needs_db
def test_inquiry_is_forwarded_once_per_submission(web):
    payload = inquiry()
    r = web["client"].post("/public/inquiries", json=payload)
    assert r.status_code == 202 and r.json()["reference"] == payload["submission_id"][:8].upper()
    (sent, kw), = web["forwarded"]
    assert sent["source"] == "form" and sent["budget_max"] == 15_000_000
    assert "website" not in sent and "submission_id" not in sent
    assert kw == {"source": "form", "idempotency_key": f"web:{payload['submission_id']}"}


@needs_db
def test_inquiry_validation_messages(web):
    r = web["client"].post("/public/inquiries", json=inquiry(email=None, phone=None))
    assert r.status_code == 422
    assert r.json()["errors"][0]["field"] == "email"
    bad = web["client"].post("/public/inquiries", json=inquiry(email="sara@"))
    assert bad.status_code == 422 and "email address" in bad.json()["errors"][0]["message"]
    assert web["forwarded"] == []


@needs_db
def test_honeypot_is_accepted_silently(web):
    r = web["client"].post("/public/inquiries", json=inquiry(website="http://spam"))
    assert r.status_code == 202 and web["forwarded"] == []


@needs_db
def test_rate_limit(web):
    for _ in range(5):
        assert web["client"].post("/public/inquiries", json=inquiry()).status_code == 202
    assert web["client"].post("/public/inquiries", json=inquiry()).status_code == 429


@needs_db
def test_intake_down_is_a_clear_error(web, monkeypatch):
    monkeypatch.setattr(public, "forward_to_intake", lambda *a, **k: (502, {}))
    r = web["client"].post("/public/inquiries", json=inquiry())
    assert r.status_code == 503 and "Try again" in r.json()["detail"]


@needs_db
def test_staff_requires_token(web):
    c = web["client"]
    assert c.get("/staff/session").status_code == 401
    assert c.get("/staff/session", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/staff/session", headers={"Authorization": f"Bearer {STAFF}"}).json() == \
        {"ok": True}


@needs_db
def test_staff_views(web):
    db, h = web["db"], {"Authorization": f"Bearer {STAFF}"}
    eid = db.execute("INSERT INTO intake_events (idempotency_key, source, raw_payload,"
                     " odoo_lead_id, status) VALUES ('k', 'form', '{\"name\": \"Sara\"}', 7,"
                     " 'completed') RETURNING id").fetchone()[0]
    db.execute("INSERT INTO escalations (event_id, reason, assigned_to, priority, due_at,"
               " odoo_lead_id) VALUES (%s, 'no_matching_property', 'Rep', 'high', %s, 7)",
               (eid, datetime.now(UTC) - timedelta(hours=1)))
    db.execute("INSERT INTO dead_letters (workflow, payload, error) VALUES ('scheduler', '{}',"
               " 'boom')")
    handoff, = web["client"].get("/staff/handoffs", headers=h).json()
    assert handoff["overdue"] and handoff["customer"] == "Sara"
    assert handoff["reasons"] == ["no listing in the catalog fits"]
    lead, = web["client"].get("/staff/leads", headers=h).json()
    assert lead["handed_off"] and lead["lead_url"].endswith("id=7&model=crm.lead&view_type=form")
    dl, = web["client"].get("/staff/dead-letters", headers=h).json()
    assert dl["replayable"] is False
    r = web["client"].post(f"/staff/dead-letters/{dl['id']}/discard", headers=h,
                           json={"reason": "scheduler reran"})
    assert r.json()["status"] == "discarded"


def test_staff_fails_closed_without_configured_token():
    app.dependency_overrides[get_settings] = lambda: Settings(None, None, "fake")
    try:
        assert TestClient(app).get("/staff/session").status_code == 503
    finally:
        app.dependency_overrides.clear()



@needs_db
def test_public_config_and_daily_cap(migrated_db, monkeypatch):
    migrated_db.execute(SEED)
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=TEST_DATABASE_URL, api_key=TEST_API_KEY, llm_provider="fake",
        webhook_hmac_secret=TEST_WEBHOOK_SECRET, demo_mode=True, public_daily_limit=2,
        mail_viewer_path="/mail/")
    monkeypatch.setattr(public, "forward_to_intake", lambda *a, **k: (202, {}))
    public._hits.clear()
    try:
        client = TestClient(app)
        assert client.get("/public/config").json() == {"demo": True, "mail_viewer": "/mail/"}
        for n in range(2):
            migrated_db.execute("INSERT INTO intake_events (idempotency_key, source, raw_payload)"
                                " VALUES (%s, 'form', '{}')", (f"web:{n}",))
        r = client.post("/public/inquiries", json=inquiry())
        assert r.status_code == 429 and "today's inquiry limit" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_public_config_outside_demo():
    app.dependency_overrides[get_settings] = lambda: Settings(None, None, "fake")
    try:
        assert TestClient(app).get("/public/config").json() == {"demo": False,
                                                               "mail_viewer": None}
    finally:
        app.dependency_overrides.clear()
