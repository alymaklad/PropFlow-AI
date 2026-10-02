"""Request/response models for the /v1 API."""

from datetime import date, datetime
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



# --- property matching --------------------------------------------------------------------------

class MatchRequest(BaseModel):
    correlation_id: UUID
    event_id: UUID | None = None
    lead: NormalizedLeadOut


class ListingOut(BaseModel):
    listing_id: str
    property_type: str
    location: str
    price: float
    currency: str
    bedrooms: int | None
    bathrooms: int | None
    delivery_status: str
    amenities: list[str]
    description: str | None
    verified_days_ago: int


class MatchOut(BaseModel):
    status: Literal["matched", "none", "insufficient_criteria", "conflict"]
    matches: list[ListingOut]
    missing: list[str]
    criteria: dict



# --- customer messages and consent --------------------------------------------------------------

class PrepareRequest(BaseModel):
    lead_ref: str = Field(min_length=1, max_length=200)
    to_email: str | None = Field(default=None, max_length=320)
    contact_keys: list[str] = Field(default_factory=list, max_length=5)
    template: str = Field(min_length=1, max_length=100)
    sequence_no: int = Field(default=1, ge=1)
    data: dict = Field(default_factory=dict)


class PrepareOut(BaseModel):
    send: bool
    message_id: UUID | None = None
    reason: str | None = None  # why not: no_email, opted_out, already_sent, pending, ...
    to: str | None = None
    subject: str | None = None
    text: str | None = None
    template_version: str | None = None


class ConsentRequest(BaseModel):
    contact_keys: list[str] = Field(min_length=1, max_length=5)
    channel: Literal["email", "whatsapp"] = "email"
    status: Literal["opted_in", "opted_out"]
    source: str = Field(min_length=1, max_length=100)



# --- routing, handoff, follow-ups ----------------------------------------------------------------

class RouteRequest(BaseModel):
    qualification: dict | None = None  # a /v1/qualify response (opt_out, reasons)
    lead: NormalizedLeadOut
    match_status: Literal["matched", "none", "insufficient_criteria", "conflict"] | None = None


class RouteOut(BaseModel):
    route: Literal["opt_out", "handoff", "shortlist", "clarify", "rep_only"]
    reasons: list[str]


class MessageOut(PrepareOut):
    kind: Literal["rep", "customer", "manager"]
    lead_id: int | None = None  # set on no_manager entries so ops can be alerted
    lead_url: str | None = None


class HandoffRequest(BaseModel):
    event_id: UUID
    correlation_id: UUID
    lead_id: int
    user_id: int | None = None
    team_id: int | None = None
    priority: Literal["high", "standard", "nurture"]
    reasons: list[str] = Field(min_length=1)
    lead: NormalizedLeadOut
    matches: list[dict] = Field(default_factory=list)
    now: datetime | None = None  # tests and manual replays; defaults to the current time


class HandoffOut(BaseModel):
    escalation_id: UUID
    created: bool
    due_at: datetime
    contact_by: str
    owner: dict | None
    lead_url: str
    messages: list[MessageOut]


class ClockRequest(BaseModel):
    now: datetime | None = None


class HandoffCheckOut(BaseModel):
    resolved: list[str]
    messages: list[MessageOut]


class FollowupStartRequest(BaseModel):
    lead_id: int
    correlation_id: UUID
    lead: NormalizedLeadOut
    now: datetime | None = None


class FollowupDueOut(BaseModel):
    messages: list[MessageOut]
    stopped: list[dict]



class NextActionRequest(BaseModel):
    event_id: UUID
    correlation_id: UUID
    lead: NormalizedLeadOut          # the merged lead from /v1/qualify (or /v1/normalize)
    qualification: dict | None = None
    score: ScoreOut
    upsert: UpsertOut
    match: MatchOut
    now: datetime | None = None


class NextActionOut(BaseModel):
    route: Literal["opt_out", "handoff", "shortlist", "clarify", "rep_only"]
    reasons: list[str]
    messages: list[MessageOut]
    due_at: datetime | None



# --- inbound email and recovery -------------------------------------------------------------------

class EmailIn(BaseModel):
    """A received email, as parsed by n8n's IMAP trigger."""

    message_id: str | None = Field(default=None, max_length=500)
    in_reply_to: str | None = Field(default=None, max_length=500)
    references: list[str] = Field(default_factory=list, max_length=50)
    from_email: str = Field(min_length=3, max_length=320)
    from_name: str | None = Field(default=None, max_length=200)
    subject: str | None = Field(default=None, max_length=1000)
    text: str | None = Field(default=None, max_length=50_000)
    now: datetime | None = None


class EmailOut(BaseModel):
    kind: Literal["inquiry", "reply", "duplicate", "ignored"]
    forwarded_status: int | None = None
    action: str | None = None
    lead_id: int | None = None
    score: dict | None = None
    messages: list[MessageOut] = Field(default_factory=list)


class DeadLetterItem(BaseModel):
    id: UUID
    workflow: str
    error: str
    correlation_id: UUID | None
    status: str
    attempts: int
    created_at: datetime


class ReplayOut(BaseModel):
    id: UUID
    status: str
    resolution: str
    intake_status: int | None = None


class DiscardRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
