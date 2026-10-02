import uuid

import pytest

from app.matching import find_matches
from tests.conftest import ROOT, load_dataset, needs_db

SEED = (ROOT / "database" / "seeds" / "properties.sql").read_text()
LABELS = {r["id"]: r["expected"]["extraction"] for r in load_dataset()}


@pytest.fixture
def catalog(migrated_db):
    migrated_db.execute(SEED)
    return migrated_db


def lead(**kw):
    base = {k: None for k in ("property_type", "location", "bedrooms", "budget_min",
                              "budget_max", "currency", "delivery_preference")}
    return {**base, "conflicts": [], **kw}


def from_label(record_id):
    labels = LABELS[record_id]
    return lead(**{k: labels[k] for k in ("property_type", "location", "bedrooms", "budget_min",
                                          "budget_max", "currency", "delivery_preference")})


@needs_db
@pytest.mark.parametrize("record_id", ["L048", "L049", "L050"])
def test_dataset_no_match_cases_find_nothing(catalog, record_id):
    assert find_matches(catalog, from_label(record_id)).status == "none"


@needs_db
@pytest.mark.parametrize(("record_id", "expected_first"), [
    ("L001", "NC-APT-102"),   # New Cairo 3br 6-8M ready
    ("L002", "SZ-VIL-201"),   # Sheikh Zayed 4br villa up to 15M
    ("L003", "MAD-APT-101"),  # Maadi 2br under 5M
    ("L052", "HRG-APT-102"),  # Hurghada 2br USD 150k
])
def test_dataset_requests_with_inventory_match(catalog, record_id, expected_first):
    result = find_matches(catalog, from_label(record_id))
    assert result.status == "matched"
    assert result.matches[0]["listing_id"] == expected_first


@needs_db
def test_reserved_sold_and_stale_listings_are_never_returned(catalog):
    result = find_matches(catalog, lead(location="New Cairo", property_type="apartment",
                                        bedrooms=3, budget_max=8_000_000))
    ids = {m["listing_id"] for m in result.matches}
    assert "NC-APT-105" not in ids and "NC-APT-106" not in ids
    result = find_matches(catalog, lead(location="Sheikh Zayed", property_type="villa",
                                        bedrooms=4, budget_max=14_100_000))
    assert "SZ-VIL-205" not in {m["listing_id"] for m in result.matches}
    assert all(m["verified_days_ago"] <= 14 for m in result.matches)


@needs_db
def test_price_tolerance_and_ordering(catalog):
    result = find_matches(catalog, lead(location="New Cairo", property_type="villa",
                                        bedrooms=4, budget_max=14_000_000))
    assert [m["listing_id"] for m in result.matches] == ["NC-VIL-201"]  # 14.5M within 5%


@needs_db
def test_delivery_preference_filter(catalog):
    ready = find_matches(catalog, lead(location="Sheikh Zayed", property_type="apartment",
                                       bedrooms=3, budget_max=8e6, delivery_preference="ready"))
    assert ready.status == "none"
    off_plan = find_matches(catalog, lead(location="Sheikh Zayed", property_type="apartment",
                                          bedrooms=3, budget_max=8e6,
                                          delivery_preference="off_plan"))
    assert {m["listing_id"] for m in off_plan.matches} == {"SZ-APT-101", "SZ-APT-102"}


@needs_db
def test_currency_must_match(catalog):
    result = find_matches(catalog, lead(location="Hurghada", bedrooms=2, budget_max=150_000))
    assert result.status == "none"  # EGP budget of 150k: the USD listing is not comparable


@needs_db
def test_insufficient_criteria_and_conflict(catalog):
    result = find_matches(catalog, lead(property_type="villa", budget_max=8e6))
    assert (result.status, result.missing) == ("insufficient_criteria", ["location"])
    result = find_matches(catalog, lead(location="Maadi"))
    assert result.missing == ["budget"]
    result = find_matches(catalog, lead(location="Maadi", budget_max=4e6,
                                        conflicts=["studio_with_bedrooms"]))
    assert result.status == "conflict"


@needs_db
def test_match_endpoint_records_outcome(catalog, db_client):
    body = {"valid": True, "source": "form", "name": "X", "phone": None,
            "email": "x@example.com", "contact_key": "x@example.com", "message": None,
            "property_type": "studio", "location": "Zamalek", "location_raw": "Zamalek",
            "bedrooms": 0, "budget_min": None, "budget_max": 3_500_000, "currency": "EGP",
            "purchase_timeline_months": None, "purchase_intent": "low",
            "errors": [], "warnings": [], "conflicts": []}
    r = db_client.post("/v1/match", json={"correlation_id": str(uuid.uuid4()), "lead": body})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "matched"
    assert [m["listing_id"] for m in r.json()["matches"]] == ["ZAM-STU-701", "ZAM-STU-702"]
    row = catalog.execute("SELECT status, listing_ids FROM match_results").fetchone()
    assert row == ("matched", ["ZAM-STU-701", "ZAM-STU-702"])
