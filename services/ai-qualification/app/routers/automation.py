"""Next-action routing, handoffs and follow-up sequences. Called by n8n (intake and scheduler
workflows); each response lists the messages to send, already claimed in the outbound ledger."""

from datetime import UTC, datetime
from functools import cache

import psycopg
from fastapi import APIRouter, Depends

from app.auth import require_api_key
from app.automation import (
    check_handoffs,
    create_handoff,
    decide_route,
    due_followups,
    handoff_messages,
    start_sequence,
)
from app.business_time import BusinessCalendar
from app.config import Settings, get_settings
from app.deps import get_db, get_odoo
from app.odoo_client import OdooClient
from app.schemas import (
    ClockRequest,
    FollowupDueOut,
    FollowupStartRequest,
    HandoffCheckOut,
    HandoffOut,
    HandoffRequest,
    RouteOut,
    RouteRequest,
)

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@cache
def get_calendar() -> BusinessCalendar:
    return BusinessCalendar.from_env()


def _now(value: datetime | None) -> datetime:
    return value or datetime.now(UTC)


@router.post("/route", response_model=RouteOut)
def route(body: RouteRequest) -> RouteOut:
    lead = body.lead.model_dump()
    chosen, reasons = decide_route(body.qualification, lead, body.match_status,
                                   has_email=bool(lead.get("email")))
    return RouteOut(route=chosen, reasons=reasons)


@router.post("/handoffs", response_model=HandoffOut)
def handoff(body: HandoffRequest, conn: psycopg.Connection = Depends(get_db),
            odoo: OdooClient = Depends(get_odoo), settings: Settings = Depends(get_settings),
            cal: BusinessCalendar = Depends(get_calendar)) -> HandoffOut:
    lead = body.lead.model_dump()
    result = create_handoff(
        conn, odoo, cal, event_id=body.event_id, correlation_id=body.correlation_id,
        lead_id=body.lead_id, user_id=body.user_id, team_id=body.team_id,
        priority=body.priority, reasons=body.reasons, lead=lead, matches=body.matches,
        public_url=settings.odoo_public_url, now=_now(body.now))
    messages = handoff_messages(conn, result, lead_id=body.lead_id, reasons=body.reasons,
                                lead=lead)
    return HandoffOut(escalation_id=result.escalation_id, created=result.created,
                      due_at=result.due_at, contact_by=result.contact_by, owner=result.owner,
                      lead_url=result.lead_url, messages=messages)


@router.post("/handoffs/check", response_model=HandoffCheckOut)
def handoffs_check(body: ClockRequest, conn: psycopg.Connection = Depends(get_db),
                   odoo: OdooClient = Depends(get_odoo),
                   settings: Settings = Depends(get_settings),
                   cal: BusinessCalendar = Depends(get_calendar)) -> HandoffCheckOut:
    return HandoffCheckOut(**check_handoffs(conn, odoo, cal, public_url=settings.odoo_public_url,
                                            now=_now(body.now)))


@router.post("/followups/start")
def followups_start(body: FollowupStartRequest, conn: psycopg.Connection = Depends(get_db),
                    cal: BusinessCalendar = Depends(get_calendar)) -> dict:
    lead = body.lead.model_dump()
    if not lead.get("email"):
        return {"created": False, "reason": "no_email"}
    requirements = {k: lead.get(k) for k in ("property_type", "location", "bedrooms",
                                             "budget_min", "budget_max", "currency")}
    return start_sequence(conn, cal, lead_id=body.lead_id, correlation_id=body.correlation_id,
                          to_email=lead["email"], contact_keys=[lead.get("phone") or ""],
                          name=lead.get("name"), requirements=requirements, now=_now(body.now))


@router.post("/followups/due", response_model=FollowupDueOut)
def followups_due(body: ClockRequest, conn: psycopg.Connection = Depends(get_db),
                  odoo: OdooClient = Depends(get_odoo),
                  cal: BusinessCalendar = Depends(get_calendar)) -> FollowupDueOut:
    return FollowupDueOut(**due_followups(conn, odoo, cal, now=_now(body.now)))
