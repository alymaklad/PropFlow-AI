import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.business_time import BusinessCalendar
from app.reports import build_report, render_text
from tests.conftest import needs_db
from tests.fake_odoo import FakeOdoo

CAIRO = ZoneInfo("Africa/Cairo")
CAL = BusinessCalendar(CAIRO, time(9), time(17), frozenset({6, 0, 1, 2, 3}))
END = datetime(2026, 10, 5, 8, 0, tzinfo=CAIRO)
START = END - timedelta(days=1)
IN_WINDOW = END - timedelta(hours=5)


def event(conn, *, source="form", status="completed", kind="inquiry", lead=None, action=None,
          at=IN_WINDOW):
    return conn.execute(
        "INSERT INTO intake_events (idempotency_key, source, raw_payload, status, kind,"
        " odoo_lead_id, crm_action, received_at) VALUES (%s, %s, '{}', %s, %s, %s, %s, %s)"
        " RETURNING id, correlation_id",
        (str(uuid.uuid4()), source, status, kind, lead, action, at)).fetchone()


def seed(conn):
    a = event(conn, lead=1, action="created")
    b = event(conn, source="email", lead=2, action="matched_contact")
    event(conn, status="rejected")
    event(conn, status="failed")
    event(conn)  # opt-out: completed without a lead
    event(conn, source="email", kind="reply", lead=1)
    event(conn, lead=9, action="created", at=START - timedelta(minutes=1))  # outside window
    for (eid, _), priority, total in ((a, "high", 90), (b, "standard", 60)):
        conn.execute("INSERT INTO score_results (event_id, rules_version, total, components,"
                     " priority) VALUES (%s, 'reference-1', %s, '[]', %s)", (eid, total, priority))
    conn.execute("INSERT INTO match_results (event_id, correlation_id, status, criteria)"
                 " VALUES (%s, %s, 'matched', '{}'), (%s, %s, 'none', '{}')",
                 (a[0], a[1], b[0], b[1]))
    conn.execute("INSERT INTO qualifications (event_id, model, prompt_version,"
                 " validation_status) VALUES (%s, 'm', 'v', 'valid'), (%s, 'm', 'v', 'fallback')",
                 (a[0], b[0]))
    # first response 30 minutes after intake (shortlist), and a handoff ack after 90 minutes
    conn.execute("INSERT INTO outbound_messages (lead_ref, channel, template, status, sent_at,"
                 " created_at) VALUES (%s, 'email', 'customer_shortlist', 'sent', %s, %s)",
                 (str(a[1]), IN_WINDOW + timedelta(minutes=30), IN_WINDOW))
    (esc,) = conn.execute(
        "INSERT INTO escalations (event_id, reason, assigned_to, due_at, created_at)"
        " VALUES (%s, 'no_matching_property,low_confidence', 'Rep 10', %s, %s) RETURNING id",
        (b[0], END - timedelta(hours=1), IN_WINDOW)).fetchone()
    conn.execute("INSERT INTO outbound_messages (lead_ref, channel, template, status, sent_at,"
                 " created_at) VALUES (%s, 'email', 'customer_handoff_ack', 'sent', %s, %s)",
                 (f"handoff:{esc}", IN_WINDOW + timedelta(minutes=90), IN_WINDOW))
    conn.execute("INSERT INTO followup_sequences (odoo_lead_id, correlation_id, to_email,"
                 " status, stop_reason, created_at) VALUES (1, %s, 'a@example.com', 'stopped',"
                 " 'customer_replied', %s)", (a[1], IN_WINDOW))
    conn.execute("INSERT INTO dead_letters (workflow, payload, error, created_at)"
                 " VALUES ('intake', '{}', 'boom', %s)", (IN_WINDOW,))
    # sent before migration 0006 added sent_at: no timing, must be ignored
    conn.execute("INSERT INTO outbound_messages (lead_ref, channel, template, status,"
                 " created_at) VALUES (%s, 'email', 'customer_clarification', 'sent', %s)",
                 (str(b[1]), IN_WINDOW))
    conn.execute("INSERT INTO lead_assignments (correlation_id, team_id, user_id, assigned_at)"
                 " VALUES (%s, 1, 10, %s)", (a[1], IN_WINDOW))


