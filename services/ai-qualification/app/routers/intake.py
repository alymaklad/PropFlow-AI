"""Event ledger: signed webhook receipt, idempotent claim, final status recording."""

import hashlib
import json
import logging
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb

from app.auth import require_api_key
from app.config import Settings, get_settings
from app.deps import get_db
from app.schemas import (
    ClaimOut,
    ClaimRequest,
    EventStatusRequest,
    ReceiveOut,
    ReceiveRequest,
)
from app.signing import SignatureError, verify

logger = logging.getLogger("propflow.intake")
router = APIRouter(prefix="/v1/intake", dependencies=[Depends(require_api_key)])

# Redeliveries of events in these states are acknowledged without processing again.
FINAL_STATES = {"completed", "rejected"}


def derive_idempotency_key(source: str, payload: dict | str) -> str:
    if isinstance(payload, dict):
        payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{source}:sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


def _claim(conn: psycopg.Connection, source: str, payload: dict, key: str,
           initial_status: str = "processing", error: str | None = None) -> ClaimOut:
    row = conn.execute(
        """
        INSERT INTO intake_events (idempotency_key, source, raw_payload, status, error)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (idempotency_key)
            DO UPDATE SET delivery_count = intake_events.delivery_count + 1
        RETURNING id, correlation_id, status, delivery_count, odoo_lead_id, (xmax = 0)
        """,
        (key, source, Jsonb(payload), initial_status, error),
    ).fetchone()
    event_id, correlation_id, state, deliveries, lead_id, inserted = row
    return ClaimOut(
        event_id=event_id, correlation_id=correlation_id, idempotency_key=key,
        duplicate=not inserted, proceed=state not in FINAL_STATES,
        status=state, delivery_count=deliveries, odoo_lead_id=lead_id,
    )


@router.post("/claim", response_model=ClaimOut)
def claim(body: ClaimRequest, conn: psycopg.Connection = Depends(get_db)) -> ClaimOut:
    """Record an already-trusted event once. A redelivery increments delivery_count and
    returns the original row; `proceed` tells the workflow whether to (re)process it."""
    key = body.idempotency_key or derive_idempotency_key(body.source, body.raw_payload)
    return _claim(conn, body.source, body.raw_payload, key)


@router.post("/receive", response_model=ReceiveOut,
             responses={401: {"description": "bad signature (not stored)"},
                        422: {"description": "signed but not a JSON object (stored as rejected)"}})
def receive(body: ReceiveRequest, conn: psycopg.Connection = Depends(get_db),
            settings: Settings = Depends(get_settings)):
    """Verify the webhook signature over the exact raw body, parse it, and claim the event.

    Unsigned or wrongly signed requests are refused and NOT stored, so anonymous traffic
    cannot fill the ledger. Signed but malformed bodies are stored as rejected."""
    if not settings.webhook_hmac_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook secret not configured")
    try:
        verify(settings.webhook_hmac_secret, body.timestamp, body.signature, body.raw_body,
               settings.webhook_max_skew_seconds)
    except SignatureError as exc:
        logger.warning("rejected webhook: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    try:
        payload = json.loads(body.raw_body)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        key = body.idempotency_key or derive_idempotency_key(body.source, body.raw_body)
        claimed = _claim(conn, body.source, {"_unparsed": body.raw_body[:5000]}, key,
                         initial_status="rejected", error="malformed_json")
        return JSONResponse(status_code=422, content={
            "detail": "body must be a JSON object", "event_id": str(claimed.event_id)})

    key = body.idempotency_key or derive_idempotency_key(body.source, payload)
    claimed = _claim(conn, body.source, payload, key)
    return ReceiveOut(**claimed.model_dump(), payload=payload)


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
