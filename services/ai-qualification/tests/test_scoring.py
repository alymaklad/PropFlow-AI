import json

import pytest

from app.scoring import RulesConfigError, ScoringInput, load_rules, score
from tests.conftest import load_dataset

FIELDS = ("budget_min", "budget_max", "purchase_timeline_months", "property_type", "location",
          "bedrooms", "purchase_intent")


@pytest.mark.parametrize("record", load_dataset(), ids=lambda r: r["id"])
def test_scores_match_reference_labels(record):
    """'Scoring consistency' metric: agreement with the labeled expectations (must be 100%)."""
    extraction, expected = record["expected"]["extraction"], record["expected"]["score"]
    result = score(ScoringInput(**{f: extraction[f] for f in FIELDS}))
    assert result.total == expected["total"]
    assert result.priority == expected["priority"]
    assert [(c.rule, c.points) for c in result.components] == [
        (c["rule"], c["points"]) for c in expected["components"]
    ]


def test_rules_version_matches_dataset():
    path = load_dataset.__globals__["ROOT"] / "sample-data" / "synthetic-leads.json"
    assert load_rules()["version"] == json.loads(path.read_text())["scoring_rules_version"]


def test_followup_reply_adds_points():
    base = ScoringInput(budget_max=5e6, purchase_timeline_months=2, property_type="apartment",
                        location="Maadi", bedrooms=2, purchase_intent="medium")
    assert score(base).total == 70
    replied = ScoringInput(**{**base.__dict__, "responded_to_followup": True})
    result = score(replied)
    assert (result.total, result.priority) == (80, "high")


def test_every_component_explains_itself():
    result = score(ScoringInput())
    assert result.total == 0 and result.priority == "nurture"
    assert all(c.reason for c in result.components)
    reqs = next(c for c in result.components if c.rule == "requirements_complete")
    assert reqs.reason == "missing property type, location, bedrooms"


def test_land_does_not_need_bedrooms():
    result = score(ScoringInput(property_type="land", location="6th of October"))
    assert next(c for c in result.components if c.rule == "requirements_complete").points == 20


@pytest.mark.parametrize(("patch", "message"), [
    ({"rules": {"budget_provided": {"points": 20}}}, "rules must be exactly"),
    ({"priority_thresholds": {"high": 40, "standard": 50}}, "thresholds"),
    ({"version": ""}, "version"),
])
def test_invalid_rules_config_is_rejected(tmp_path, patch, message):
    config = {**load_rules(), **patch}
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(config))
    with pytest.raises(RulesConfigError, match=message):
        load_rules(str(path))


def test_points_over_100_rejected(tmp_path):
    config = load_rules()
    rules = {k: dict(v) for k, v in config["rules"].items()}
    rules["budget_provided"]["points"] = 50
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({**config, "rules": rules}))
    with pytest.raises(RulesConfigError, match="exceed 100"):
        load_rules(str(path))
