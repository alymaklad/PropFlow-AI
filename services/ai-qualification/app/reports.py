"""Operational report (task 3.7; Workflow H in the project description).

Every metric states its window and, for rates, its numerator and denominator. Counts come
from the PropFlow ledger; workload and overdue activities come from Odoo (shown as
unavailable if Odoo cannot be reached, so the report still goes out).
"""

from datetime import datetime, timedelta
from statistics import median

import psycopg

from app.business_time import BusinessCalendar
from app.odoo_client import OdooClient, OdooError

PERIODS = {"day": timedelta(days=1), "week": timedelta(days=7)}
PROPFLOW_ACTIVITIES = ["PropFlow follow-up", "PropFlow handoff: contact the customer",
                       "PropFlow: customer replied"]


def ratio(num: int, den: int) -> dict:
    return {"numerator": num, "denominator": den, "rate": round(num / den, 4) if den else None}


def _counts(conn: psycopg.Connection, sql: str, params: tuple) -> dict[str, int]:
    return {str(k): v for k, v in conn.execute(sql, params).fetchall()}


def build_report(conn: psycopg.Connection, odoo: OdooClient | None, cal: BusinessCalendar, *,
                 start: datetime, end: datetime) -> dict:
    w = (start, end)
    inquiries = "kind = 'inquiry' AND received_at >= %s AND received_at < %s"

    by_source = _counts(conn, f"SELECT source, count(*) FROM intake_events WHERE {inquiries}"
                              " GROUP BY 1", w)
    by_status = _counts(conn, f"SELECT status, count(*) FROM intake_events WHERE {inquiries}"
                              " GROUP BY 1", w)
    crm_actions = _counts(conn, f"SELECT crm_action, count(*) FROM intake_events WHERE"
                                f" {inquiries} AND crm_action IS NOT NULL GROUP BY 1", w)
    received = sum(by_source.values())
    rejected = by_status.get("rejected", 0)
    completed = by_status.get("completed", 0)
    failed = by_status.get("failed", 0)
    valid = received - rejected
    with_lead = conn.execute(f"SELECT count(*) FROM intake_events WHERE {inquiries}"
                             " AND odoo_lead_id IS NOT NULL", w).fetchone()[0]
    closed_without_lead = conn.execute(
        f"SELECT count(*) FROM intake_events WHERE {inquiries} AND status = 'completed'"
        " AND odoo_lead_id IS NULL", w).fetchone()[0]

    priorities = _counts(conn, """
        SELECT s.priority, count(*) FROM (
            SELECT DISTINCT ON (s.event_id) s.event_id, s.priority
              FROM score_results s JOIN intake_events e ON e.id = s.event_id
             WHERE e.kind = 'inquiry' AND e.received_at >= %s AND e.received_at < %s
             ORDER BY s.event_id, s.created_at DESC) s
        GROUP BY 1""", w)
    scored = sum(priorities.values())

    matches = _counts(conn, """
        SELECT m.status, count(*) FROM (
            SELECT DISTINCT ON (m.event_id) m.status
              FROM match_results m JOIN intake_events e ON e.id = m.event_id
             WHERE e.kind = 'inquiry' AND e.received_at >= %s AND e.received_at < %s
             ORDER BY m.event_id, m.created_at DESC) m
        GROUP BY 1""", w)
    ai = _counts(conn, "SELECT q.validation_status, count(*) FROM qualifications q"
                       " JOIN intake_events e ON e.id = q.event_id"
                       " WHERE e.received_at >= %s AND e.received_at < %s GROUP BY 1", w)

    # Time from intake to the first customer email actually sent (shortlist, question or
    # handoff acknowledgement).
    response_minutes = [r[0] for r in conn.execute("""
        SELECT EXTRACT(EPOCH FROM min(o.sent_at) - e.received_at) / 60
          FROM intake_events e
          LEFT JOIN escalations x ON x.event_id = e.id
          JOIN outbound_messages o
            ON o.template LIKE 'customer_%%' AND o.status IN ('sent', 'delivered')
           AND o.sent_at IS NOT NULL  -- rows sent before sent_at existed have no timing
           AND (o.lead_ref = e.correlation_id::text OR o.lead_ref = 'handoff:' || x.id::text)
         WHERE e.kind = 'inquiry' AND e.received_at >= %s AND e.received_at < %s
         GROUP BY e.id, e.received_at""", w).fetchall()]

    sequences = _counts(conn, "SELECT coalesce(stop_reason, status), count(*)"
                              " FROM followup_sequences WHERE created_at >= %s"
                              " AND created_at < %s GROUP BY 1", w)
    reminders_sent = conn.execute(
        "SELECT count(*) FROM outbound_messages WHERE template = 'customer_reminder'"
        " AND sent_at >= %s AND sent_at < %s", w).fetchone()[0]
    messages = _counts(conn, "SELECT template || ':' || status, count(*) FROM outbound_messages"
                             " WHERE created_at >= %s AND created_at < %s GROUP BY 1", w)
    replies = conn.execute("SELECT count(*) FROM intake_events WHERE kind = 'reply'"
                           " AND received_at >= %s AND received_at < %s", w).fetchone()[0]

    handoff_rows = conn.execute(
        "SELECT reason, status, due_at, reminded_at, manager_notified_at FROM escalations"
        " WHERE created_at >= %s AND created_at < %s", w).fetchall()
    reasons: dict[str, int] = {}
    for reason, *_ in handoff_rows:
        for r in filter(None, reason.split(",")):
            reasons[r] = reasons.get(r, 0) + 1
    open_handoffs = sum(1 for r in handoff_rows if r[1] == "open")
    overdue_open = conn.execute("SELECT count(*) FROM escalations WHERE status = 'open'"
                                " AND due_at < %s", (end,)).fetchone()[0]

    dead_letters = _counts(conn, "SELECT status, count(*) FROM dead_letters"
                                 " WHERE created_at >= %s AND created_at < %s GROUP BY 1", w)
    open_dead_letters = conn.execute("SELECT count(*) FROM dead_letters WHERE status = 'open'"
                                     ).fetchone()[0]

    workload, overdue_activities, odoo_status = {}, None, "ok"
    assignments = conn.execute("SELECT user_id, count(*) FROM lead_assignments"
                               " WHERE assigned_at >= %s AND assigned_at < %s GROUP BY 1",
                               w).fetchall()
    try:
        if odoo is None:
            raise OdooError("Odoo not configured")
        user_ids = [u for u, _ in assignments]
        names = {u["id"]: u["name"] for u in odoo.search_read(
            "res.users", [("id", "in", user_ids)], ["name"])} if user_ids else {}
        open_leads = odoo.search_read(
            "crm.lead", [("propflow_correlation_id", "!=", False), ("probability", "<", 100)],
            ["user_id"])
        open_by_user: dict[str, int] = {}
        for lead in open_leads:
            who = lead["user_id"][1] if lead["user_id"] else "unassigned"
            open_by_user[who] = open_by_user.get(who, 0) + 1
        for user_id, count in assignments:
            name = names.get(user_id, f"user {user_id}")
            workload[name] = {"assigned_in_window": count,
                              "open_leads": open_by_user.get(name, 0)}
        for name, count in open_by_user.items():
            workload.setdefault(name, {"assigned_in_window": 0, "open_leads": count})
        overdue_activities = len(odoo.search_read(
            "mail.activity", [("res_model", "=", "crm.lead"),
                              ("summary", "in", PROPFLOW_ACTIVITIES),
                              ("date_deadline", "<", cal.local(end).date().isoformat())],
            ["id"]))
    except OdooError as exc:
        odoo_status = f"unavailable: {exc}"

    return {
        "window": {"start": cal.local(start).isoformat(timespec="minutes"),
                   "end": cal.local(end).isoformat(timespec="minutes"), "timezone": str(cal.tz)},
        "intake": {
            "received_by_source": by_source, "received": received,
            "outcomes": by_status, "rejected_invalid": rejected,
            "intake_success_rate": ratio(completed, valid),
            "crm_actions": crm_actions,
            "closed_without_lead": closed_without_lead,
        },
        "qualification": {
            "priority_distribution": priorities,
            "qualified_rate": ratio(priorities.get("high", 0) + priorities.get("standard", 0),
                                    scored),
            "ai_outcomes": ai,
        },
        "crm_sync": {"success_rate": ratio(with_lead, with_lead + failed),
                     "failed": failed},
        "first_response_minutes": {
            "count": len(response_minutes),
            "denominator_note": "events whose first customer email was sent in the window",
            "average": round(sum(response_minutes) / len(response_minutes), 1)
            if response_minutes else None,
            "median": round(median(response_minutes), 1) if response_minutes else None,
        },
        "matching": {"outcomes": matches, "matched_rate": ratio(matches.get("matched", 0),
                                                                 sum(matches.values()))},
        "followups": {"sequences_started_by_outcome": sequences, "reminders_sent":
                      reminders_sent, "customer_replies": replies,
                      "overdue_propflow_activities": overdue_activities},
        "handoffs": {"created": len(handoff_rows), "still_open": open_handoffs,
                     "overdue_open_now": overdue_open, "by_reason": reasons,
                     "reminded": sum(1 for r in handoff_rows if r[3]),
                     "escalated_to_manager": sum(1 for r in handoff_rows if r[4])},
        "messages": messages,
        "failures": {"dead_letters_by_status": dead_letters,
                     "open_dead_letters_now": open_dead_letters},
        "workload": workload,
        "odoo": odoo_status,
    }


