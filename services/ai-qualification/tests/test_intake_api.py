import uuid

from app.routers.intake import derive_idempotency_key
from tests.conftest import needs_db

PAYLOAD = {"name": "Sara", "email": "lead002@example.com", "message": "villa"}


def test_derived_key_is_stable_and_order_independent():
    a = derive_idempotency_key("form", {"a": 1, "b": 2})
    assert a == derive_idempotency_key("form", {"b": 2, "a": 1})
    assert a != derive_idempotency_key("email", {"a": 1, "b": 2})
    assert a.startswith("form:sha256:")


@needs_db
def test_claim_then_redelivery(db_client):
    first = db_client.post("/v1/intake/claim", json={"raw_payload": PAYLOAD,
                                                      "idempotency_key": "evt-1"}).json()
    assert (first["duplicate"], first["proceed"], first["status"]) == (False, True, "processing")
    again = db_client.post("/v1/intake/claim", json={"raw_payload": PAYLOAD,
                                                      "idempotency_key": "evt-1"}).json()
    assert again["event_id"] == first["event_id"]
    assert again["correlation_id"] == first["correlation_id"]
    assert (again["duplicate"], again["proceed"], again["delivery_count"]) == (True, True, 2)


@needs_db
def test_completed_event_is_not_processed_again(db_client):
    claim = db_client.post("/v1/intake/claim", json={"raw_payload": PAYLOAD}).json()
    r = db_client.post(f"/v1/intake/{claim['event_id']}/status",
                       json={"status": "completed", "odoo_lead_id": 7})
    assert r.status_code == 200
    again = db_client.post("/v1/intake/claim", json={"raw_payload": PAYLOAD}).json()
    assert (again["duplicate"], again["proceed"], again["odoo_lead_id"]) == (True, False, 7)


@needs_db
def test_failed_event_can_be_retried(db_client):
    claim = db_client.post("/v1/intake/claim", json={"raw_payload": PAYLOAD}).json()
    db_client.post(f"/v1/intake/{claim['event_id']}/status",
                   json={"status": "failed", "error": "Odoo unavailable"})
    assert db_client.post("/v1/intake/claim", json={"raw_payload": PAYLOAD}).json()["proceed"]


@needs_db
def test_unknown_event_status_is_404(db_client):
    r = db_client.post(f"/v1/intake/{uuid.uuid4()}/status", json={"status": "completed"})
    assert r.status_code == 404