@needs_db
def test_report_figures_reconcile_with_the_ledger(migrated_db):
    seed(migrated_db)
    odoo = FakeOdoo()
    lead = odoo._create({"name": "x", "user_id": 10, "propflow_correlation_id": "c"})
    odoo.activities[(lead, "PropFlow follow-up")] = {"id": 1, "user_id": 10,
                                                     "deadline": "2026-10-01"}
    r = build_report(migrated_db, odoo, CAL, start=START, end=END)
    i = r["intake"]
    assert i["received"] == 5 and i["received_by_source"] == {"form": 4, "email": 1}
    assert i["outcomes"] == {"completed": 3, "rejected": 1, "failed": 1}
    assert i["intake_success_rate"] == {"numerator": 3, "denominator": 4, "rate": 0.75}
    assert i["crm_actions"] == {"created": 1, "matched_contact": 1}
    assert i["closed_without_lead"] == 1
    assert r["crm_sync"]["success_rate"] == {"numerator": 2, "denominator": 3, "rate": 0.6667}
    assert r["qualification"]["priority_distribution"] == {"high": 1, "standard": 1}
    assert r["qualification"]["ai_outcomes"] == {"valid": 1, "fallback": 1}
    assert r["matching"]["outcomes"] == {"matched": 1, "none": 1}
    assert r["first_response_minutes"] == {
        "count": 2, "average": 60.0, "median": 60.0,
        "denominator_note": "events whose first customer email was sent in the window"}
    assert r["followups"]["sequences_started_by_outcome"] == {"customer_replied": 1}
    assert r["followups"]["customer_replies"] == 1
    assert r["followups"]["overdue_propflow_activities"] == 1
    h = r["handoffs"]
    assert (h["created"], h["still_open"], h["overdue_open_now"]) == (1, 1, 1)
    assert h["by_reason"] == {"no_matching_property": 1, "low_confidence": 1}
    assert r["failures"] == {"dead_letters_by_status": {"open": 1}, "open_dead_letters_now": 1}
    assert r["workload"] == {"Rep 10": {"assigned_in_window": 1, "open_leads": 1}}
    assert r["odoo"] == "ok"


@needs_db
def test_report_text_states_windows_and_denominators(migrated_db):
    seed(migrated_db)
    text = render_text(build_report(migrated_db, FakeOdoo(), CAL, start=START, end=END),
                       "PropFlow daily report")
    assert "Intake success rate (completed / valid): 75.0% (3 of 4)" in text
    assert "First customer response: median 60.0 min, average 60.0 min over 2 lead(s)" in text
    assert "Reasons: low_confidence 1, no_matching_property 1" in text
    assert "Window: 2026-10-04T08:00+03:00 to 2026-10-05T08:00+03:00" in text


@needs_db
def test_report_survives_odoo_outage(migrated_db):
    seed(migrated_db)
    r = build_report(migrated_db, None, CAL, start=START, end=END)
    assert r["odoo"].startswith("unavailable") and r["workload"] == {}
    assert r["followups"]["overdue_propflow_activities"] is None
    assert "Overdue PropFlow activities in Odoo now: unavailable" in render_text(r, "t")


@needs_db
def test_report_endpoint(db_client, migrated_db):
    from app.main import app
    from app.routers.automation import _optional_odoo, get_calendar
    app.dependency_overrides[_optional_odoo] = lambda: FakeOdoo()
    app.dependency_overrides[get_calendar] = lambda: CAL
    seed(migrated_db)
    r = db_client.post("/v1/reports/summary", json={"period": "day", "end": END.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subject"] == "[PropFlow] Daily report: 5 inquiries, 1 handoffs (Mon 05 Oct 2026)"
    assert body["text"].startswith("PropFlow daily report, Mon 05 Oct 2026")
