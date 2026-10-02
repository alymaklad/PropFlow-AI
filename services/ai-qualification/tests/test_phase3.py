import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.business_time import BusinessCalendar
from app.deps import get_odoo
from app.email_intake import strip_quoted
from app.main import app
from app.routers import inbound
from app.routers.automation import get_calendar
from app.routers.outbound import prepare
from tests.conftest import needs_db
from tests.fake_odoo import FakeOdoo

CAIRO = ZoneInfo("Africa/Cairo")
CAL = BusinessCalendar(CAIRO, time(9), time(17), frozenset({6, 0, 1, 2, 3}))
NOW = datetime(2026, 10, 4, 10, 0, tzinfo=CAIRO)
REMINDER = {"name": "Sara", "requirements": {"location": "Maadi"}, "advisor_name": "Rep"}


# --- contact limits and ledger fields ----------

@needs_db
def test_daily_limit_per_customer_address(migrated_db):
    def send(n, limit=3):
        return prepare(migrated_db, lead_ref=f"cid-{n}", to_email="Lead002@example.com",
                       contact_keys=[], template="customer_reminder", sequence_no=1,
                       data=REMINDER, daily_limit=limit)
    assert [send(n).send for n in range(3)] == [True, True, True]
    blocked = send(3)
    assert (blocked.send, blocked.reason) == (False, "rate_limited")
    # internal notifications are not limited
    internal = prepare(migrated_db, lead_ref="cid-x", to_email="lead002@example.com",
                       contact_keys=[], template="customer_reminder", sequence_no=1,
                       data=REMINDER, check_consent=False)
    assert internal.send


@needs_db
def test_retrying_an_already_claimed_message_is_not_rate_limited(migrated_db):
    for n in range(3):
        prepare(migrated_db, lead_ref=f"cid-{n}", to_email="a@example.com", contact_keys=[],
                template="customer_reminder", sequence_no=1, data=REMINDER, daily_limit=3)
    retry = prepare(migrated_db, lead_ref="cid-0", to_email="a@example.com", contact_keys=[],
                    template="customer_reminder", sequence_no=1, data=REMINDER, daily_limit=3)
    assert retry.reason == "pending"  # the ledger answer, not rate_limited


@needs_db
def test_sent_at_recorded(db_client, migrated_db):
    out = prepare(migrated_db, lead_ref="c", to_email="a@example.com", contact_keys=[],
                  template="customer_reminder", sequence_no=1, data=REMINDER)
    db_client.post(f"/v1/outbound/{out.message_id}/status",
                   json={"status": "sent", "provider_msg_id": "<m1@x>"})
    assert migrated_db.execute("SELECT sent_at IS NOT NULL, to_address FROM outbound_messages"
                               ).fetchone() == (True, "a@example.com")


# --- dead letters ----------

def _event_with_dead_letter(conn, status="failed"):
    eid, cid = conn.execute(
        "INSERT INTO intake_events (idempotency_key, source, raw_payload, status)"
        " VALUES (%s, 'form', '{\"name\": \"x\"}', %s) RETURNING id, correlation_id",
        (f"k-{uuid.uuid4()}", status)).fetchone()
    (dl,) = conn.execute("INSERT INTO dead_letters (workflow, correlation_id, payload, error)"
                         " VALUES ('intake', %s, '{}', 'Odoo down') RETURNING id",
                         (cid,)).fetchone()
    return eid, cid, dl


@needs_db
def test_completing_an_event_closes_its_dead_letters(db_client, migrated_db):
    eid, _, dl = _event_with_dead_letter(migrated_db)
    db_client.post(f"/v1/intake/{eid}/status", json={"status": "completed"})
    assert migrated_db.execute("SELECT status, resolution FROM dead_letters WHERE id = %s",
                               (dl,)).fetchone() == ("replayed", "event completed")


@needs_db
def test_replay_forwards_original_event(db_client, migrated_db, monkeypatch):
    calls = []
    monkeypatch.setattr(inbound, "forward_to_intake",
                        lambda settings, payload, **kw: calls.append((payload, kw)) or (202, {}))
    _, _, dl = _event_with_dead_letter(migrated_db)
    assert [d["id"] for d in db_client.get("/v1/dead-letters").json()] == [str(dl)]
    r = db_client.post(f"/v1/dead-letters/{dl}/replay")
    assert r.status_code == 200 and r.json()["status"] == "replayed"
    (payload, kw), = calls
    assert payload == {"name": "x"} and kw["source"] == "form"
    assert kw["idempotency_key"].startswith("k-")
    assert db_client.post(f"/v1/dead-letters/{dl}/replay").status_code == 409