def _pct(r: dict) -> str:
    if r["rate"] is None:
        return f"n/a (0 of {r['denominator']})"
    return f"{r['rate'] * 100:.1f}% ({r['numerator']} of {r['denominator']})"


def _kv(d: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items())) or "none"


def render_text(report: dict, title: str) -> str:
    i, q, f, h = report["intake"], report["qualification"], report["followups"], report["handoffs"]
    fr = report["first_response_minutes"]
    workload_lines = [f"  {name}: {v['assigned_in_window']} / {v['open_leads']}"
                      for name, v in sorted(report["workload"].items())] or ["  none"]
    lines = [
        title, f"Window: {report['window']['start']} to {report['window']['end']} "
        f"({report['window']['timezone']})", "",
        "INTAKE",
        f"  Inquiries received: {i['received']} ({_kv(i['received_by_source'])})",
        f"  Outcomes: {_kv(i['outcomes'])}",
        f"  Intake success rate (completed / valid): {_pct(i['intake_success_rate'])}",
        f"  CRM: {_kv(i['crm_actions'])}; closed without a lead (opt-outs): "
        f"{i['closed_without_lead']}",
        f"  CRM sync success (lead in Odoo / lead in Odoo + failed): "
        f"{_pct(report['crm_sync']['success_rate'])}", "",
        "QUALIFICATION",
        f"  Priority: {_kv(q['priority_distribution'])}",
        f"  Qualified (high + standard / scored): {_pct(q['qualified_rate'])}",
        f"  AI outcomes: {_kv(q['ai_outcomes'])}", "",
        "RESPONSE AND FOLLOW-UP",
        f"  First customer response: median {fr['median']} min, average {fr['average']} min "
        f"over {fr['count']} lead(s)",
        f"  Property matches: {_kv(report['matching']['outcomes'])}; matched "
        f"{_pct(report['matching']['matched_rate'])}",
        f"  Reminder sequences started: {_kv(f['sequences_started_by_outcome'])}; reminders "
        f"sent {f['reminders_sent']}; customer replies {f['customer_replies']}",
        "  Overdue PropFlow activities in Odoo now: " + (
            str(f["overdue_propflow_activities"])
            if f["overdue_propflow_activities"] is not None else "unavailable"),
        "",
        "HANDOFFS TO SALESPEOPLE",
        f"  Created: {h['created']} (still open {h['still_open']}); overdue open now: "
        f"{h['overdue_open_now']}",
        f"  Reasons: {_kv(h['by_reason'])}",
        f"  Rep reminders: {h['reminded']}; escalated to manager: {h['escalated_to_manager']}",
        "",
        "WORKLOAD (assigned in window / open PropFlow leads)",
        *workload_lines,
        "",
        "FAILURES AND RECOVERY",
        f"  Dead letters in window: {_kv(report['failures']['dead_letters_by_status'])}; open "
        f"now: {report['failures']['open_dead_letters_now']}",
        "", f"Odoo: {report['odoo']}",
        "All figures are counts of PropFlow ledger records unless stated; rates show their "
        "numerator and denominator.", "-- PropFlow",
    ]
    return "\n".join(lines)
