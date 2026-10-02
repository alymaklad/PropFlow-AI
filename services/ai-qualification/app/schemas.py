"""Request/response models for the /v1 API."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Source = Literal["form", "email", "manual"]
Intent = Literal["high", "medium", "low", "unknown"]


class IntakePayload(BaseModel):
    """Raw intake as received by the webhook. Values are loose on purpose: web forms send
    strings, and normalization decides what is usable."""

    model_config = ConfigDict(extra="ignore")

    source: Source = "form"
    name: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=320)
    message: str | None = Field(default=None, max_length=20_000)
    property_type: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=500)
    bedrooms: int | str | None = None
    budget: str | int | float | None = None
    budget_min: str | int | float | None = None
    budget_max: str | int | float | None = None
    currency: str | None = Field(default=None, max_length=3)
    timeline: int | str | None = None
    purchase_stage: str | None = Field(default=None, max_length=50)
    delivery_preference: str | None = Field(default=None, max_length=50)


class NormalizedLeadOut(BaseModel):
    valid: bool
    source: Source
    name: str | None
    phone: str | None
    email: str | None
    contact_key: str | None
    message: str | None
    property_type: str | None
    location: str | None
    location_raw: str | None
    bedrooms: int | None
    budget_min: int | None
    budget_max: int | None
    currency: str | None
    purchase_timeline_months: int | None
    delivery_preference: Literal["ready", "under_construction", "off_plan", "any"] | None = None
    purchase_intent: Intent
    errors: list[str]
    warnings: list[str]
    conflicts: list[str]


class ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    purchase_timeline_months: int | None = Field(default=None, ge=0, le=240)
    property_type: str | None = None
    location: str | None = None
    bedrooms: int | None = Field(default=None, ge=0, le=20)
    purchase_intent: Intent = "unknown"
    responded_to_followup: bool = False


class ScoreComponentOut(BaseModel):
    rule: str
    points: int
    reason: str


class ScoreOut(BaseModel):
    total: int
    components: list[ScoreComponentOut]
    priority: Literal["high", "standard", "nurture"]
    rules_version: str


# --- intake ledger ------------------------------------------------------------------------------

class ClaimRequest(BaseModel):
    source: Source = "form"
    raw_payload: dict
    # Webhook event id if the sender provides one; otherwise derived from the payload.
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class ClaimOut(BaseModel):
    event_id: UUID
    correlation_id: UUID
    idempotency_key: str
    duplicate: bool
    proceed: bool  # false when an earlier delivery already completed or was rejected
    status: str
    delivery_count: int
    odoo_lead_id: int | None


class EventStatusRequest(BaseModel):
    status: Literal["completed", "rejected", "failed"]
    error: str | None = Field(default=None, max_length=2000)
    odoo_lead_id: int | None = None


# --- CRM ----------------------------------------------------------------------------------------

class UpsertRequest(BaseModel):
    correlation_id: UUID
    event_id: UUID | None = None
    lead: NormalizedLeadOut
    score: ScoreOut
    exception_status: Literal["none", "handoff", "sync_error"] = "none"


class OwnerOut(BaseModel):
    id: int
    name: str
    email: str | None


class UpsertOut(BaseModel):
    lead_id: int
    lead_url: str
    action: Literal["created", "updated", "matched_contact"]
    user_id: int | None
    team_id: int | None
    owner: OwnerOut | None
    warnings: list[str]


class FollowupRequest(BaseModel):
    user_id: int | None
    priority: Literal["high", "standard", "nurture"]
    today: date | None = None  # for tests; defaults to the service's current date


class FollowupOut(BaseModel):
    scheduled: bool
    activity_id: int | None
    deadline: date | None
    warnings: list[str]


class ReceiveRequest(BaseModel):
    """What n8n forwards from the webhook: the exact raw body plus the signature headers."""

    source: Source = "form"
    raw_body: str = Field(max_length=100_000)
    timestamp: str | None = None
    signature: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class ReceiveOut(ClaimOut):
    payload: dict


# --- outbound message ledger and dead letters ----------------------------------------------------

class OutboundClaimRequest(BaseModel):
    lead_ref: str = Field(min_length=1, max_length=200)
    channel: Literal["email", "whatsapp"] = "email"
    template: str = Field(min_length=1, max_length=100)
    sequence_no: int = Field(default=1, ge=1)


class OutboundClaimOut(BaseModel):
    message_id: UUID
    send: bool  # false: this message was already sent, or an attempt is in an unknown state
    status: str


class OutboundStatusRequest(BaseModel):
    status: Literal["sent", "failed", "cancelled"]
    provider_msg_id: str | None = Field(default=None, max_length=300)
    error: str | None = Field(default=None, max_length=2000)


class DeadLetterRequest(BaseModel):
    workflow: str = Field(min_length=1, max_length=200)
    error: str = Field(min_length=1, max_length=5000)
    correlation_id: UUID | None = None
    payload: dict = Field(default_factory=dict)


class DeadLetterOut(BaseModel):
    id: UUID



# --- AI qualification ---------------------------------------------------------------------------

class QualifyRequest(BaseModel):
    correlation_id: UUID
    event_id: UUID | None = None
    lead: NormalizedLeadOut


class QualifyOut(BaseModel):
    status: Literal["valid", "repaired", "invalid", "fallback", "skipped", "unsupported_language"]
    needs_human_review: bool
    reasons: list[str]
    opt_out: bool
    requests_human: bool
    confidence: float | None
    model: str | None
    prompt_version: str
    extraction: dict | None
    lead: NormalizedLeadOut  # form fields merged with the extraction (form values win)
