"""Outbound message ledger ("record before send") and the dead-letter queue."""

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Jsonb

from app.auth import require_api_key
from app.deps import get_db
from app.schemas import (
    DeadLetterOut,
    DeadLetterRequest,
    OutboundClaimOut,
    OutboundClaimRequest,
    OutboundStatusRequest,
)

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@router.post("/outbound/claim", response_model=OutboundClaimOut)
def claim_outbound(body: OutboundClaimRequest,
                   conn: psycopg.Connection = Depends(get_db)) -> OutboundClaimOut:
    """Reserve a message before sending it. `send` is true only for a new message or one whose
    previous attempt failed. A message left `pending` by a crash mid-send is NOT resent
    automatically (it may have gone out): at most once, and it stays visible as pending."""
    key = (body.lead_ref, body.template, body.sequence_no)
    where = "lead_ref = %s AND template = %s AND sequence_no = %s"
    with conn.transaction():
        row = conn.execute(f"SELECT id, status FROM outbound_messages WHERE {where} FOR UPDATE",
                           key).fetchone()
        if row is None:
            inserted = conn.execute(
                "INSERT INTO outbound_messages (lead_ref, channel, template, sequence_no)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id",
                (body.lead_ref, body.channel, body.template, body.sequence_no),
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
