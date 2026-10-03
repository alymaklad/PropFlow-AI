"""Next-action routing, salesperson handoff and customer follow-up sequences
(tasks 2.8-2.10; Workflows F and G).

All customer messages go through outbound.prepare (consent check, at-most-once claim, fixed
template). Internal notifications are claimed the same way, so retries never send twice.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.business_time import BusinessCalendar
from app.crm import _m2o_id, fetch_owner, lead_url, schedule_followup, team_manager
from app.messages import next_steps, reason_text
from app.odoo_client import OdooClient
from app.routers.outbound import prepare

HANDOFF_SUMMARY = "PropFlow handoff: contact the customer"
AI_FAILURE_REASONS = {"ai_unavailable", "ai_output_invalid"}
FIRST_REMINDER_AFTER_DAYS = 2
NEXT_REMINDER_AFTER_DAYS = 3


# --- routing -----------------------------------------------------------------------------------

def has_matching_criteria(lead: dict) -> bool:
    return lead.get("location") is not None and (
        lead.get("budget_min") is not None or lead.get("budget_max") is not None)


def decide_route(qualification: dict | None, lead: dict, match_status: str | None,
                 has_email: bool) -> tuple[str, list[str]]:
    """Returns (route, reasons). Routes: opt_out, handoff, shortlist, clarify, rep_only."""
    q = qualification or {}
    if q.get("opt_out"):
        return "opt_out", []
    reasons = list(q.get("reasons", []))
    # Deterministic fallback: when the AI failed but the form already gives enough to search
    # the catalog, carry on without it instead of handing off.
    if set(reasons) <= AI_FAILURE_REASONS and reasons and has_matching_criteria(lead):
        reasons = []
    if lead.get("conflicts") and "conflicting_requirements" not in reasons:
        reasons.append("conflicting_requirements")
    if match_status == "none":
        reasons.append("no_matching_property")
    if reasons:
        return "handoff", reasons
    if not has_email:
        return "rep_only", []  # no way to email the customer: the rep's follow-up covers it
    return ("shortlist" if match_status == "matched" else "clarify"), []


# --- handoff -----------------------------------------------------------------------------------

@dataclass
class HandoffResult:
    escalation_id: UUID
    created: bool
    due_at: datetime
    contact_by: str
    owner: dict | None
    lead_url: str
    messages: list[dict] = field(default_factory=list)


def _deadline(cal: BusinessCalendar, start: datetime, priority: str) -> datetime:
    return cal.add_hours(start, 2) if priority == "high" else cal.add_days(start, 1)


def context_note(lead: dict, reasons: list[str], matches: list[dict], contact_by: str) -> str:
    """Plain text for the lead's chatter (Odoo escapes it)."""
    reqs = [f"{k}={lead[k]}" for k in ("property_type", "location", "bedrooms", "budget_min",
                                       "budget_max", "currency", "delivery_preference",
                                       "purchase_timeline_months") if lead.get(k) is not None]
    lines = [f"PropFlow handed this lead to its salesperson: {reason_text(reasons)}.",
             f"Contact the customer by {contact_by}. Automatic customer messages are paused.",
             "Suggested next step: " + " ".join(next_steps(reasons)),
             "Requirements: " + (", ".join(reqs) or "none extracted"),
             "Matching listings: " + (", ".join(m["listing_id"] for m in matches) or "none")]
    if lead.get("message"):
        lines.append(f"Inquiry: {lead['message']}")
    return "\n".join(lines)


