"""Event ledger: idempotent claim of inbound events and final status recording."""

import hashlib
import json
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.types.json import Jsonb

from app.auth import require_api_key
from app.deps import get_db
from app.schemas import ClaimOut, ClaimRequest, EventStatusRequest

router = APIRouter(prefix="/v1/intake", dependencies=[Depends(require_api_key)])

# Redeliveries of events in these states are acknowledged without processing again.
FINAL_STATES = {"completed", "rejected"}


def derive_idempotency_key(source: str, payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{source}:sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


@router.post("/claim", response_model=ClaimOut)
def claim(body: ClaimRequest, conn: psycopg.Connection = Depends(get_db)) -> ClaimOut:
    """Record the event once. A redelivery increments delivery_count and returns the original
    row; `proceed` tells the workflow whether to (re)process it."""
    key = body.idempotency_key or derive_idempotency_key(body.source, body.raw_payload)
    row = conn.execute(
        """
        INSERT INTO intake_events (idempotency_key, source, raw_payload, status)
        VALUES (%s, %s, %s, 'processing')
        ON CONFLICT (idempotency_key)
            DO UPDATE SET delivery_count = intake_events.delivery_count + 1
        RETURNING id, correlation_id, status, delivery_count, odoo_lead_id, (xmax = 0)
        """,
        (key, body.source, Jsonb(body.raw_payload)),
    ).fetchone()
    event_id, correlation_id, state, deliveries, lead_id, inserted = row
    return ClaimOut(
        event_id=event_id, correlation_id=correlation_id, idempotency_key=key,
        duplicate=not inserted, proceed=inserted or state not in FINAL_STATES,
        status=state, delivery_count=deliveries, odoo_lead_id=lead_id,
    )


@router.post("/{event_id}/status")
def set_status(event_id: UUID, body: EventStatusRequest,
               conn: psycopg.Connection = Depends(get_db)) -> dict[str, str]:
    updated = conn.execute(
        """
        UPDATE intake_events
           SET status = %s, error = %s, odoo_lead_id = COALESCE(%s, odoo_lead_id)
         WHERE id = %s
        RETURNING id
        """,
        (body.status, body.error, body.odoo_lead_id, event_id),
    ).fetchone()
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown event")
    return {"status": body.status}
