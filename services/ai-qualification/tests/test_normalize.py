import pytest

from app.normalize import (
    BudgetError,
    normalize_bedrooms,
    normalize_email,
    normalize_lead,
    normalize_location,
    normalize_phone,
    normalize_property_type,
    normalize_timeline,
    parse_budget,
)
from tests.conftest import load_dataset

DATASET = load_dataset()


@pytest.mark.parametrize("record", DATASET, ids=lambda r: r["id"])
def test_contact_normalization_matches_dataset(record):
    payload, expected = record["payload"], record["expected"]["normalized"]
    assert normalize_phone(payload.get("phone")) == expected.get("phone")
    assert normalize_email(payload.get("email")) == expected.get("email")


@pytest.mark.parametrize("raw", ["", "   ", None, "12345", "not a phone", "+20 100"])
def test_invalid_phones(raw):
    assert normalize_phone(raw) is None


def test_arabic_indic_phone_digits():
    assert normalize_phone("٠١٠٠٠٠٠٠٠٠١") == "+201000000001"


@pytest.mark.parametrize("raw", ["no-at-sign", "a@b", "two@@example.com", "spa ce@example.com"])
def test_invalid_emails(raw):
    assert normalize_email(raw) is None


@pytest.mark.parametrize(("raw", "expected"), [
    ("6-8 million", (6_000_000, 8_000_000, "EGP")),
    ("6–8 million EGP", (6_000_000, 8_000_000, "EGP")),
    ("6 to 8 million", (6_000_000, 8_000_000, "EGP")),
    ("between 9 and 10 million EGP", (9_000_000, 10_000_000, "EGP")),
    ("12-14M", (12_000_000, 14_000_000, "EGP")),
    ("6-8 mil", (6_000_000, 8_000_000, "EGP")),
    ("up to 15M EGP", (None, 15_000_000, "EGP")),
    ("under 5 million", (None, 5_000_000, "EGP")),
    ("5.5 M", (None, 5_500_000, "EGP")),
    ("7m", (None, 7_000_000, "EGP")),
    ("around 3 million", (None, 3_000_000, "EGP")),
    ("500 thousand EGP", (None, 500_000, "EGP")),
    ("USD 150,000", (None, 150_000, "USD")),
    ("$150k", (None, 150_000, "USD")),
    ("at least 5 million", (5_000_000, None, "EGP")),
    ("2500000", (None, 2_500_000, "EGP")),
    ("من 6 لـ 8 مليون", (6_000_000, 8_000_000, "EGP")),
    ("٣٫٥ مليون", (None, 3_500_000, "EGP")),
    (7_000_000, (None, 7_000_000, "EGP")),
])
def test_parse_budget(raw, expected):
    b = parse_budget(raw)
    assert (b.min, b.max, b.currency) == expected


@pytest.mark.parametrize(("raw", "code"), [
    ("flexible", "budget_unparseable"),
    ("7", "budget_ambiguous_unit"),
    ("min 9 million max 6 million", "budget_min_gt_max"),
    ("9-6 million", "budget_min_gt_max"),
    (0, "budget_unparseable"),
])
def test_parse_budget_errors(raw, code):
    with pytest.raises(BudgetError, match=code):
        parse_budget(raw)


@pytest.mark.parametrize("raw", [None, "", "  "])
def test_empty_budget_is_none(raw):
    assert parse_budget(raw) is None


@pytest.mark.parametrize(("raw", "expected"), [
    ("New Cairo", "New Cairo"), ("nw cairo", "New Cairo"), ("Fifth Settlement", "New Cairo"),
    ("tagamoa", "New Cairo"), ("التجمع الخامس", "New Cairo"), ("Alexandria, Smouha", "Alexandria"),
    ("Sheikh Zayed", "Sheikh Zayed"), ("6th of October", "6th of October"),
    ("New Administrative Capital", "New Capital"), ("el gouna", "El Gouna"),
    ("Atlantis", None), ("", None), (None, None),
])
def test_normalize_location(raw, expected):
    assert normalize_location(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("Apartment", "apartment"), ("flat", "apartment"), ("Twin House", "townhouse"),
    ("shop", "commercial"), ("Villa", "villa"), ("castle", None),
])
def test_normalize_property_type(raw, expected):
    assert normalize_property_type(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    (3, 3), ("3", 3), ("3br", 3), ("3 bedrooms", 3), ("Studio", 0), (0, 0), ("4+", 4),
    ("many", None), (25, None), (-1, None), (None, None), (True, None),
])
def test_normalize_bedrooms(raw, expected):
    assert normalize_bedrooms(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("immediately", 1), ("within_3_months", 3), ("3_6_months", 6), (2, 2), ("4", 4),
    ("soon", None), (0, None), (None, None),
])
def test_normalize_timeline(raw, expected):
    assert normalize_timeline(raw) == expected


def test_structured_form_lead():
    lead = normalize_lead({
        "source": "form", "name": "  Ahmed   Samir ", "phone": "0100-000-0001",
        "email": "Lead001@Example.com", "message": "Interested",
        "property_type": "Apartment", "location": "Fifth Settlement", "bedrooms": "3",
        "budget": "6-8 million", "timeline": "within_3_months", "purchase_stage": "ready_to_buy",
    })
    assert lead.valid and not lead.warnings and not lead.conflicts
    assert (lead.name, lead.phone, lead.email) == ("Ahmed Samir", "+201000000001",
                                                   "lead001@example.com")
    assert lead.contact_key == "+201000000001"
    assert (lead.property_type, lead.location, lead.bedrooms) == ("apartment", "New Cairo", 3)
    assert (lead.budget_min, lead.budget_max, lead.currency) == (6_000_000, 8_000_000, "EGP")
    assert (lead.purchase_timeline_months, lead.purchase_intent) == (3, "high")


def test_lead_without_contact_is_invalid():
    lead = normalize_lead({"name": "X", "message": "hello", "phone": "123"})
    assert not lead.valid
    assert lead.errors == ["contact_missing"]
    assert "phone_invalid" in lead.warnings


def test_lead_without_content_is_invalid():
    lead = normalize_lead({"email": "a@example.com"})
    assert lead.errors == ["content_missing"]


def test_bad_fields_become_warnings_not_errors():
    lead = normalize_lead({
        "name": "N", "email": "a@example.com", "message": "hi", "location": "Atlantis",
        "budget": "flexible",
        "bedrooms": "many", "timeline": "soon", "property_type": "castle",
    })
    assert lead.valid
    assert set(lead.warnings) == {"location_unrecognized", "budget_unparseable",
                                  "bedrooms_invalid", "timeline_invalid",
                                  "property_type_unrecognized"}
    assert lead.location is None and lead.location_raw == "Atlantis"


def test_conflicts_are_reported():
    lead = normalize_lead({"email": "a@example.com", "property_type": "studio", "bedrooms": 4,
                           "budget": "min 9 million max 6 million"})
    assert lead.valid
    assert set(lead.conflicts) == {"studio_with_bedrooms", "budget_min_gt_max"}
    assert lead.budget_min is None and lead.budget_max is None


def test_separate_budget_fields():
    lead = normalize_lead({"email": "a@example.com", "budget_min": "6 million",
                           "budget_max": 8_000_000, "currency": "usd"})
    assert (lead.budget_min, lead.budget_max, lead.currency) == (6_000_000, 8_000_000, "USD")


def test_long_message_is_truncated():
    lead = normalize_lead({"email": "a@example.com", "message": "x" * 6000})
    assert len(lead.message) == 5000 and "message_truncated" in lead.warnings
