"""Staff dashboard API: what needs attention, report figures, recovery actions.

Authenticated with a bearer token (STAFF_TOKEN). This is development-grade access control for
an internal tool on localhost; production should put the dashboard behind SSO.
"""

import hmac
from datetime import UTC, datetime
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, status
from psycopg.rows import dict_row

from app.business_time import BusinessCalendar
from app.config import Settings, get_settings
from app.crm import lead_url
from app.deps import get_db
from app.messages import REASON_LABELS
from app.reports import PERIODS, build_report
from app.routers.automation import _optional_odoo, get_calendar
from app.routers.inbound import discard_dead_letter, replay_dead_letter
from app.schemas import DiscardRequest


def require_staff(authorization: str | None = Header(default=None),
                  settings: Settings = Depends(get_settings)) -> None:
    expected = settings.staff_token
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "staff access not configured")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in with a valid staff token")


router = APIRouter(prefix="/staff", dependencies=[Depends(require_staff)])


@router.get("/session")
def session() -> dict:
    return {"ok": True}


@router.get("/overview")
def overview(period: str = "day", conn: psycopg.Connection = Depends(get_db),
             odoo=Depends(_optional_odoo),
             cal: BusinessCalendar = Depends(get_calendar)) -> dict:
    if period not in PERIODS:
        raise HTTPException(422, "period must be day or week")
    end = datetime.now(UTC)
    return build_report(conn, odoo, cal, start=end - PERIODS[period], end=end)


@router.get("/handoffs")
def handoffs(conn: psycopg.Connection = Depends(get_db),
             settings: Settings = Depends(get_settings),
             cal: BusinessCalendar = Depends(get_calendar)) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT x.id, x.odoo_lead_id, x.reason, x.priority, x.assigned_to, x.due_at,"
            " x.created_at, x.reminded_at, x.manager_notified_at, e.raw_payload->>'name' AS name"
            " FROM escalations x LEFT JOIN intake_events e ON e.id = x.event_id"
            " WHERE x.status = 'open' ORDER BY x.due_at LIMIT 100").fetchall()
    now = datetime.now(UTC)
    return [{
        "id": str(r["id"]), "lead_id": r["odoo_lead_id"], "customer": r["name"],
        "reasons": [REASON_LABELS.get(x, x.replace("_", " "))
                    for x in (r["reason"] or "").split(",") if x],
        "priority": r["priority"], "owner": r["assigned_to"],
        "due_at": r["due_at"].isoformat(), "due_text": cal.describe(r["due_at"]),
        "overdue": r["due_at"] < now, "reminded": r["reminded_at"] is not None,
        "escalated": r["manager_notified_at"] is not None,
        "lead_url": lead_url(settings.odoo_public_url, r["odoo_lead_id"])
        if r["odoo_lead_id"] else None,
    } for r in rows]


@router.get("/leads")
def recent_leads(limit: int = 25, conn: psycopg.Connection = Depends(get_db),
                 settings: Settings = Depends(get_settings)) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """
            SELECT e.received_at, e.source, e.kind, e.status, e.crm_action, e.odoo_lead_id,
                   coalesce(e.raw_payload->>'name', e.raw_payload->>'from') AS name, e.error,
                   (SELECT s.priority FROM score_results s WHERE s.event_id = e.id
                     ORDER BY s.created_at DESC LIMIT 1) AS priority,
                   (SELECT s.total FROM score_results s WHERE s.event_id = e.id
                     ORDER BY s.created_at DESC LIMIT 1) AS score,
                   EXISTS (SELECT 1 FROM escalations x WHERE x.event_id = e.id) AS handed_off
              FROM intake_events e ORDER BY e.received_at DESC LIMIT %s
            """, (max(1, min(limit, 100)),)).fetchall()
    return [{**r, "received_at": r["received_at"].isoformat(),
             "lead_url": lead_url(settings.odoo_public_url, r["odoo_lead_id"])
             if r["odoo_lead_id"] else None} for r in rows]


@router.get("/dead-letters")
def dead_letters(conn: psycopg.Connection = Depends(get_db)) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT id, workflow, error, correlation_id, attempts, created_at,"
            " payload->>'last_node' AS last_node FROM dead_letters WHERE status = 'open'"
            " ORDER BY created_at DESC LIMIT 100").fetchall()
    return [{**r, "id": str(r["id"]), "correlation_id": str(r["correlation_id"])
             if r["correlation_id"] else None, "created_at": r["created_at"].isoformat(),
             "replayable": r["correlation_id"] is not None} for r in rows]


@router.post("/dead-letters/{dead_letter_id}/replay")
def staff_replay(dead_letter_id: UUID, conn: psycopg.Connection = Depends(get_db),
                 settings: Settings = Depends(get_settings)):
    return replay_dead_letter(dead_letter_id, conn, settings)


@router.post("/dead-letters/{dead_letter_id}/discard")
def staff_discard(dead_letter_id: UUID, body: DiscardRequest,
                  conn: psycopg.Connection = Depends(get_db)):
    return discard_dead_letter(dead_letter_id, body, conn)
