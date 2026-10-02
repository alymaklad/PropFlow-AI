"""Public API for the buyer site (no API key). Reads verified listings and accepts inquiries.

Inquiries are validated here, rate-limited per client, guarded by a honeypot field, made
idempotent with a client-generated submission id, then signed server-side and forwarded to
the same n8n intake webhook as every other channel. The browser never sees the webhook secret.
"""

import threading
import time
from collections import defaultdict, deque
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.deps import get_db
from app.forwarding import ForwardError, forward_to_intake
from app.matching import FRESHNESS_DAYS
from app.normalize import normalize_lead

router = APIRouter(prefix="/public")

RATE_LIMIT, RATE_WINDOW = 5, 600  # inquiries per client per 10 minutes
_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()

ERROR_TEXT = {
    "contact_missing": ("email", "Add an email address or a phone number so an advisor can "
                                 "reply."),
    "content_missing": ("message", "Tell us what you are looking for: a property type, an "
                                   "area or a few words in the message."),
}


def client_key(request: Request) -> str:
    # nginx sets X-Real-IP; the service is not exposed publicly without it.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


def rate_limited(key: str, now: float | None = None) -> bool:
    now = now or time.monotonic()
    with _lock:
        hits = _hits[key]
        while hits and now - hits[0] > RATE_WINDOW:
            hits.popleft()
        if len(hits) >= RATE_LIMIT:
            return True
        hits.append(now)
        return False


class PublicInquiry(BaseModel):
    submission_id: UUID
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    property_type: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=80)
    bedrooms: int | None = Field(default=None, ge=0, le=20)
    budget_max: int | None = Field(default=None, ge=0, le=10_000_000_000)
    timeline: str | None = Field(default=None, max_length=40)
    purchase_stage: str | None = Field(default=None, max_length=40)
    message: str | None = Field(default=None, max_length=3000)
    website: str | None = Field(default=None, max_length=200)  # honeypot: humans leave it empty


@router.get("/listings")
def listings(location: str | None = None, property_type: str | None = None,
             bedrooms: int | None = None, budget_max: int | None = None,
             conn: psycopg.Connection = Depends(get_db)) -> dict:
    """Available listings verified within the freshness window, cheapest first."""
    conditions = ["availability = 'available'",
                  "last_verified_at >= now() - make_interval(days => %(fresh)s)"]
    params: dict = {"fresh": FRESHNESS_DAYS}
    for key, value, clause in (("location", location, "location = %(location)s"),
                               ("ptype", property_type, "property_type = %(ptype)s"),
                               ("bedrooms", bedrooms, "bedrooms = %(bedrooms)s"),
                               ("budget", budget_max, "price <= %(budget)s")):
        if value is not None and value != "":
            conditions.append(clause)
            params[key] = value
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT listing_id, property_type, location, price::float AS price, currency,"
            " bedrooms, bathrooms, delivery_status, amenities, description,"
            " EXTRACT(day FROM now() - last_verified_at)::int AS verified_days_ago"
            " FROM properties WHERE " + " AND ".join(conditions)
            + " ORDER BY currency, price LIMIT 60", params).fetchall()
        options = cur.execute(
            "SELECT array_agg(DISTINCT location ORDER BY location) AS locations,"
            " array_agg(DISTINCT property_type ORDER BY property_type) AS property_types"
            " FROM properties WHERE availability = 'available'"
            " AND last_verified_at >= now() - make_interval(days => %(fresh)s)",
            {"fresh": FRESHNESS_DAYS}).fetchone()
    return {"listings": rows, "freshness_days": FRESHNESS_DAYS,
            "locations": options["locations"] or [],
            "property_types": options["property_types"] or []}


@router.post("/inquiries", status_code=202)
def submit_inquiry(body: PublicInquiry, request: Request,
                   settings: Settings = Depends(get_settings)):
    reference = str(body.submission_id)[:8].upper()
    if body.website:  # a bot filled the hidden field: accept silently, do nothing
        return {"status": "accepted", "reference": reference}
    if rate_limited(client_key(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Too many inquiries from this connection. Try again in a few "
                            "minutes.")
    payload = {k: v for k, v in body.model_dump(exclude={"submission_id", "website"}).items()
               if v not in (None, "")}
    payload["source"] = "form"
    lead = normalize_lead(payload)
    if not lead.valid:
        return JSONResponse(status_code=422, content={"errors": [
            {"field": ERROR_TEXT[e][0], "message": ERROR_TEXT[e][1]} for e in lead.errors]})
    if body.email and "email_invalid" in lead.warnings:
        return JSONResponse(status_code=422, content={"errors": [
            {"field": "email", "message": "Check the email address: it looks incomplete."}]})
    if body.phone and "phone_invalid" in lead.warnings:
        return JSONResponse(status_code=422, content={"errors": [
            {"field": "phone", "message": "Check the phone number, including the country "
                                          "code if it is not Egyptian."}]})
    try:
        code, _ = forward_to_intake(settings, payload, source="form",
                                    idempotency_key=f"web:{body.submission_id}")
    except ForwardError:
        code = 503
    if code >= 500 or code == 401:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "We couldn't send your inquiry right now. Try again in a minute.")
    return {"status": "accepted", "reference": reference}