def create_handoff(conn: psycopg.Connection, odoo: OdooClient, cal: BusinessCalendar, *,
                   event_id: UUID, correlation_id: UUID, lead_id: int, user_id: int | None,
                   team_id: int | None, priority: str, reasons: list[str], lead: dict,
                   matches: list[dict], public_url: str, now: datetime) -> HandoffResult:
    url = lead_url(public_url, lead_id)
    existing = conn.execute(
        "SELECT id, due_at, assigned_user_id FROM escalations WHERE event_id = %s",
        (event_id,)).fetchone()
    if existing:
        escalation_id, due_at, assigned = existing
        owner = fetch_owner(odoo, assigned)
        return HandoffResult(escalation_id, False, due_at, cal.describe(due_at), owner, url)

    owner = fetch_owner(odoo, user_id) or team_manager(odoo, team_id)
    due_at = _deadline(cal, now, priority)
    contact_by = cal.describe(due_at)
    odoo.execute("crm.lead", "write", [lead_id], {"propflow_exception_status": "handoff",
                                                  "propflow_automation": "paused"})
    activity_id = None
    if owner:
        activity_id = odoo.execute(
            "crm.lead", "propflow_schedule_activity", [lead_id], HANDOFF_SUMMARY, owner["id"],
            due_at.date().isoformat(), f"Handed off: {reason_text(reasons)}.")
    odoo.execute("crm.lead", "propflow_post_note", [lead_id],
                 context_note(lead, reasons, matches, contact_by))
    with conn.transaction():
        (escalation_id,) = conn.execute(
            """
            INSERT INTO escalations (event_id, correlation_id, odoo_lead_id, odoo_activity_id,
                                     assigned_user_id, assigned_to, priority, reason, due_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            RETURNING id
            """,
            (event_id, correlation_id, lead_id, activity_id, owner and owner["id"],
             owner and owner["name"], priority, ",".join(reasons), due_at),
        ).fetchone() or conn.execute("SELECT id FROM escalations WHERE event_id = %s",
                                     (event_id,)).fetchone()
        conn.execute("UPDATE followup_sequences SET status = 'stopped', stop_reason = "
                     "'handed_off' WHERE odoo_lead_id = %s AND status = 'active'", (lead_id,))
    return HandoffResult(escalation_id, True, due_at, contact_by, owner, url)


def handoff_messages(conn: psycopg.Connection, result: HandoffResult, *, lead_id: int,
                     reasons: list[str], lead: dict) -> list[dict]:
    """Rep notification plus one customer acknowledgement (consent-checked)."""
    messages = []
    owner = result.owner
    if owner and owner.get("email"):
        out = prepare(conn, lead_ref=f"handoff:{result.escalation_id}", to_email=owner["email"],
                      contact_keys=[], template="internal_handoff", sequence_no=1,
                      check_consent=False,
                      data={"owner_name": owner["name"], "lead_id": lead_id, "reasons": reasons,
                            "contact_by": result.contact_by, "lead_url": result.lead_url})
        messages.append({"kind": "rep", **out.model_dump()})
    if owner and owner.get("email"):
        out = prepare(conn, lead_ref=f"handoff:{result.escalation_id}", to_email=lead.get("email"),
                      contact_keys=[k for k in (lead.get("phone"),) if k],
                      template="customer_handoff_ack", sequence_no=1,
                      data={"name": lead.get("name"), "advisor_name": owner["name"],
                            "advisor_email": owner["email"], "advisor_phone": owner.get("phone"),
                            "contact_by": result.contact_by})
        messages.append({"kind": "customer", **out.model_dump()})
    return messages


def check_handoffs(conn: psycopg.Connection, odoo: OdooClient, cal: BusinessCalendar, *,
                   public_url: str, now: datetime) -> dict:
    """Resolve handoffs whose activity is done; remind the rep once when the deadline passes,
    then notify the team manager. Notifications only go out during business hours."""
    rows = conn.execute(
        "SELECT id, odoo_lead_id, odoo_activity_id, assigned_user_id, priority, reason, due_at,"
        " reminded_at, manager_notified_at FROM escalations WHERE status = 'open'"
        " ORDER BY due_at LIMIT 200").fetchall()
    activity_ids = [r[2] for r in rows if r[2]]
    open_activities = {a["id"] for a in odoo.search_read(
        "mail.activity", [("id", "in", activity_ids)], ["id"])} if activity_ids else set()

    resolved, messages = [], []
    for (esc_id, lead_id, activity_id, user_id, priority, reason, due_at, reminded_at,
         manager_notified_at) in rows:
        if activity_id and activity_id not in open_activities:
            conn.execute("UPDATE escalations SET status = 'resolved', resolved_at = now(),"
                         " outcome = 'activity done' WHERE id = %s", (esc_id,))
            resolved.append(str(esc_id))
            continue
        if not cal.is_open(now) or now < due_at:
            continue
        owner = fetch_owner(odoo, user_id)
        base = {"lead_id": lead_id, "contact_by": cal.describe(due_at),
                "lead_url": lead_url(public_url, lead_id), "reasons": reason.split(",")}
        if reminded_at is None and owner and owner.get("email"):
            out = prepare(conn, lead_ref=f"handoff:{esc_id}", to_email=owner["email"],
                          contact_keys=[], template="internal_handoff_reminder", sequence_no=1,
                          check_consent=False, data={**base, "owner_name": owner["name"]})
            messages.append({"kind": "rep", **out.model_dump()})
            conn.execute("UPDATE escalations SET reminded_at = now(),"
                         " reminder_count = reminder_count + 1 WHERE id = %s", (esc_id,))
        elif manager_notified_at is None and now >= _deadline(cal, due_at, priority or ""):
            team = odoo.search_read("crm.lead", [("id", "=", lead_id)], ["team_id"],
                                    context={"active_test": False})
            manager = team_manager(odoo, _m2o_id(team[0]["team_id"])) if team else None
            if manager and manager.get("email"):
                out = prepare(conn, lead_ref=f"handoff:{esc_id}", to_email=manager["email"],
                              contact_keys=[], template="internal_handoff_overdue",
                              sequence_no=1, check_consent=False,
                              data={**base, "manager_name": manager["name"],
                                    "owner_name": owner["name"] if owner else "nobody"})
                messages.append({"kind": "manager", **out.model_dump()})
            else:
                # Nobody to escalate to: the scheduler alerts ops instead.
                messages.append({"kind": "manager", "send": False, "reason": "no_manager",
                                 "lead_id": lead_id, "lead_url": base["lead_url"]})
            conn.execute("UPDATE escalations SET manager_notified_at = now() WHERE id = %s",
                         (esc_id,))
    return {"resolved": resolved, "messages": messages}


