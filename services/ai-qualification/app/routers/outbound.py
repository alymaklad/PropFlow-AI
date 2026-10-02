"""Outbound message ledger ("record before send") and the dead-letter queue."""

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Jsonb

from app.auth import require_api_key
from app.deps import get_db
from app.messages import TEMPLATE_VERSION, TemplateError, render
from app.schemas import (
    ConsentRequest,
    DeadLetterOut,
    DeadLetterRequest,
    OutboundClaimOut,
    OutboundClaimRequest,
    OutboundStatusRequest,
    PrepareOut,
    PrepareRequest,
)

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


def claim_message(conn: psycopg.Connection, lead_ref: str, channel: str, template: str,
                  sequence_no: int) -> OutboundClaimOut:
    """Reserve a message before sending it. `send` is true only for a new message or one whose
    previous attempt failed. A message left `pending` by a crash mid-send is NOT resent
    automatically (it may have gone out): at most once, and it stays visible as pending."""
    key = (lead_ref, template, sequence_no)
    where = "lead_ref = %s AND template = %s AND sequence_no = %s"
    with conn.transaction():
        row = conn.execute(f"SELECT id, status FROM outbound_messages WHERE {where} FOR UPDATE",
                           key).fetchone()
        if row is None:
            inserted = conn.execute(
                "INSERT INTO outbound_messages (lead_ref, channel, template, sequence_no)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id",
                (lead_ref, channel, template, sequence_no),
            ).fetchone()
            if inserted:
                return OutboundClaimOut(message_id=inserted[0], send=True, status="pending")
            # A concurrent request inserted it first: it owns the send.
            row = conn.execute(f"SELECT id, status FROM outbound_messages WHERE {where}",
                               key).fetchone()
            return OutboundClaimOut(message_id=row[0], send=False, status=row[1])
        message_id, state = row
        if state == "failed":
            conn.execute("UPDATE outbound_messages SET status = 'pending', error = NULL"
                         " WHERE id = %s", (message_id,))
            return OutboundClaimOut(message_id=message_id, send=True, status="pending")
        return OutboundClaimOut(message_id=message_id, send=False, status=state)


def opted_out(conn: psycopg.Connection, contact_keys: list[str], channel: str) -> bool:
    keys = [k.strip().lower() for k in contact_keys if k]
    if not keys:
        return False
    row = conn.execute(
        "SELECT 1 FROM consents WHERE contact_key = ANY(%s) AND channel = %s"
        " AND status = 'opted_out' LIMIT 1", (keys, channel)).fetchone()
    return row is not None


@router.post("/outbound/claim", response_model=OutboundClaimOut)
def claim_outbound(body: OutboundClaimRequest,
                   conn: psycopg.Connection = Depends(get_db)) -> OutboundClaimOut:
    """Claim an internal notification (rep or ops email). Customer messages use
    /v1/messages/prepare, which also checks consent."""
    return claim_message(conn, body.lead_ref, body.channel, body.template, body.sequence_no)


@router.post("/messages/prepare", response_model=PrepareOut)
def prepare_message(body: PrepareRequest,
                    conn: psycopg.Connection = Depends(get_db)) -> PrepareOut:
    """The single path for customer messages: consent check, at-most-once claim, render.
    Send only when `send` is true, then report the outcome on /v1/outbound/{id}/status."""
    if not body.to_email:
        return PrepareOut(send=False, reason="no_email")
    if opted_out(conn, [body.to_email, *body.contact_keys], "email"):
        return PrepareOut(send=False, reason="opted_out")
    try:
        subject, text = render(body.template, body.data)
    except TemplateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    claim = claim_message(conn, body.lead_ref, "email", body.template, body.sequence_no)
    if not claim.send:
        return PrepareOut(send=False, message_id=claim.message_id,
                          reason="already_sent" if claim.status == "sent" else claim.status)
    return PrepareOut(send=True, message_id=claim.message_id, to=body.to_email,
                      subject=subject, text=text, template_version=TEMPLATE_VERSION)


@router.post("/consents", status_code=204)
def record_consent(body: ConsentRequest, conn: psycopg.Connection = Depends(get_db)) -> None:
    """Record opt-in/opt-out for every key of a contact (email address and phone)."""
    with conn.transaction():
        for key in {k.strip().lower() for k in body.contact_keys if k}:
            conn.execute(
                """
                INSERT INTO consents (contact_key, channel, status, source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (contact_key, channel) DO UPDATE
                   SET status = EXCLUDED.status, source = EXCLUDED.source, updated_at = now()
                """,
                (key, body.channel, body.status, body.source),
            )


@router.post("/outbound/{message_id}/status")
def set_outbound_status(message_id: UUID, body: OutboundStatusRequest,
                        conn: psycopg.Connection = Depends(get_db)) -> dict[str, str]:
    updated = conn.execute(
        "UPDATE outbound_messages SET status = %s, provider_msg_id = %s, error = %s"
        " WHERE id = %s RETURNING id",
        (body.status, body.provider_msg_id, body.error, message_id),
    ).fetchone()
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown message")
    return {"status": body.status}


@router.post("/dead-letters", response_model=DeadLetterOut, status_code=201)
def add_dead_letter(body: DeadLetterRequest,
                    conn: psycopg.Connection = Depends(get_db)) -> DeadLetterOut:
    (dead_letter_id,) = conn.execute(
        "INSERT INTO dead_letters (workflow, correlation_id, payload, error)"
        " VALUES (%s, %s, %s, %s) RETURNING id",
        (body.workflow, body.correlation_id, Jsonb(body.payload), body.error),
    ).fetchone()
    return DeadLetterOut(id=dead_letter_id)
