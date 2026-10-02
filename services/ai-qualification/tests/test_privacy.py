import json

from tests.conftest import needs_db


def _seed(conn):
    payload = {"name": "Sara", "email": "sara@example.com", "phone": "0100-000-0002",
               "message": "villa"}
    eid, cid = conn.execute(
        "INSERT INTO intake_events (idempotency_key, source, raw_payload, odoo_lead_id)"
        " VALUES ('k1', 'form', %s, 42) RETURNING id, correlation_id",
        (json.dumps(payload),)).fetchone()
    conn.execute("INSERT INTO intake_events (idempotency_key, source, raw_payload)"
                 " VALUES ('k2', 'form', '{\"email\": \"other@example.com\"}')")
    conn.execute("INSERT INTO qualifications (event_id, model, prompt_version, raw_output,"
                 " validation_status) VALUES (%s, 'm', 'v', 'Sara wants a villa', 'valid')",
                 (eid,))
    conn.execute("INSERT INTO outbound_messages (lead_ref, channel, template, to_address)"
                 " VALUES (%s, 'email', 'customer_shortlist', 'sara@example.com')", (str(cid),))
    conn.execute("INSERT INTO followup_sequences (odoo_lead_id, correlation_id, to_email)"
                 " VALUES (42, %s, 'sara@example.com')", (cid,))
    conn.execute("INSERT INTO consents VALUES ('sara@example.com', 'email', 'opted_out',"
                 " 'reply', now())")
    return eid


@needs_db
def test_erase_by_email(db_client, migrated_db):
    eid = _seed(migrated_db)
    r = db_client.post("/v1/privacy/erase", json={"contact": "Sara@Example.com"})
    assert r.status_code == 200
    body = r.json()
    assert (body["events_erased"], body["messages_scrubbed"], body["sequences_deleted"],
            body["opt_out_kept"], body["odoo_lead_ids"]) == (1, 1, 1, True, [42])
    raw, = migrated_db.execute("SELECT raw_payload FROM intake_events WHERE id = %s",
                               (eid,)).fetchone()
    assert raw == {"erased": True}
    assert migrated_db.execute("SELECT raw_output FROM qualifications").fetchone() == (None,)
    assert migrated_db.execute("SELECT count(*) FROM intake_events WHERE raw_payload->>'email'"
                               " = 'other@example.com'").fetchone() == (1,)  # untouched


@needs_db
def test_erase_by_phone_in_any_format(db_client, migrated_db):
    _seed(migrated_db)
    body = db_client.post("/v1/privacy/erase", json={"contact": "+20 100 000 0002"}).json()
    assert body["events_erased"] == 1


@needs_db
def test_erase_rejects_garbage(db_client, migrated_db):
    assert db_client.post("/v1/privacy/erase", json={"contact": "nobody"}).status_code == 422


@needs_db
def test_retention_keeps_counts_and_recent_data(db_client, migrated_db):
    eid = _seed(migrated_db)
    migrated_db.execute("UPDATE intake_events SET received_at = now() - interval '40 days'"
                        " WHERE id = %s", (eid,))
    migrated_db.execute("UPDATE qualifications SET created_at = now() - interval '40 days'")
    body = db_client.post("/v1/privacy/retention", json={"older_than_days": 30}).json()
    assert (body["events_anonymised"], body["qualifications_cleared"]) == (1, 1)
    assert migrated_db.execute("SELECT count(*) FROM intake_events").fetchone() == (2,)
    assert migrated_db.execute("SELECT raw_payload->>'email' FROM intake_events WHERE"
                               " idempotency_key = 'k2'").fetchone() == ("other@example.com",)
    assert db_client.post("/v1/privacy/retention", json={"older_than_days": 3}).status_code == 422
