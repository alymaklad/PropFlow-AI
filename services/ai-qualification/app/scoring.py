"""Deterministic, explainable lead scoring (task 1.3).

Rules and thresholds come from data/scoring_rules.json (override with SCORING_RULES_PATH).
AI may extract the signals, but the score is always computed here, never by a model.
"""

import json
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DEFAULT_RULES_PATH = Path(__file__).parent / "data" / "scoring_rules.json"
EXPECTED_RULES = {
    "budget_provided", "timeline_within_3_months", "requirements_complete",
    "explicit_high_intent", "followup_response",
}


@dataclass(frozen=True)
class ScoringInput:
    budget_min: float | None = None
    budget_max: float | None = None
    purchase_timeline_months: int | None = None
    property_type: str | None = None
    location: str | None = None
    bedrooms: int | None = None
    purchase_intent: str = "unknown"
    responded_to_followup: bool = False


@dataclass(frozen=True)
class Component:
    rule: str
    points: int
    reason: str


@dataclass(frozen=True)
class ScoreResult:
    total: int
    components: list[Component]
    priority: str
    rules_version: str


class RulesConfigError(ValueError):
    pass


@cache
def load_rules(path: str | None = None) -> dict:
    rules_path = Path(path or os.environ.get("SCORING_RULES_PATH") or DEFAULT_RULES_PATH)
    config = json.loads(rules_path.read_text(encoding="utf-8"))
    rules = config.get("rules", {})
    if set(rules) != EXPECTED_RULES:
        raise RulesConfigError(f"rules must be exactly {sorted(EXPECTED_RULES)}")
    if sum(r["points"] for r in rules.values()) > 100:
        raise RulesConfigError("rule points must not exceed 100 in total")
    t = config.get("priority_thresholds", {})
    if not 0 < t.get("standard", 0) < t.get("high", 0) <= 100:
        raise RulesConfigError("thresholds must satisfy 0 < standard < high <= 100")
    if not config.get("version"):
        raise RulesConfigError("version is required")
    return config


def score(signals: ScoringInput, config: dict | None = None) -> ScoreResult:
    config = config or load_rules()
    rules = config["rules"]
    components: list[Component] = []

    def add(rule: str, passed: bool, yes: str, no: str) -> None:
        components.append(Component(rule, rules[rule]["points"] if passed else 0,
                                    yes if passed else no))

    has_budget = signals.budget_min is not None or signals.budget_max is not None
    add("budget_provided", has_budget, "budget stated", "no budget stated")

    max_months = rules["timeline_within_3_months"]["max_months"]
    months = signals.purchase_timeline_months
    soon = months is not None and months <= max_months
    add("timeline_within_3_months", soon, f"buying within {months} month(s)",
        "no purchase timeline" if months is None else f"timeline {months} months is beyond "
        f"{max_months}")

    no_bedrooms = set(rules["requirements_complete"]["no_bedrooms_types"])
    missing = [
        name for name, value in (("property type", signals.property_type),
                                 ("location", signals.location))
        if value is None
    ]
    if signals.bedrooms is None and signals.property_type not in no_bedrooms:
        missing.append("bedrooms")
    add("requirements_complete", not missing, "type, location and size known",
        "missing " + ", ".join(missing))

    add("explicit_high_intent", signals.purchase_intent == "high", "explicit high intent",
        f"intent is {signals.purchase_intent}")

    add("followup_response", signals.responded_to_followup, "replied to a follow-up",
        "no follow-up reply yet")

    total = sum(c.points for c in components)
    thresholds = config["priority_thresholds"]
    priority = ("high" if total >= thresholds["high"]
                else "standard" if total >= thresholds["standard"] else "nurture")
    return ScoreResult(total, components, priority, config["version"])