@needs_db
def test_replay_of_completed_event_just_closes(db_client, migrated_db, monkeypatch):
    monkeypatch.setattr(inbound, "forward_to_intake", lambda *a, **k: pytest.fail("no call"))
    _, _, dl = _event_with_dead_letter(migrated_db, status="completed")
    assert db_client.post(f"/v1/dead-letters/{dl}/replay").json()["resolution"] == \
        "event had already completed"


@needs_db
def test_replay_failure_keeps_dead_letter_open(db_client, migrated_db, monkeypatch):
    monkeypatch.setattr(inbound, "forward_to_intake", lambda *a, **k: (503, {}))
    _, _, dl = _event_with_dead_letter(migrated_db)
    assert db_client.post(f"/v1/dead-letters/{dl}/replay").status_code == 502
    assert migrated_db.execute("SELECT status, attempts FROM dead_letters").fetchone() == \
        ("open", 2)


@needs_db
def test_dead_letter_without_event_can_only_be_discarded(db_client, migrated_db):
    (dl,) = migrated_db.execute("INSERT INTO dead_letters (workflow, payload, error) VALUES"
                                " ('scheduler', '{}', 'boom') RETURNING id").fetchone()
    assert db_client.post(f"/v1/dead-letters/{dl}/replay").status_code == 409
    r = db_client.post(f"/v1/dead-letters/{dl}/discard", json={"reason": "transient, reran"})
    assert r.json()["status"] == "discarded"


# --- inbound email ----------

@pytest.mark.parametrize(("text", "expected"), [
    ("Yes, Tuesday works.\n\nOn Sun, 4 Oct 2026, PropFlow wrote:\n> Hi Sara",
     "Yes, Tuesday works."),
    ("Thanks\n> quoted", "Thanks"),
    ("Sounds good\n-----Original Message-----\nFrom: x", "Sounds good"),
    ("", ""),
])
def test_strip_quoted(text, expected):
    assert strip_quoted(text) == expected


@pytest.fixture
def email_env(db_client, migrated_db, monkeypatch):
    odoo = FakeOdoo()
    forwarded = []
    app.dependency_overrides[get_odoo] = lambda: odoo
    app.dependency_overrides[get_calendar] = lambda: CAL
    monkeypatch.setattr(
        inbound, "forward_to_intake",
        lambda settings, payload, **kw: forwarded.append((payload, kw)) or (202, {}))
    lead_id = odoo._create({"name": "x", "user_id": 10, "propflow_score": 70,
                            "propflow_priority": "standard",
                            "propflow_score_explanation": "Total 70 (standard), rules reference-1\n"
                            "budget_provided: +20 (budget stated)\n"
                            "followup_response: +0 (no follow-up reply yet)"})
    cid = migrated_db.execute(
        "INSERT INTO intake_events (idempotency_key, source, raw_payload, status, odoo_lead_id)"
        " VALUES ('orig', 'form', '{}', 'completed', %s) RETURNING correlation_id",
        (lead_id,)).fetchone()[0]
    migrated_db.execute(
        "INSERT INTO outbound_messages (lead_ref, channel, template, status, provider_msg_id,"
        " to_address) VALUES (%s, 'email', 'customer_shortlist', 'sent', '<sent-1@propflow>',"
        " 'sara@example.com')", (str(cid),))
    migrated_db.execute(
        "INSERT INTO followup_sequences (odoo_lead_id, correlation_id, to_email, next_due_at)"
        " VALUES (%s, %s, 'sara@example.com', now())", (lead_id, cid))
    return {"client": db_client, "odoo": odoo, "lead_id": lead_id, "forwarded": forwarded,
            "db": migrated_db}


def email(**kw):
    return {"message_id": f"<{uuid.uuid4()}@mail>", "from_email": "Sara@Example.com",
            "from_name": "Sara", "subject": "Re: Listings that match your request",
            "text": "Yes please, can we see SZ-VIL-201 on Tuesday?\n\nOn Sun wrote:\n> old",
            "now": NOW.isoformat(), **kw}


