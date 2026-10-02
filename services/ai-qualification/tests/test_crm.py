import uuid
from datetime import date

import pytest

from app.crm import add_business_days, lead_name, schedule_followup, upsert_lead
from tests.conftest import needs_db
from tests.fake_odoo import FakeOdoo

SCORE = {"total": 70, "priority": "standard", "rules_version": "reference-1", "components": [
    {"rule": "budget_provided", "points": 20, "reason": "budget stated"},
    {"rule": "timeline_within_3_months", "points": 30, "reason": "buying within 2 month(s)"},
    {"rule": "requirements_complete", "points": 20, "reason": "type, location and size known"},
    {"rule": "explicit_high_intent", "points": 0, "reason": "intent is medium"},
    {"rule": "followup_response", "points": 0, "reason": "no follow-up reply yet"},
]}


def lead(**overrides):
    base = {"valid": True, "source": "form", "name": "Ahmed Samir", "phone": "+201000000001",
            "email": "lead001@example.com", "contact_key": "+201000000001",
            "message": "3 bed in New Cairo\n<b>asap</b>", "property_type": "apartment",
            "location": "New Cairo", "location_raw": "Fifth Settlement", "bedrooms": 3,
            "budget_min": 6_000_000, "budget_max": 8_000_000, "currency": "EGP",
            "purchase_timeline_months": 2, "purchase_intent": "medium",
            "errors": [], "warnings": [], "conflicts": []}
    return {**base, **overrides}


def test_lead_name():
    assert lead_name(lead()) == "Apartment in New Cairo – Ahmed Samir"
    assert lead_name(lead(property_type=None, location=None, name=None)) == \
        "Property – +201000000001"


@pytest.mark.parametrize(("start", "days", "expected"), [
    (date(2026, 10, 4), 0, date(2026, 10, 4)),   # Sunday, same day
    (date(2026, 10, 2), 0, date(2026, 10, 4)),   # Friday -> Sunday
    (date(2026, 10, 8), 1, date(2026, 10, 11)),  # Thursday +1 -> Sunday
    (date(2026, 10, 4), 3, date(2026, 10, 7)),   # Sunday +3 -> Wednesday
])
def test_add_business_days(start, days, expected):
    assert add_business_days(start, days) == expected


@needs_db
def test_creates_lead_with_round_robin_owner(migrated_db):
    odoo, cid = FakeOdoo(), uuid.uuid4()
    result = upsert_lead(odoo, migrated_db, correlation_id=cid, lead=lead(), score=SCORE)
    assert (result.action, result.user_id, result.team_id, result.warnings) == \
        ("created", 10, 1, [])
    stored = odoo.leads[result.lead_id]
    assert stored["propflow_correlation_id"] == str(cid)
    assert stored["propflow_bedrooms"] == "3" and stored["propflow_priority"] == "standard"
    assert "&lt;b&gt;asap&lt;/b&gt;" in stored["description"] and "<br>" in stored["description"]
    assert stored["propflow_original_message"].endswith("<b>asap</b>")
    assert "budget_provided: +20 (budget stated)" in stored["propflow_score_explanation"]


@needs_db
def test_retry_updates_instead_of_duplicating(migrated_db):
    odoo, cid = FakeOdoo(), uuid.uuid4()
    first = upsert_lead(odoo, migrated_db, correlation_id=cid, lead=lead(), score=SCORE)
    again = upsert_lead(odoo, migrated_db, correlation_id=cid, lead=lead(bedrooms=None),
                        score=SCORE)
    assert again.action == "updated" and again.lead_id == first.lead_id
    assert len(odoo.leads) == 1
    assert odoo.leads[first.lead_id]["propflow_bedrooms"] is False  # full replace on retry


@needs_db
def test_lost_create_response_does_not_duplicate(migrated_db):
    odoo = FakeOdoo()
    odoo.lose_next_create_response = True
    result = upsert_lead(odoo, migrated_db, correlation_id=uuid.uuid4(), lead=lead(),
                         score=SCORE)
    assert result.action == "updated" and len(odoo.leads) == 1


@needs_db
def test_known_contact_gets_a_note_not_a_new_lead(migrated_db):
    odoo = FakeOdoo()
    first = upsert_lead(odoo, migrated_db, correlation_id=uuid.uuid4(),
                        lead=lead(bedrooms=None), score=SCORE)
    low = {**SCORE, "total": 20, "priority": "nurture"}
    second = upsert_lead(odoo, migrated_db, correlation_id=uuid.uuid4(),
                         lead=lead(phone=None, contact_key="lead001@example.com",
                                   message="Also open to a villa", property_type="villa",
                                   bedrooms=4, location=None),
                         score=low)
    assert (second.action, second.lead_id, second.user_id) == \
        ("matched_contact", first.lead_id, first.user_id)
    assert len(odoo.leads) == 1
    stored = odoo.leads[first.lead_id]
    assert stored["propflow_bedrooms"] == "4"               # was missing: filled in
    assert stored["propflow_property_type"] == "apartment"  # existing value kept
    assert stored["propflow_location"] == "New Cairo"       # not erased
    assert stored["propflow_priority"] == "standard"        # not downgraded
    (lead_id, note), = odoo.notes
    assert lead_id == first.lead_id
    assert "Also open to a villa" in note and "property_type=villa" in note
    assert "Score: 20 (nurture)" in note


@needs_db
def test_known_contact_handoff_status_is_carried_over(migrated_db):
    odoo = FakeOdoo()
    first = upsert_lead(odoo, migrated_db, correlation_id=uuid.uuid4(), lead=lead(), score=SCORE)
    upsert_lead(odoo, migrated_db, correlation_id=uuid.uuid4(), lead=lead(), score=SCORE,
                exception_status="handoff")
    assert odoo.leads[first.lead_id]["propflow_exception_status"] == "handoff"


@needs_db
def test_closed_won_lead_is_not_reused(migrated_db):
    odoo = FakeOdoo()
    first = upsert_lead(odoo, migrated_db, correlation_id=uuid.uuid4(), lead=lead(), score=SCORE)
    odoo.leads[first.lead_id]["probability"] = 100
    second = upsert_lead(odoo, migrated_db, correlation_id=uuid.uuid4(), lead=lead(),
                         score=SCORE)
    assert second.action == "created" and second.lead_id != first.lead_id


@needs_db
def test_no_salespeople_creates_unassigned_lead_with_warning(migrated_db):
    odoo = FakeOdoo(members=())
    result = upsert_lead(odoo, migrated_db, correlation_id=uuid.uuid4(), lead=lead(),
                         score=SCORE)
    assert result.user_id is None and result.warnings == ["no_salespeople"]
    assert odoo.leads[result.lead_id]["user_id"] is False


def test_schedule_followup_is_idempotent():
    odoo = FakeOdoo()
    odoo.leads[1] = {"id": 1, "active": True}
    a1, d1 = schedule_followup(odoo, lead_id=1, user_id=10, priority="nurture",
                               today=date(2026, 10, 4))
    a2, _ = schedule_followup(odoo, lead_id=1, user_id=10, priority="nurture",
                              today=date(2026, 10, 4))
    assert a1 == a2 and d1 == date(2026, 10, 7)
    assert odoo.leads[1]["propflow_next_followup"] == "2026-10-07"
