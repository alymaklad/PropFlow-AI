"""Inbound email (replies and new inquiries) and dead-letter recovery."""

import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_api_key
from app.business_time import BusinessCalendar
from app.config import Settings, get_settings
from app.deps import get_db, get_odoo
from app.email_intake import find_reply_lead, handle_reply, strip_quoted
from app.forwarding import ForwardError, forward_to_intake
from app.normalize import normalize_email
from app.odoo_client import OdooClient
from app.routers.automation import get_calendar
from app.routers.intake import _claim
from app.schemas import DeadLetterItem, DiscardRequest, EmailIn, EmailOut, ReplayOut

logger = logging.getLogger("propflow.inbound")
router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


def _message_key(body: EmailIn) -> str:
    if body.message_id:
        return f"email:{body.message_id.strip()}"
    digest = hashlib.sha256(f"{body.from_email}|{body.subject}|{body.text}".encode()).hexdigest()
    return f"email:sha256:{digest}"


@router.post("/email/receive", response_model=EmailOut)
def receive_email(body: EmailIn, conn: psycopg.Connection = Depends(get_db),
                  odoo: OdooClient = Depends(get_odoo), settings: Settings = Depends(get_settings),
                  cal: BusinessCalendar = Depends(get_calendar)) -> EmailOut:
    sender = normalize_email(body.from_email)
    if not sender:
        return EmailOut(kind="ignored", action="invalid_sender")
    key = _message_key(body)
    lead_id = find_reply_lead(conn, [body.in_reply_to or "", *body.references], sender,
                              body.subject or "")

    if lead_id is None:
        # New inquiry: same pipeline as a web form (signed, idempotent on the Message-ID).
        text = strip_quoted(body.text or "") or (body.text or "")
        payload = {"source": "email", "name": body.from_name, "email": sender,
                   "message": "\n\n".join(p for p in (body.subject, text) if p)}
        try:
            code, _ = forward_to_intake(settings, payload, source="email", idempotency_key=key)
        except ForwardError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        if code >= 500:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"intake webhook returned {code}")
        return EmailOut(kind="inquiry", forwarded_status=code)

    claim = _claim(conn, "email", {"from": sender, "subject": body.subject,
                                   "text": (body.text or "")[:20_000], "reply_to_lead": lead_id},
                   key)
    if not claim.proceed:
        return EmailOut(kind="duplicate", lead_id=lead_id)
    conn.execute("UPDATE intake_events SET kind = 'reply', odoo_lead_id = %s WHERE id = %s",
                 (lead_id, claim.event_id))
    result = handle_reply(conn, odoo, cal, event_id=claim.event_id, lead_id=lead_id,
                          from_email=sender, text=body.text or "",
                          public_url=settings.odoo_public_url,
                          now=body.now or datetime.now(UTC))
    conn.execute("UPDATE intake_events SET status = 'completed' WHERE id = %s",
                 (claim.event_id,))
    return EmailOut(kind="reply", lead_id=lead_id, action=result["action"],
                    score=result.get("score"), messages=result["messages"])


@router.get("/dead-letters", response_model=list[DeadLetterItem])
def list_dead_letters(status_filter: str = "open",
                      conn: psycopg.Connection = Depends(get_db)) -> list[DeadLetterItem]:
    rows = conn.execute(
        "SELECT id, workflow, error, correlation_id, status, attempts, created_at"
        " FROM dead_letters WHERE status = %s ORDER BY created_at DESC LIMIT 200",
        (status_filter,)).fetchall()
    keys = ("id", "workflow", "error", "correlation_id", "status", "attempts", "created_at")
    return [DeadLetterItem(**dict(zip(keys, r, strict=True))) for r in rows]


@router.post("/dead-letters/{dead_letter_id}/replay", response_model=ReplayOut)
def replay_dead_letter(dead_letter_id: UUID, conn: psycopg.Connection = Depends(get_db),
                       settings: Settings = Depends(get_settings)) -> ReplayOut:
    """Re-drive the original event through the intake webhook (same idempotency key, so a
    partially processed event resumes instead of duplicating)."""
    row = conn.execute("SELECT correlation_id, status FROM dead_letters WHERE id = %s",
                       (dead_letter_id,)).fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown dead letter")
    correlation_id, state = row
    if state != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"dead letter is already {state}")
    if correlation_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "no event to replay (scheduled jobs rerun on their own); discard it")
    event = conn.execute(
        "SELECT idempotency_key, source, raw_payload, status FROM intake_events"
        " WHERE correlation_id = %s ORDER BY created_at LIMIT 1", (correlation_id,)).fetchone()
    if not event:
        raise HTTPException(status.HTTP_409_CONFLICT, "the original event is not in the ledger")
    key, source, payload, event_status = event

    def close(resolution: str, code: int | None = None) -> ReplayOut:
        conn.execute("UPDATE dead_letters SET status = 'replayed', replayed_at = now(),"
                     " attempts = attempts + 1, resolution = %s WHERE id = %s",
                     (resolution, dead_letter_id))
        return ReplayOut(id=dead_letter_id, status="replayed", resolution=resolution,
                         intake_status=code)

    if event_status == "completed":
        return close("event had already completed")
    if event_status == "rejected":
        raise HTTPException(status.HTTP_409_CONFLICT, "the event was rejected as invalid")
    try:
        code, _ = forward_to_intake(settings, payload, source=source, idempotency_key=key)
    except ForwardError as exc:
        conn.execute("UPDATE dead_letters SET attempts = attempts + 1 WHERE id = %s",
                     (dead_letter_id,))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    if code >= 400:
        conn.execute("UPDATE dead_letters SET attempts = attempts + 1 WHERE id = %s",
                     (dead_letter_id,))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"intake webhook returned {code}")
    return close("replayed to intake", code)


@router.post("/dead-letters/{dead_letter_id}/discard", response_model=ReplayOut)
def discard_dead_letter(dead_letter_id: UUID, body: DiscardRequest,
                        conn: psycopg.Connection = Depends(get_db)) -> ReplayOut:
    updated = conn.execute(
        "UPDATE dead_letters SET status = 'discarded', resolution = %s WHERE id = %s"
        " AND status = 'open' RETURNING id", (body.reason, dead_letter_id)).fetchone()
    if not updated:
        raise HTTPException(status.HTTP_409_CONFLICT, "unknown or not open")
    return ReplayOut(id=dead_letter_id, status="discarded", resolution=body.reason)
