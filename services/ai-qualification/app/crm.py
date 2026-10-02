"""Idempotent lead upsert into Odoo (task 1.4) and follow-up scheduling.

Deterministic code only: it receives normalized, validated data and a computed score. The LLM
code path never calls this module (see docs/architecture.md, ownership rules).

Upsert order:
1. A lead with this correlation id exists: update it. This covers a retry after a create whose
   response was lost.
2. An open lead exists for the same contact (E.164 phone or email): add the new inquiry to it
   as a note and keep its owner. Only requirements the lead is *missing* are filled in; the
   lead's existing values and score are left alone (a rep may have edited them, and a partial
   follow-up message must not downgrade a hot lead). The new inquiry's details and score are
   in the note.
3. Otherwise assign an owner round-robin and create the lead. If a concurrent request created
   it first (unique correlation id), fall back to step 1.
"""

import html
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal
from uuid import UUID

import psycopg

from app.assignment import active_salespeople, assign, resolve_team_id
from app.odoo_client import OdooClient, OdooDuplicateError

LEAD_FIELDS = ["id", "user_id", "team_id", "propflow_correlation_id"]
REQUIREMENT_FIELDS = ["propflow_property_type", "propflow_location", "propflow_bedrooms",
                      "propflow_budget_min", "propflow_budget_max", "propflow_currency",
                      "propflow_timeline_months"]
REQUIREMENT_KEYS = ("property_type", "location", "bedrooms", "budget_min", "budget_max",
                    "currency", "purchase_timeline_months")
FOLLOWUP_SUMMARY = "PropFlow follow-up"
# Business days until the follow-up is due, by priority (0 = today).
FOLLOWUP_BUSINESS_DAYS = {"high": 0, "standard": 1, "nurture": 3}
WEEKEND = {4, 5}  # Friday, Saturday (Egypt)


@dataclass
class UpsertResult:
    lead_id: int
    action: Literal["created", "updated", "matched_contact"]
    user_id: int | None
    team_id: int | None
    warnings: list[str] = field(default_factory=list)


def _m2o_id(value: Any) -> int | None:
    return value[0] if value else None


def lead_name(lead: dict) -> str:
    what = (lead.get("property_type") or "property").replace("_", " ").capitalize()
    where = f" in {lead['location']}" if lead.get("location") else ""
    who = lead.get("name") or lead.get("contact_key") or "unknown contact"
    return f"{what}{where} – {who}"


def score_explanation(score: dict) -> str:
    lines = [f"Total {score['total']} ({score['priority']}), rules {score['rules_version']}"]
    lines += [f"{c['rule']}: +{c['points']} ({c['reason']})" for c in score["components"]]
    return "\n".join(lines)


def requirement_values(lead: dict, *, only_present: bool) -> dict:
    bedrooms = lead.get("bedrooms")
    values = {
        "propflow_property_type": lead.get("property_type"),
        "propflow_location": lead.get("location") or lead.get("location_raw"),
        "propflow_bedrooms": str(min(bedrooms, 6)) if bedrooms is not None else None,
        "propflow_budget_min": lead.get("budget_min"),
        "propflow_budget_max": lead.get("budget_max"),
        "propflow_currency": lead.get("currency"),
        "propflow_timeline_months": lead.get("purchase_timeline_months"),
    }
    if only_present:
        return {k: v for k, v in values.items() if v is not None}
    return {k: (v if v is not None else False) for k, v in values.items()}


def score_values(score: dict, exception_status: str) -> dict:
    return {
        "propflow_score": score["total"],
        "propflow_priority": score["priority"],
        "propflow_rules_version": score["rules_version"],
        "propflow_score_explanation": score_explanation(score),
        "propflow_exception_status": exception_status,
    }


def inquiry_note(lead: dict, score: dict, correlation_id: UUID) -> str:
    """Plain text; Odoo escapes it (propflow_post_note)."""
    parts = [f"New inquiry for this contact via {lead['source']} (correlation {correlation_id})."]
    if lead.get("message"):
        parts.append(f"Message: {lead['message']}")
    reqs = [f"{k}={lead[k]}" for k in REQUIREMENT_KEYS if lead.get(k) is not None]
    if reqs:
        parts.append("Requirements: " + ", ".join(reqs))
    parts.append(f"Score: {score['total']} ({score['priority']})")
    return "\n".join(parts)