# --- follow-up sequences -----------------------------------------------------------------------

def start_sequence(conn: psycopg.Connection, cal: BusinessCalendar, *, lead_id: int,
                   correlation_id: UUID, to_email: str, contact_keys: list[str],
                   name: str | None, requirements: dict, now: datetime) -> dict:
    row = conn.execute(
        """
        INSERT INTO followup_sequences (odoo_lead_id, correlation_id, to_email, contact_keys,
                                        customer_name, requirements, next_due_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (odoo_lead_id) DO NOTHING
        RETURNING id, next_due_at
        """,
        (lead_id, correlation_id, to_email.lower(), [k.lower() for k in contact_keys if k],
         name, Jsonb(requirements), cal.add_days(now, FIRST_REMINDER_AFTER_DAYS)),
    ).fetchone()
    if row is None:
        return {"created": False}
    return {"created": True, "sequence_id": str(row[0]), "next_due_at": row[1].isoformat()}


def _stop_reason(lead: dict | None) -> str | None:
    if lead is None or not lead.get("active", True):
        return "lead_closed"
    if lead.get("probability", 0) >= 100:
        return "won"
    if lead.get("propflow_automation") == "paused":
        return "paused_by_owner"
    if lead.get("propflow_exception_status") == "handoff":
        return "handed_off"
    if lead.get("type") == "opportunity":
        return "owner_took_over"
    return None


def due_followups(conn: psycopg.Connection, odoo: OdooClient, cal: BusinessCalendar, *,
                  now: datetime, limit: int = 50) -> dict:
    """Send due reminders during business hours. Each reminder is checked against the lead's
    current state in Odoo and the consent register first."""
    if not cal.is_open(now):
        return {"messages": [], "stopped": []}
    rows = conn.execute(
        "SELECT id, odoo_lead_id, correlation_id, to_email, contact_keys, customer_name,"
        " requirements, reminders_sent, max_reminders FROM followup_sequences"
        " WHERE status = 'active' AND next_due_at <= %s ORDER BY next_due_at LIMIT %s",
        (now, limit)).fetchall()
    if not rows:
        return {"messages": [], "stopped": []}
    leads = {lead["id"]: lead for lead in odoo.search_read(
        "crm.lead", [("id", "in", [r[1] for r in rows])],
        ["active", "probability", "type", "propflow_automation", "propflow_exception_status",
         "user_id"], context={"active_test": False})}

    messages, stopped = [], []
    for seq_id, lead_id, cid, to_email, keys, name, reqs, sent, max_reminders in rows:
        lead = leads.get(lead_id)
        reason = _stop_reason(lead)
        if reason is None and sent >= max_reminders:
            reason = "completed"
        if reason:
            final = "completed" if reason == "completed" else "stopped"
            conn.execute("UPDATE followup_sequences SET status = %s, stop_reason = %s"
                         " WHERE id = %s", (final, None if final == "completed" else reason,
                                            seq_id))
            stopped.append({"sequence_id": str(seq_id), "reason": reason})
            continue
        number = sent + 1
        advisor = lead["user_id"][1] if lead.get("user_id") else "our sales team"
        out = prepare(conn, lead_ref=str(cid), to_email=to_email, contact_keys=list(keys),
                      template="customer_reminder", sequence_no=number,
                      data={"name": name, "requirements": reqs, "advisor_name": advisor})
        if out.reason in ("opted_out", "demo_no_reminders"):
            conn.execute("UPDATE followup_sequences SET status = 'stopped', stop_reason = %s"
                         " WHERE id = %s", (out.reason, seq_id))
            stopped.append({"sequence_id": str(seq_id), "reason": out.reason})
            continue
        done = number >= max_reminders
        conn.execute(
            "UPDATE followup_sequences SET reminders_sent = %s, status = %s, next_due_at = %s"
            " WHERE id = %s",
            (number, "completed" if done else "active",
             None if done else cal.add_days(now, NEXT_REMINDER_AFTER_DAYS), seq_id))
        messages.append({"kind": "customer", **out.model_dump()})
    return {"messages": messages, "stopped": stopped}



