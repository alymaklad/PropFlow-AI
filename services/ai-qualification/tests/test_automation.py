import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.automation import (
    check_handoffs,
    create_handoff,
    decide_route,
    due_followups,
    handoff_messages,
    start_sequence,
)
from app.business_time import BusinessCalendar
from tests.conftest import needs_db
from tests.fake_odoo import FakeOdoo

CAIRO = ZoneInfo("Africa/Cairo")
CAL = BusinessCalendar(CAIRO, time(9), time(17), frozenset({6, 0, 1, 2, 3}))
URL = "http://odoo.test"


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=CAIRO)  # 4 Oct 2026 is a Sunday


SUNDAY_10 = at(4, 10)


def lead(**kw):
    base = {"name": "Sara Hassan", "email": "lead002@example.com", "phone": "+201000000002",
            "message": "Can I talk to a person? Villa in Zayed", "property_type": "villa",
            "location": "Sheikh Zayed", "bedrooms": 4, "budget_min": None,
            "budget_max": 15_000_000, "currency": "EGP", "delivery_preference": None,
            "purchase_timeline_months": 2, "conflicts": []}
    return {**base, **kw}


# --- routing -----------------------------------------------------------------------------------

@pytest.mark.parametrize(("qual", "lead_kw", "match", "has_email", "expected"), [
    ({"opt_out": True, "reasons": ["injection_suspected"]}, {}, "matched", True, ("opt_out", [])),
    ({"reasons": ["customer_requested_human"]}, {}, "matched", True,
     ("handoff", ["customer_requested_human"])),
    ({"reasons": []}, {}, "matched", True, ("shortlist", [])),
    ({"reasons": []}, {"location": None}, "insufficient_criteria", True, ("clarify", [])),
    ({"reasons": []}, {}, "none", True, ("handoff", ["no_matching_property"])),
    ({"reasons": []}, {"conflicts": ["studio_with_bedrooms"]}, "conflict", True,
     ("handoff", ["conflicting_requirements"])),
    ({"reasons": []}, {}, "matched", False, ("rep_only", [])),
    # AI down but the form is enough to search: carry on deterministically
    ({"reasons": ["ai_unavailable"]}, {}, "matched", True, ("shortlist", [])),
    # AI down and nothing to search with: hand off
    ({"reasons": ["ai_unavailable"]}, {"location": None}, "insufficient_criteria", True,
     ("handoff", ["ai_unavailable"])),
    (None, {}, "matched", True, ("shortlist", [])),  # no message: no qualification at all
])
def test_decide_route(qual, lead_kw, match, has_email, expected):
    assert decide_route(qual, lead(**lead_kw), match, has_email) == expected


# --- handoff -----------------------------------------------------------------------------------

def _event(conn):
    return conn.execute("INSERT INTO intake_events (idempotency_key, source, raw_payload)"
                        " VALUES (%s, 'form', '{}') RETURNING id, correlation_id",
                        (str(uuid.uuid4()),)).fetchone()


def _handoff(conn, odoo, event, *, user_id=10, priority="high", now=SUNDAY_10,
             reasons=("customer_requested_human",)):
    lead_id = odoo._create({"name": "x", "team_id": 1,
                            "propflow_correlation_id": str(event[1])})
    return lead_id, create_handoff(
        conn, odoo, CAL, event_id=event[0], correlation_id=event[1], lead_id=lead_id,
        user_id=user_id, team_id=1, priority=priority, reasons=list(reasons), lead=lead(),
        matches=[{"listing_id": "SZ-VIL-201"}], public_url=URL, now=now)


@needs_db
def test_handoff_pauses_automation_and_assigns_a_deadline(migrated_db):
    odoo = FakeOdoo()
    lead_id, result = _handoff(migrated_db, odoo, _event(migrated_db))
    assert result.created and result.due_at == at(4, 12)  # high priority: 2 business hours
    assert result.contact_by == "Sunday 4 October at 12:00"
    stored = odoo.leads[lead_id]
    assert stored["propflow_exception_status"] == "handoff"
    assert stored["propflow_automation"] == "paused"
    (activity_key, activity), = odoo.activities.items()
    assert activity_key[1] == "PropFlow handoff: contact the customer"
    assert activity["user_id"] == 10 and activity["deadline"] == "2026-10-04"
    (_, note), = odoo.notes
    assert "the customer asked to speak to a person" in note and "SZ-VIL-201" in note
    row = migrated_db.execute("SELECT status, assigned_user_id, priority, reason FROM"
                              " escalations").fetchone()
    assert row == ("open", 10, "high", "customer_requested_human")


@needs_db
def test_handoff_is_idempotent_per_event(migrated_db):
    odoo, event = FakeOdoo(), _event(migrated_db)
    lead_id, first = _handoff(migrated_db, odoo, event)
    again = create_handoff(migrated_db, odoo, CAL, event_id=event[0], correlation_id=event[1],
                           lead_id=lead_id, user_id=10, team_id=1, priority="high",
                           reasons=["customer_requested_human"], lead=lead(), matches=[],
                           public_url=URL, now=at(4, 11))
    assert not again.created and again.escalation_id == first.escalation_id
    assert again.due_at == first.due_at and len(odoo.notes) == 1


