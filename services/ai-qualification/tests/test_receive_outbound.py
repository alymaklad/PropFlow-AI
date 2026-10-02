import json
import time
import uuid

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.deps import get_odoo
from app.main import app
from app.signing import sign
from tests.conftest import TEST_API_KEY, TEST_WEBHOOK_SECRET, needs_db
from tests.fake_odoo import FakeOdoo


def signed(body: str, **extra):
    ts = int(time.time())
    return {"raw_body": body, "timestamp": str(ts),
            "signature": sign(TEST_WEBHOOK_SECRET, ts, body), **extra}


BODY = json.dumps({"name": "Sara", "email": "lead002@example.com", "message": "villa"})


@needs_db
def test_receive_valid_signature_claims_event(db_client):
    r = db_client.post("/v1/intake/receive", json=signed(BODY))
    assert r.status_code == 200
    body = r.json()
    assert body["payload"]["name"] == "Sara" and body["proceed"] and not body["duplicate"]
    again = db_client.post("/v1/intake/receive", json=signed(BODY)).json()
    assert again["duplicate"] and again["event_id"] == body["event_id"]


@needs_db
def test_receive_bad_signature_is_401_and_not_stored(db_client, migrated_db):
    r = db_client.post("/v1/intake/receive",
                       json={"raw_body": BODY, "timestamp": str(int(time.time())),
                             "signature": "sha256=" + "0" * 64})
    assert r.status_code == 401
    assert migrated_db.execute("SELECT count(*) FROM intake_events").fetchone()[0] == 0


@needs_db
def test_receive_malformed_json_is_stored_as_rejected(db_client, migrated_db):
    r = db_client.post("/v1/intake/receive", json=signed("[1, 2"))
    assert r.status_code == 422
    state, error = migrated_db.execute("SELECT status, error FROM intake_events").fetchone()
    assert (state, error) == ("rejected", "malformed_json")


@needs_db
def test_receive_without_configured_secret_fails_closed(migrated_db):
    from tests.conftest import TEST_DATABASE_URL
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=TEST_DATABASE_URL, api_key=TEST_API_KEY, llm_provider="fake")
    try:
        client = TestClient(app, headers={"X-API-Key": TEST_API_KEY})
        assert client.post("/v1/intake/receive", json=signed(BODY)).status_code == 503
    finally:
        app.dependency_overrides.clear()


@needs_db
def test_outbound_claim_sends_once(db_client):
    msg = {"lead_ref": "cid-1", "template": "rep_high_priority"}
    first = db_client.post("/v1/outbound/claim", json=msg).json()
    assert first["send"] and first["status"] == "pending"
    # crash before marking sent: a retry must not resend
    assert not db_client.post("/v1/outbound/claim", json=msg).json()["send"]
    db_client.post(f"/v1/outbound/{first['message_id']}/status", json={"status": "sent"})
    again = db_client.post("/v1/outbound/claim", json=msg).json()
    assert (again["send"], again["status"], again["message_id"]) == \
        (False, "sent", first["message_id"])


@needs_db
def test_outbound_failed_message_can_be_retried_once(db_client):
    msg = {"lead_ref": "cid-2", "template": "rep_high_priority"}
    first = db_client.post("/v1/outbound/claim", json=msg).json()
    db_client.post(f"/v1/outbound/{first['message_id']}/status",
                   json={"status": "failed", "error": "SMTP down"})
    retry = db_client.post("/v1/outbound/claim", json=msg).json()
    assert retry["send"] and retry["status"] == "pending"
    assert not db_client.post("/v1/outbound/claim", json=msg).json()["send"]


@needs_db
def test_outbound_status_unknown_is_404(db_client):
    r = db_client.post(f"/v1/outbound/{uuid.uuid4()}/status", json={"status": "sent"})
    assert r.status_code == 404


@needs_db
def test_dead_letter_is_stored(db_client, migrated_db):
    r = db_client.post("/v1/dead-letters", json={
        "workflow": "PropFlow - Lead intake", "error": "Odoo rejected the request",
        "payload": {"execution_id": "42"}})
    assert r.status_code == 201
    row = migrated_db.execute("SELECT workflow, status, attempts FROM dead_letters").fetchone()
    assert row == ("PropFlow - Lead intake", "open", 1)


@needs_db
def test_upsert_endpoint_returns_owner_and_link(db_client, migrated_db):
    odoo = FakeOdoo()
    app.dependency_overrides[get_odoo] = lambda: odoo
    claim = db_client.post("/v1/intake/claim", json={"raw_payload": {"x": 1}}).json()
    lead = db_client.post("/v1/normalize", json={
        "name": "Sara", "email": "lead002@example.com", "property_type": "villa",
        "location": "Sheikh Zayed", "bedrooms": 4, "budget": "up to 15M",
        "timeline": "within_3_months", "purchase_stage": "ready_to_buy"}).json()
    score = db_client.post("/v1/score", json=lead).json()
    r = db_client.post("/v1/crm/leads/upsert", json={
        "correlation_id": claim["correlation_id"], "event_id": claim["event_id"],
        "lead": lead, "score": score})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "created"
    assert body["owner"] == {"id": 10, "name": "Rep 10", "email": "rep10@example.com"}
    assert body["lead_url"].endswith(f"/web#id={body['lead_id']}&model=crm.lead&view_type=form")
    ledger = migrated_db.execute(
        "SELECT e.odoo_lead_id, s.total FROM intake_events e JOIN score_results s"
        " ON s.event_id = e.id").fetchone()
    assert ledger == (body["lead_id"], 90)


@needs_db
def test_concurrent_outbound_claims_send_once(db_client):
    import threading

    msg = {"lead_ref": "cid-race", "template": "rep_high_priority"}
    results = []

    def worker():
        results.append(db_client.post("/v1/outbound/claim", json=msg).json()["send"])

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
