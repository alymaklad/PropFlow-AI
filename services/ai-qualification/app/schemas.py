"""Request/response models for the /v1 API."""

from typing import Literal

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