@needs_db
def test_standard_priority_deadline_is_next_business_day(migrated_db):
    _, result = _handoff(migrated_db, FakeOdoo(), _event(migrated_db), priority="standard",
                         now=at(8, 15))  # Thursday 15:00
    assert result.due_at == at(11, 15)  # Sunday 15:00


@needs_db
def test_unassigned_lead_falls_back_to_team_manager(migrated_db):
    _, result = _handoff(migrated_db, FakeOdoo(members=()), _event(migrated_db), user_id=None)
    assert result.owner["email"] == "manager@example.com"


@needs_db
def test_handoff_stops_active_followups(migrated_db):
    odoo, event = FakeOdoo(), _event(migrated_db)
    lead_id = odoo._create({"name": "x"})
    start_sequence(migrated_db, CAL, lead_id=lead_id, correlation_id=event[1],
                   to_email="a@example.com", contact_keys=[], name="A", requirements={},
                   now=at(4, 10))
    create_handoff(migrated_db, odoo, CAL, event_id=event[0], correlation_id=event[1],
                   lead_id=lead_id, user_id=10, team_id=1, priority="high",
                   reasons=["low_confidence"], lead=lead(), matches=[], public_url=URL,
                   now=at(4, 11))
    assert migrated_db.execute("SELECT status, stop_reason FROM followup_sequences").fetchone() \
        == ("stopped", "handed_off")


@needs_db
def test_handoff_messages_rep_and_customer_once(migrated_db):
    odoo, event = FakeOdoo(), _event(migrated_db)
    lead_id, result = _handoff(migrated_db, odoo, event)
    messages = handoff_messages(migrated_db, result, lead_id=lead_id,
                                reasons=["customer_requested_human"], lead=lead())
    rep, customer = messages
    assert (rep["kind"], rep["send"], rep["to"]) == ("rep", True, "rep10@example.com")
    assert "Please contact the customer by Sunday 4 October at 12:00" in rep["text"]
    assert (customer["kind"], customer["send"], customer["to"]) == \
        ("customer", True, "lead002@example.com")
    assert "Rep 10 from our sales team will contact you" in customer["text"]
    again = handoff_messages(migrated_db, result, lead_id=lead_id,
                             reasons=["customer_requested_human"], lead=lead())
    assert [m["send"] for m in again] == [False, False]


@needs_db
def test_handoff_ack_respects_opt_out(migrated_db):
    migrated_db.execute("INSERT INTO consents VALUES ('+201000000002', 'email', 'opted_out',"
                        " 'test', now())")
    odoo, event = FakeOdoo(), _event(migrated_db)
    lead_id, result = _handoff(migrated_db, odoo, event)
    rep, customer = handoff_messages(migrated_db, result, lead_id=lead_id,
                                     reasons=["customer_requested_human"], lead=lead())
    assert rep["send"] and (customer["send"], customer["reason"]) == (False, "opted_out")


@needs_db
def test_overdue_handoff_reminds_rep_then_manager(migrated_db):
    odoo = FakeOdoo()
    _handoff(migrated_db, odoo, _event(migrated_db), now=at(4, 10))  # due Sunday 12:00

    def check(now):
        return check_handoffs(migrated_db, odoo, CAL, public_url=URL, now=now)

    assert check(at(4, 11))["messages"] == []                       # not due yet
    reminder, = check(at(4, 12, 15))["messages"]
    assert (reminder["kind"], reminder["to"]) == ("rep", "rep10@example.com")
    assert check(at(4, 13))["messages"] == []                       # reminded once only
    assert check(at(4, 18))["messages"] == []                       # outside business hours
    escalation, = check(at(5, 9, 30))["messages"]                   # 2 business hours later
    assert (escalation["kind"], escalation["to"]) == ("manager", "manager@example.com")
    assert "has not been actioned" in escalation["text"]
    assert check(at(5, 10))["messages"] == []


@needs_db
def test_overdue_handoff_without_manager_is_reported(migrated_db):
    odoo = FakeOdoo()
    odoo.MANAGER_ID = None  # the team has no leader
    _handoff(migrated_db, odoo, _event(migrated_db), now=at(4, 10))
    check_handoffs(migrated_db, odoo, CAL, public_url=URL, now=at(4, 12, 15))  # reminder
    missing, = check_handoffs(migrated_db, odoo, CAL, public_url=URL, now=at(5, 9, 30))[
        "messages"]
    assert (missing["kind"], missing["send"], missing["reason"]) == \
        ("manager", False, "no_manager")


@needs_db
def test_done_activity_resolves_handoff(migrated_db):
    odoo = FakeOdoo()
    _handoff(migrated_db, odoo, _event(migrated_db))
    (_, activity), = odoo.activities.items()
    odoo.done_activities.add(activity["id"])
    result = check_handoffs(migrated_db, odoo, CAL, public_url=URL, now=at(4, 15))
    assert len(result["resolved"]) == 1 and result["messages"] == []
    assert migrated_db.execute("SELECT status FROM escalations").fetchone() == ("resolved",)


