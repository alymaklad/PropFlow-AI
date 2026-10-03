import re

import pytest

from app.messages import DEMO_NOTICE, OPT_OUT_LINE, TemplateError, first_name, render, summary
from tests.conftest import needs_db

REQ = {"property_type": "villa", "location": "Sheikh Zayed", "bedrooms": 4,
       "budget_max": 15_000_000, "currency": "EGP"}
MATCH = {"listing_id": "SZ-VIL-201", "property_type": "villa", "location": "Sheikh Zayed",
         "price": 14_200_000.0, "currency": "EGP", "bedrooms": 4, "delivery_status": "ready",
         "description": "Villa in a gated community.", "verified_days_ago": 2}
DATA = {
    "customer_shortlist": {"name": "Sara Hassan", "requirements": REQ, "matches": [MATCH],
                           "advisor_name": "Demo Rep Two"},
    "customer_clarification": {"name": "Sara", "missing": ["location", "budget"]},
    "customer_handoff_ack": {"name": "Sara", "advisor_name": "Demo Rep Two",
                             "advisor_email": "demo-rep-2@example.com",
                             "advisor_phone": "+20 2 0000 0000", "contact_by": "Sunday 11:00"},
    "customer_reminder": {"name": "Sara", "requirements": REQ, "advisor_name": "Demo Rep Two"},
}
PROMISES = re.compile(r"\b(guarantee|guaranteed|reserved for you|definitely available)\b", re.I)


@pytest.mark.parametrize("template", sorted(DATA))
def test_every_template_has_opt_out_and_makes_no_promises(template):
    subject, text = render(template, DATA[template])
    assert subject and text.startswith("Hi Sara,")
    assert OPT_OUT_LINE in text
    assert not PROMISES.search(text)


def test_shortlist_lists_verified_listings_with_caveat():
    _, text = render("customer_shortlist", DATA["customer_shortlist"])
    assert "SZ-VIL-201: 4 bedrooms, Sheikh Zayed, 14.2 million EGP (ready)" in text
    assert "checked within the last 2 day(s) and can change" in text


def test_clarification_asks_only_for_missing_fields():
    _, text = render("customer_clarification", DATA["customer_clarification"])
    assert "Which area" in text and "budget range" in text and "bedrooms" not in text
    with pytest.raises(TemplateError):
        render("customer_clarification", {"missing": ["unknown_field"]})


def test_handoff_ack_names_the_advisor_and_deadline():
    _, text = render("customer_handoff_ack", DATA["customer_handoff_ack"])
    assert "Demo Rep Two from our sales team will contact you by Sunday 11:00" in text
    assert "demo-rep-2@example.com or +20 2 0000 0000" in text


def test_missing_data_and_unknown_template_are_errors():
    with pytest.raises(TemplateError, match="needs matches"):
        render("customer_shortlist", {"requirements": REQ, "advisor_name": "x"})
    with pytest.raises(TemplateError, match="unknown"):
        render("nope", {})


@pytest.mark.parametrize(("req", "expected"), [
    (REQ, "4-bedroom villa in Sheikh Zayed, up to 15 million EGP"),
    ({"property_type": "studio", "bedrooms": 0, "location": "Zamalek"}, "studio in Zamalek"),
    ({"location": "Maadi", "budget_min": 5_500_000}, "property in Maadi, from 5.5 million EGP"),
    ({"bedrooms": 2, "budget_max": 150_000, "currency": "USD"}, "2-bedroom, up to 150,000 USD"),
])
def test_summary(req, expected):
    assert summary(req) == expected


def test_first_name_fallback():
    assert first_name("  Sara Hassan ") == "Sara" and first_name(None) == "there"


PREPARE = {"lead_ref": "cid-1", "to_email": "lead002@example.com",
           "contact_keys": ["+201000000002"], "template": "customer_reminder",
           "data": DATA["customer_reminder"]}


@needs_db
def test_prepare_renders_and_claims_once(db_client):
    first = db_client.post("/v1/messages/prepare", json=PREPARE).json()
    assert first["send"] and first["to"] == "lead002@example.com"
    assert first["subject"] == "Still looking for a property?"
    again = db_client.post("/v1/messages/prepare", json=PREPARE).json()
    assert (again["send"], again["reason"]) == (False, "pending")
    db_client.post(f"/v1/outbound/{first['message_id']}/status", json={"status": "sent"})
    assert db_client.post("/v1/messages/prepare", json=PREPARE).json()["reason"] == \
        "already_sent"


@needs_db
@pytest.mark.parametrize("opted_out_key", ["Lead002@Example.com", "+201000000002"])
def test_opt_out_by_email_or_phone_blocks_every_message(db_client, opted_out_key):
    r = db_client.post("/v1/consents", json={"contact_keys": [opted_out_key],
                                             "status": "opted_out", "source": "test"})
    assert r.status_code == 204
    out = db_client.post("/v1/messages/prepare", json=PREPARE).json()
    assert (out["send"], out["reason"]) == (False, "opted_out")
    other = db_client.post("/v1/messages/prepare", json={
        **PREPARE, "template": "customer_clarification",
        "data": DATA["customer_clarification"]}).json()
    assert other["reason"] == "opted_out"


@needs_db
def test_opting_back_in_allows_messages(db_client):
    body = {"contact_keys": ["lead002@example.com"], "source": "test"}
    db_client.post("/v1/consents", json={**body, "status": "opted_out"})
    db_client.post("/v1/consents", json={**body, "status": "opted_in"})
    assert db_client.post("/v1/messages/prepare", json=PREPARE).json()["send"]


@needs_db
def test_prepare_without_email_or_with_bad_data(db_client):
    assert db_client.post("/v1/messages/prepare", json={**PREPARE, "to_email": None}).json() \
        == {"send": False, "message_id": None, "reason": "no_email", "to": None,
            "subject": None, "text": None, "template_version": None}
    r = db_client.post("/v1/messages/prepare", json={**PREPARE, "data": {}})
    assert r.status_code == 422


@needs_db
def test_demo_with_real_delivery_replaces_stop_line_and_skips_reminders(db_client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("CUSTOMER_EMAIL_DELIVERY", "true")
    reminder = db_client.post("/v1/messages/prepare", json=PREPARE).json()
    assert (reminder["send"], reminder["reason"]) == (False, "demo_no_reminders")
    out = db_client.post("/v1/messages/prepare", json={
        **PREPARE, "template": "customer_clarification",
        "data": DATA["customer_clarification"]}).json()
    assert out["send"] and DEMO_NOTICE in out["text"] and OPT_OUT_LINE not in out["text"]


@needs_db
def test_demo_without_real_delivery_keeps_stop_line(db_client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    out = db_client.post("/v1/messages/prepare", json=PREPARE).json()
    assert out["send"] and OPT_OUT_LINE in out["text"]