# --- composite next action (one call from the intake workflow) ----------------------------------

ACTION_TEXT = {
    "shortlist": "matching listings were emailed to the customer",
    "clarify": "the customer was asked for the missing details",
    "rep_only": "no customer email on file: please contact them",
}


def next_action(conn: psycopg.Connection, odoo: OdooClient, cal: BusinessCalendar, *,
                event_id: UUID, correlation_id: UUID, lead: dict, qualification: dict | None,
                score: dict, upsert: dict, match: dict, public_url: str,
                now: datetime) -> dict:
    """Decide and carry out the next step after the lead is in Odoo. Returns the route, its
    reasons and the messages to send (already consent-checked and claimed)."""
    route, reasons = decide_route(qualification, lead, match["status"],
                                  has_email=bool(lead.get("email")))
    lead_id, owner = upsert["lead_id"], upsert.get("owner")
    url = lead_url(public_url, lead_id)
    messages: list[dict] = []

    if route == "handoff":
        result = create_handoff(
            conn, odoo, cal, event_id=event_id, correlation_id=correlation_id, lead_id=lead_id,
            user_id=upsert.get("user_id"), team_id=upsert.get("team_id"),
            priority=score["priority"], reasons=reasons, lead=lead,
            matches=match.get("matches", []), public_url=public_url, now=now)
        messages += handoff_messages(conn, result, lead_id=lead_id, reasons=reasons, lead=lead)
        if not result.owner:
            messages.append({"kind": "manager", "send": False, "reason": "no_owner",
                             "lead_id": lead_id, "lead_url": url})
        return {"route": route, "reasons": reasons, "messages": messages,
                "due_at": result.due_at.isoformat()}

    if route == "opt_out":  # normally handled before the upsert; kept safe here too
        return {"route": route, "reasons": [], "messages": []}

    if upsert.get("user_id"):
        schedule_followup(odoo, lead_id=lead_id, user_id=upsert["user_id"],
                          priority=score["priority"], today=cal.local(now).date())
    advisor = owner["name"] if owner else "our sales team"
    if route in ("shortlist", "clarify"):
        template, data = (
            ("customer_shortlist", {"name": lead.get("name"), "requirements": lead,
                                    "matches": match["matches"], "advisor_name": advisor})
            if route == "shortlist" else
            ("customer_clarification", {"name": lead.get("name"),
                                        "missing": match.get("missing", [])}))
        out = prepare(conn, lead_ref=str(correlation_id), to_email=lead.get("email"),
                      contact_keys=[k for k in (lead.get("phone"),) if k], template=template,
                      sequence_no=1, data=data)
        messages.append({"kind": "customer", **out.model_dump()})
        if out.reason != "opted_out":
            start_sequence(conn, cal, lead_id=lead_id, correlation_id=correlation_id,
                           to_email=lead["email"],
                           contact_keys=[k for k in (lead.get("phone"),) if k],
                           name=lead.get("name"),
                           requirements={k: lead.get(k) for k in (
                               "property_type", "location", "bedrooms", "budget_min",
                               "budget_max", "currency")},
                           now=now)
    if score["priority"] == "high" and owner and owner.get("email"):
        out = prepare(conn, lead_ref=str(correlation_id), to_email=owner["email"],
                      contact_keys=[], template="internal_high_priority", sequence_no=1,
                      check_consent=False,
                      data={"owner_name": owner["name"], "lead_id": lead_id, "score": score,
                            "action": ACTION_TEXT[route], "lead_url": url})
        messages.append({"kind": "rep", **out.model_dump()})
    if not owner:
        messages.append({"kind": "manager", "send": False, "reason": "no_owner",
                         "lead_id": lead_id, "lead_url": url})
    return {"route": route, "reasons": reasons, "messages": messages, "due_at": None}