def find_by_correlation(odoo: OdooClient, correlation_id: UUID) -> dict | None:
    found = odoo.search_read("crm.lead", [("propflow_correlation_id", "=", str(correlation_id))],
                             LEAD_FIELDS, limit=1, context={"active_test": False})
    return found[0] if found else None


def find_open_lead_for_contact(odoo: OdooClient, phone: str | None,
                               email: str | None) -> dict | None:
    conditions = []
    if phone:
        conditions += [("phone_sanitized", "=", phone), ("phone", "=", phone)]
    if email:
        conditions.append(("email_normalized", "=", email))
    if not conditions:
        return None
    domain = ["|"] * (len(conditions) - 1) + conditions + [("probability", "<", 100)]
    found = odoo.search_read("crm.lead", domain, LEAD_FIELDS + REQUIREMENT_FIELDS, limit=1,
                             order="create_date desc")
    return found[0] if found else None


def missing_requirement_values(lead: dict, existing: dict) -> dict:
    """New values only for requirement fields the existing lead has no value for."""
    return {k: v for k, v in requirement_values(lead, only_present=True).items()
            if not existing.get(k)}


def upsert_lead(odoo: OdooClient, conn: psycopg.Connection, *, correlation_id: UUID, lead: dict,
                score: dict, exception_status: str = "none",
                configured_team_id: int | None = None) -> UpsertResult:
    existing = find_by_correlation(odoo, correlation_id)
    if existing:
        odoo.execute("crm.lead", "write", [existing["id"]], {
            **requirement_values(lead, only_present=False), **score_values(score, exception_status),
        })
        return UpsertResult(existing["id"], "updated", _m2o_id(existing["user_id"]),
                            _m2o_id(existing["team_id"]))

    match = find_open_lead_for_contact(odoo, lead.get("phone"), lead.get("email"))
    if match:
        values = missing_requirement_values(lead, match)
        if exception_status != "none":
            values["propflow_exception_status"] = exception_status
        if values:
            odoo.execute("crm.lead", "write", [match["id"]], values)
        odoo.execute("crm.lead", "propflow_post_note", [match["id"]],
                     inquiry_note(lead, score, correlation_id))
        return UpsertResult(match["id"], "matched_contact", _m2o_id(match["user_id"]),
                            _m2o_id(match["team_id"]))

    team_id = resolve_team_id(odoo, configured_team_id)
    assignment = assign(conn, correlation_id, team_id, active_salespeople(odoo, team_id))
    warnings = [] if assignment.user_id else ["no_salespeople"]
    message = lead.get("message") or ""
    values = {
        "name": lead_name(lead),
        "type": "lead",
        "contact_name": lead.get("name") or False,
        "email_from": lead.get("email") or False,
        "phone": lead.get("phone") or False,
        "description": html.escape(message).replace("\n", "<br>"),
        "user_id": assignment.user_id or False,
        "team_id": team_id,
        "propflow_correlation_id": str(correlation_id),
        "propflow_source": lead["source"],
        "propflow_original_message": message or False,
        **requirement_values(lead, only_present=False),
        **score_values(score, exception_status),
    }
    try:
        lead_id = odoo.execute("crm.lead", "create", [values],
                               context={"mail_create_nosubscribe": True})
    except OdooDuplicateError:
        existing = find_by_correlation(odoo, correlation_id)
        if not existing:
            raise
        return UpsertResult(existing["id"], "updated", _m2o_id(existing["user_id"]),
                            _m2o_id(existing["team_id"]), warnings)
    if isinstance(lead_id, list):
        lead_id = lead_id[0]
    return UpsertResult(lead_id, "created", assignment.user_id, team_id, warnings)


def add_business_days(start: date, days: int, weekend: set[int] = WEEKEND) -> date:
    current = start
    while current.weekday() in weekend:
        current += timedelta(days=1)
    for _ in range(days):
        current += timedelta(days=1)
        while current.weekday() in weekend:
            current += timedelta(days=1)
    return current


def schedule_followup(odoo: OdooClient, *, lead_id: int, user_id: int, priority: str,
                      today: date) -> tuple[int, date]:
    deadline = add_business_days(today, FOLLOWUP_BUSINESS_DAYS[priority])
    activity_id = odoo.execute(
        "crm.lead", "propflow_schedule_activity", [lead_id], FOLLOWUP_SUMMARY, user_id,
        deadline.isoformat(), f"PropFlow {priority}-priority lead: contact the customer.",
    )  # also sets the lead's next follow-up date, in the same transaction
    return activity_id, deadline
