"""Deterministic CRM operations (Odoo). Called by n8n with validated data only."""

import logging
from dataclasses import asdict
from datetime import date

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Jsonb

from app.auth import require_api_key
from app.config import Settings, get_settings
from app.crm import schedule_followup, upsert_lead
from app.deps import get_db, get_odoo
from app.odoo_client import OdooClient, OdooPermanentError, OdooTransientError
from app.schemas import FollowupOut, FollowupRequest, OwnerOut, UpsertOut, UpsertRequest

logger = logging.getLogger("propflow.crm")
router = APIRouter(prefix="/v1/crm", dependencies=[Depends(require_api_key)])


def lead_url(settings: Settings, lead_id: int) -> str:
    return f"{settings.odoo_public_url.rstrip('/')}/web#id={lead_id}&model=crm.lead&view_type=form"


def fetch_owner(odoo: OdooClient, user_id: int | None) -> OwnerOut | None:
    if not user_id:
        return None
    users = odoo.search_read("res.users", [("id", "=", user_id)], ["name", "email"])
    if not users:
        return None
    return OwnerOut(id=user_id, name=users[0]["name"], email=users[0]["email"] or None)


def _odoo_failure(exc: Exception) -> HTTPException:
    """503 = transient, safe to retry later; 502 = Odoo rejected the request."""
    if isinstance(exc, OdooTransientError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Odoo unavailable: {exc}",
                             headers={"Retry-After": "30"})
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"Odoo rejected the request: {exc}")


@router.post("/leads/upsert", response_model=UpsertOut)
def upsert(body: UpsertRequest, conn: psycopg.Connection = Depends(get_db),
           odoo: OdooClient = Depends(get_odoo),
           settings: Settings = Depends(get_settings)) -> UpsertOut:
    if not body.lead.valid or not body.lead.contact_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "lead is not valid")
    score = body.score.model_dump()
    try:
        result = upsert_lead(
            odoo, conn, correlation_id=body.correlation_id, lead=body.lead.model_dump(),
            score=score, exception_status=body.exception_status,
            configured_team_id=settings.odoo_sales_team_id,
        )
        owner = fetch_owner(odoo, result.user_id)
    except (OdooTransientError, OdooPermanentError) as exc:
        logger.warning("upsert failed for %s: %s", body.correlation_id, exc)
        raise _odoo_failure(exc) from exc

    if body.event_id:
        with conn.transaction():
            conn.execute("UPDATE intake_events SET odoo_lead_id = %s WHERE id = %s",
                         (result.lead_id, body.event_id))
            conn.execute(
                """
                INSERT INTO score_results (event_id, rules_version, total, components, priority)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (event_id, rules_version) DO UPDATE
                   SET total = EXCLUDED.total, components = EXCLUDED.components,
                       priority = EXCLUDED.priority
                """,
                (body.event_id, score["rules_version"], score["total"],
                 Jsonb(score["components"]), score["priority"]),
            )
    return UpsertOut(**asdict(result), owner=owner, lead_url=lead_url(settings, result.lead_id))


@router.post("/leads/{lead_id}/followup", response_model=FollowupOut)
def followup(lead_id: int, body: FollowupRequest,
             odoo: OdooClient = Depends(get_odoo)) -> FollowupOut:
    if body.user_id is None:
        return FollowupOut(scheduled=False, activity_id=None, deadline=None,
                           warnings=["no_owner"])
    try:
        activity_id, deadline = schedule_followup(
            odoo, lead_id=lead_id, user_id=body.user_id, priority=body.priority,
            today=body.today or date.today(),
        )
    except (OdooTransientError, OdooPermanentError) as exc:
        raise _odoo_failure(exc) from exc
    return FollowupOut(scheduled=True, activity_id=activity_id, deadline=deadline, warnings=[])
