"""Inbound email (task 3.1): replies to our messages vs new inquiries.

A reply is recognised by its In-Reply-To/References headers matching the provider message id
of something we sent (stored in outbound_messages), or, as a fallback, by a "Re:" subject from
an address with active reminders. New inquiries are forwarded to the intake webhook so they
follow exactly the same path as web-form leads.
"""

import re
from datetime import datetime
from uuid import UUID

import psycopg

from app.business_time import BusinessCalendar
from app.crm import fetch_owner, lead_url
from app.odoo_client import OdooClient
from app.qualification import _OPT_OUT
from app.routers.outbound import prepare
from app.scoring import load_rules

REPLY_SUBJECT = re.compile(r"^\s*(re|aw|sv|antw)\s*:", re.I)
QUOTE_START = re.compile(r"^(on .+ wrote:|-{2,}\s*original message|from:\s.+|>)", re.I)
REPLIED_SUMMARY = "PropFlow: customer replied"


def strip_quoted(text: str) -> str:
    """The new part of a reply: everything before the quoted original."""
    kept = []
    for line in (text or "").splitlines():
        if QUOTE_START.match(line.strip()):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def is_opt_out(text: str) -> bool:
    return any(p.search(text) for p in _OPT_OUT)


def find_reply_lead(conn: psycopg.Connection, message_ids: list[str], from_email: str,
                    subject: str) -> int | None:
    # Compare without angle brackets: headers carry "<id@host>", some tools show "id@host".
    ids = [m.strip().strip("<>") for m in message_ids if m and m.strip().strip("<>")]
    if ids:
        row = conn.execute(
            "SELECT lead_ref FROM outbound_messages WHERE btrim(provider_msg_id, '<>') = ANY(%s)"
            " ORDER BY created_at DESC LIMIT 1", (ids,)).fetchone()
        if row:
            lead_ref = row[0]
            if lead_ref.startswith("handoff:"):
                found = conn.execute("SELECT odoo_lead_id FROM escalations WHERE id = %s",
                                     (lead_ref.split(":", 1)[1],)).fetchone()
            else:
                found = conn.execute(
                    "SELECT odoo_lead_id FROM intake_events WHERE correlation_id = %s"
                    " AND odoo_lead_id IS NOT NULL LIMIT 1", (lead_ref,)).fetchone()
            if found and found[0]:
                return found[0]
    if REPLY_SUBJECT.match(subject or ""):
        row = conn.execute(
            "SELECT odoo_lead_id FROM followup_sequences WHERE lower(to_email) = lower(%s)"
            " AND status = 'active' ORDER BY created_at DESC LIMIT 1", (from_email,)).fetchone()
        if row:
            return row[0]
    return None


def record_opt_out(conn: psycopg.Connection, keys: list[str], source: str) -> None:
    keys = sorted({k.strip().lower() for k in keys if k})
    with conn.transaction():
        for key in keys:
            conn.execute(
                "INSERT INTO consents (contact_key, channel, status, source)"
                " VALUES (%s, 'email', 'opted_out', %s) ON CONFLICT (contact_key, channel)"
                " DO UPDATE SET status = 'opted_out', source = EXCLUDED.source,"
                " updated_at = now()", (key, source))
        conn.execute(
            "UPDATE followup_sequences SET status = 'stopped', stop_reason = 'opted_out'"
            " WHERE status = 'active' AND (lower(to_email) = ANY(%s) OR contact_keys && %s)",
            (keys, keys))


def rescore_for_reply(odoo: OdooClient, lead_id: int) -> dict:
    """Award the follow-up-response points once, recomputing the priority."""
    rules = load_rules()
    points = rules["rules"]["followup_response"]["points"]
    lead = odoo.search_read("crm.lead", [("id", "=", lead_id)],
                            ["propflow_score", "propflow_score_explanation", "user_id"],
                            context={"active_test": False})[0]
    explanation = lead.get("propflow_score_explanation") or ""
    old = lead.get("propflow_score") or 0
    marker = re.compile(r"^followup_response: \+0 .*$", re.M)
    if not marker.search(explanation):
        return {"before": old, "after": old, "changed": False, "user_id": lead["user_id"]}
    new = min(old + points, 100)
    thresholds = rules["priority_thresholds"]
    priority = ("high" if new >= thresholds["high"]
                else "standard" if new >= thresholds["standard"] else "nurture")
    explanation = marker.sub(f"followup_response: +{points} (customer replied)", explanation)
    explanation = re.sub(r"^Total \d+ \(\w+\)", f"Total {new} ({priority})", explanation, count=1)
    odoo.execute("crm.lead", "write", [lead_id], {
        "propflow_score": new, "propflow_priority": priority,
        "propflow_score_explanation": explanation})
    return {"before": old, "after": new, "priority": priority, "changed": True,
            "user_id": lead["user_id"]}


def handle_reply(conn: psycopg.Connection, odoo: OdooClient, cal: BusinessCalendar, *,
                 event_id: UUID, lead_id: int, from_email: str, text: str, public_url: str,
                 now: datetime) -> dict:
    new_text = strip_quoted(text) or "(empty reply)"
    if is_opt_out(new_text):
        record_opt_out(conn, [from_email], "email reply")
        odoo.execute("crm.lead", "propflow_post_note", [lead_id],
                     "The customer opted out by email reply. PropFlow will not email them "
                     "again.")
        return {"action": "opted_out", "messages": []}

    conn.execute("UPDATE followup_sequences SET status = 'stopped', stop_reason ="
                 " 'customer_replied' WHERE odoo_lead_id = %s AND status = 'active'",
                 (lead_id,))
    odoo.execute("crm.lead", "propflow_post_note", [lead_id],
                 f"The customer replied by email:\n{new_text}")
    odoo.execute("crm.lead", "write", [lead_id],
                 {"propflow_last_contact": now.strftime("%Y-%m-%d %H:%M:%S")})
    score = rescore_for_reply(odoo, lead_id)
    owner_id = score["user_id"][0] if score.get("user_id") else None
    messages = []
    owner = fetch_owner(odoo, owner_id)
    if owner:
        due = cal.next_open(now)
        odoo.execute("crm.lead", "propflow_schedule_activity", [lead_id], REPLIED_SUMMARY,
                     owner["id"], due.date().isoformat(), "Read the reply and respond.")
        if owner.get("email"):
            out = prepare(conn, lead_ref=f"reply:{event_id}", to_email=owner["email"],
                          contact_keys=[], template="internal_customer_replied",
                          sequence_no=1, check_consent=False,
                          data={"owner_name": owner["name"], "lead_id": lead_id,
                                "reply": new_text[:1500], "lead_url": lead_url(public_url,
                                                                               lead_id)})
            messages.append({"kind": "rep", **out.model_dump()})
    return {"action": "reply_recorded", "score": {k: v for k, v in score.items()
                                                  if k != "user_id"}, "messages": messages}
