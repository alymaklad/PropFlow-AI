import uuid

from app.config import Settings
from app.deps import get_llm
from app.llm import EMPTY_EXTRACTION, FakeLLM, LLMUnavailable
from app.main import app
from app.qualification import qualify
from tests.conftest import needs_db

LEAD = {"valid": True, "source": "form", "name": "Sara", "phone": None,
        "email": "lead002@example.com", "contact_key": "lead002@example.com",
        "message": "Looking for a 4 bedroom villa in Sheikh Zayed, up to 15M, buying in 2 "
                   "months, ready to book a viewing.",
        "property_type": None, "location": None, "location_raw": None, "bedrooms": None,
        "budget_min": None, "budget_max": None, "currency": None,
        "purchase_timeline_months": None, "purchase_intent": "unknown",
        "errors": [], "warnings": [], "conflicts": []}
MODEL_OUT = {**EMPTY_EXTRACTION, "inquiry_type": "purchase", "property_type": "villa",
             "location": "Sheikh Zayed", "bedrooms": 4, "budget_max": 15_000_000,
             "currency": "EGP", "purchase_timeline_months": 2, "purchase_intent": "high",
             "confidence": 0.92}


@needs_db
def test_qualify_merges_and_records_trace(db_client, migrated_db):
    app.dependency_overrides[get_llm] = lambda: FakeLLM(script=[MODEL_OUT])
    claim = db_client.post("/v1/intake/claim", json={"raw_payload": {"m": 1}}).json()
    r = db_client.post("/v1/qualify", json={"correlation_id": claim["correlation_id"],
                                            "event_id": claim["event_id"], "lead": LEAD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["needs_human_review"]) == ("valid", False)
    assert body["lead"]["property_type"] == "villa" and body["lead"]["budget_max"] == 15_000_000
    score = db_client.post("/v1/score", json=body["lead"]).json()
    assert (score["total"], score["priority"]) == (90, "high")
    row = migrated_db.execute(
        "SELECT validation_status, model, prompt_version, needs_human_review, attempts"
        " FROM qualifications").fetchone()
    assert row == ("valid", "fake", "qualify-v1", False, 1)


@needs_db
def test_provider_down_returns_fallback_not_error(db_client, migrated_db):
    app.dependency_overrides[get_llm] = lambda: FakeLLM(script=[LLMUnavailable("down")])
    r = db_client.post("/v1/qualify", json={"correlation_id": str(uuid.uuid4()), "lead": LEAD})
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["needs_human_review"], body["reasons"]) == \
        ("fallback", True, ["ai_unavailable"])
    assert body["lead"]["property_type"] is None  # form fields only
    assert migrated_db.execute("SELECT count(*) FROM qualifications").fetchone()[0] == 0



def test_runtime_fake_or_none_provider_means_ai_off():
    for provider in ("none", "fake"):
        llm = get_llm(Settings(database_url=None, api_key=None, llm_provider=provider))
        result = qualify(llm, "3 bedroom flat in Maadi")
        assert (result.status, result.reasons) == ("fallback", ["ai_unavailable"])
        assert result.needs_human_review