@needs_db
def test_reply_by_header_stops_reminders_rescores_and_notifies(email_env):
    env = email_env
    r = env["client"].post("/v1/email/receive",
                           json=email(in_reply_to="<sent-1@propflow>", subject="anything"))
    body = r.json()
    assert (body["kind"], body["action"], body["lead_id"]) == ("reply", "reply_recorded",
                                                                env["lead_id"])
    assert body["score"] == {"before": 70, "after": 80, "priority": "high", "changed": True}
    lead = env["odoo"].leads[env["lead_id"]]
    assert lead["propflow_priority"] == "high"
    assert "followup_response: +10 (customer replied)" in lead["propflow_score_explanation"]
    assert lead["propflow_score_explanation"].startswith("Total 80 (high)")
    (_, note), = env["odoo"].notes
    assert "SZ-VIL-201 on Tuesday" in note and "old" not in note
    assert (env["lead_id"], "PropFlow: customer replied") in env["odoo"].activities
    (rep,) = body["messages"]
    assert rep["to"] == "rep10@example.com" and "replied by email" in rep["text"]
    assert env["db"].execute("SELECT status, stop_reason FROM followup_sequences").fetchone() \
        == ("stopped", "customer_replied")
    assert env["db"].execute("SELECT kind, status FROM intake_events WHERE source = 'email'"
                             ).fetchone() == ("reply", "completed")
    assert env["forwarded"] == []


@needs_db
def test_reply_matches_message_id_with_or_without_brackets(email_env):
    body = email_env["client"].post("/v1/email/receive", json=email(
        in_reply_to=None, references=["<other@x>", "sent-1@propflow"], subject="hi")).json()
    assert body["kind"] == "reply"


@needs_db
def test_reply_points_are_awarded_once(email_env):
    env = email_env
    env["client"].post("/v1/email/receive", json=email(in_reply_to="<sent-1@propflow>"))
    second = env["client"].post("/v1/email/receive",
                                json=email(in_reply_to="<sent-1@propflow>")).json()
    assert second["score"]["changed"] is False and second["score"]["after"] == 80


@needs_db
def test_reply_by_subject_fallback(email_env):
    body = email_env["client"].post("/v1/email/receive", json=email()).json()
    assert body["kind"] == "reply"


@needs_db
def test_opt_out_reply(email_env):
    env = email_env
    body = env["client"].post("/v1/email/receive",
                              json=email(in_reply_to="<sent-1@propflow>",
                                         text="STOP")).json()
    assert (body["action"], body["messages"]) == ("opted_out", [])
    assert env["db"].execute("SELECT status FROM consents WHERE contact_key ="
                             " 'sara@example.com'").fetchone() == ("opted_out",)
    assert env["db"].execute("SELECT stop_reason FROM followup_sequences").fetchone() == \
        ("opted_out",)


@needs_db
def test_new_email_is_forwarded_as_an_inquiry(email_env):
    env = email_env
    body = env["client"].post("/v1/email/receive", json=email(
        message_id="<new-1@mail>", from_email="new.buyer@example.com",
        subject="Villa in Sheikh Zayed", text="4 bedrooms, up to 15M")).json()
    assert (body["kind"], body["forwarded_status"]) == ("inquiry", 202)
    (payload, kw), = env["forwarded"]
    assert payload == {"source": "email", "name": "Sara", "email": "new.buyer@example.com",
                       "message": "Villa in Sheikh Zayed\n\n4 bedrooms, up to 15M"}
    assert kw == {"source": "email", "idempotency_key": "email:<new-1@mail>"}


@needs_db
def test_duplicate_reply_email_is_ignored(email_env):
    env = email_env
    msg = email(in_reply_to="<sent-1@propflow>", message_id="<dup@mail>")
    env["client"].post("/v1/email/receive", json=msg)
    assert env["client"].post("/v1/email/receive", json=msg).json()["kind"] == "duplicate"
    assert len(env["odoo"].notes) == 1


@needs_db
def test_invalid_sender_is_ignored(email_env):
    assert email_env["client"].post("/v1/email/receive",
                                    json=email(from_email="nobody")).json()["kind"] == "ignored"