# --- follow-up sequences -----------------------------------------------------------------------

def _sequence(conn, odoo, now=SUNDAY_10):
    lead_id = odoo._create({"name": "x", "user_id": 11})
    start_sequence(conn, CAL, lead_id=lead_id, correlation_id=uuid.uuid4(),
                   to_email="Lead002@Example.com", contact_keys=["+201000000002"],
                   name="Sara Hassan", requirements={"location": "Maadi", "bedrooms": 2},
                   now=now)
    return lead_id


@needs_db
def test_reminders_follow_the_schedule_then_complete(migrated_db):
    odoo = FakeOdoo()
    _sequence(migrated_db, odoo)  # first reminder due Tuesday 6 Oct 10:00

    def due(now):
        return due_followups(migrated_db, odoo, CAL, now=now)

    assert due(at(5, 10))["messages"] == []
    first, = due(at(6, 10))["messages"]
    assert first["send"] and first["to"] == "lead002@example.com"
    assert "Rep 11 will help" in first["text"] and "a 2-bedroom in Maadi" in first["text"]
    assert due(at(6, 11))["messages"] == []
    second, = due(at(11, 10))["messages"]   # +3 business days, skipping Fri/Sat
    assert second["send"]
    assert due(at(18, 10)) == {"messages": [], "stopped": []}
    assert migrated_db.execute("SELECT status, reminders_sent FROM followup_sequences"
                               ).fetchone() == ("completed", 2)


@needs_db
@pytest.mark.parametrize(("change", "reason"), [
    ({"propflow_automation": "paused"}, "paused_by_owner"),
    ({"type": "opportunity"}, "owner_took_over"),
    ({"propflow_exception_status": "handoff"}, "handed_off"),
    ({"active": False}, "lead_closed"),
    ({"probability": 100}, "won"),
])
def test_reminders_stop_when_the_owner_takes_over(migrated_db, change, reason):
    odoo = FakeOdoo()
    lead_id = _sequence(migrated_db, odoo)
    odoo.leads[lead_id].update(change)
    result = due_followups(migrated_db, odoo, CAL, now=at(6, 10))
    assert result["messages"] == [] and result["stopped"][0]["reason"] == reason


@needs_db
def test_opt_out_stops_reminders(migrated_db, db_client):
    odoo = FakeOdoo()
    _sequence(migrated_db, odoo)
    db_client.post("/v1/consents", json={"contact_keys": ["lead002@example.com"],
                                         "status": "opted_out", "source": "reply STOP"})
    assert migrated_db.execute("SELECT status, stop_reason FROM followup_sequences").fetchone() \
        == ("stopped", "opted_out")
    assert due_followups(migrated_db, odoo, CAL, now=at(6, 10))["messages"] == []


@needs_db
def test_no_reminders_outside_business_hours(migrated_db):
    odoo = FakeOdoo()
    _sequence(migrated_db, odoo)
    assert due_followups(migrated_db, odoo, CAL, now=at(9, 12))["messages"] == []  # Friday
    assert len(due_followups(migrated_db, odoo, CAL, now=at(11, 9))["messages"]) == 1


@needs_db
def test_sequence_starts_once_per_lead(migrated_db):
    odoo = FakeOdoo()
    lead_id = _sequence(migrated_db, odoo)
    again = start_sequence(migrated_db, CAL, lead_id=lead_id, correlation_id=uuid.uuid4(),
                           to_email="x@example.com", contact_keys=[], name=None,
                           requirements={}, now=at(4, 11))
    assert again == {"created": False}


@needs_db
def test_route_and_handoff_endpoints(db_client, migrated_db):
    from app.deps import get_odoo
    from app.main import app
    from app.routers.automation import get_calendar
    odoo = FakeOdoo()
    app.dependency_overrides[get_odoo] = lambda: odoo
    app.dependency_overrides[get_calendar] = lambda: CAL
    normalized = {**lead(), "valid": True, "source": "form", "contact_key": "+201000000002",
                  "location_raw": "Zayed", "purchase_intent": "high", "errors": [],
                  "warnings": []}
    r = db_client.post("/v1/route", json={
        "qualification": {"opt_out": False, "reasons": ["customer_requested_human"]},
        "lead": normalized, "match_status": "matched"})
    assert r.json() == {"route": "handoff", "reasons": ["customer_requested_human"]}

    event = _event(migrated_db)
    lead_id = odoo._create({"name": "x", "team_id": 1})
    r = db_client.post("/v1/handoffs", json={
        "event_id": str(event[0]), "correlation_id": str(event[1]), "lead_id": lead_id,
        "user_id": 10, "team_id": 1, "priority": "high",
        "reasons": ["customer_requested_human"], "lead": normalized,
        "now": at(4, 10).isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] and body["contact_by"] == "Sunday 4 October at 12:00"
    assert [(m["kind"], m["send"]) for m in body["messages"]] == \
        [("rep", True), ("customer", True)]
