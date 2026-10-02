"""AI lead qualification as a LangGraph workflow (tasks 2.2-2.4).

    sanitize ──► extract ──► validate ──► resolve ──► gate ──► END
       │            ▲           │
       │            └─ repair ──┤ (one retry with the validation errors)
       │                        └──► fallback ──► END   (provider down / output still invalid)
       ├──► unsupported_language ──► END                (Arabic script: no model call)
       └──► skipped ──► END                             (no message text)

Controls:
- The inquiry is untrusted: it is delimited, never concatenated into instructions, and the
  model has no tools. Lookups (location canonicalisation) run as graph code, read-only.
- Model output is only data. It is schema-validated and post-checked here, and it can never
  trigger an action by itself: the caller (n8n) decides, using the deterministic score and
  the review flag computed below.
- Deterministic signals back the model up: injection phrases and opt-out keywords are
  detected without it, so an opt-out is honoured even if the model misses it.
- If the provider is unavailable or the output stays invalid, the result is a fallback that
  hands the lead to a salesperson; the intake continues with the form fields only.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.llm import LLMBadOutput, LLMClient, LLMUnavailable
from app.normalize import normalize_location

PROMPT_VERSION = "qualify-v1"
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text(
    encoding="utf-8")
SCHEMA_NAME = "lead_qualification"
MAX_ATTEMPTS = 2
MAX_TEXT_CHARS = 5000
SUPPORTED_LANGUAGES = {"en"}

PROPERTY_TYPES = ["apartment", "villa", "townhouse", "duplex", "penthouse", "studio", "chalet",
                  "land", "commercial", "office"]


def _nullable(schema: dict) -> dict:
    out = dict(schema)
    out["type"] = [schema["type"], "null"]
    if "enum" in schema:
        out["enum"] = [*schema["enum"], None]
    return out


# Strict mode: every property required, no additional properties, nullable via type unions.
QUALIFICATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "language": {"type": "string"},
        "inquiry_type": {"type": "string", "enum": ["purchase", "rental", "other", "none"]},
        "property_type": _nullable({"type": "string", "enum": PROPERTY_TYPES}),
        "location": _nullable({"type": "string"}),
        "bedrooms": _nullable({"type": "integer"}),
        "budget_min": _nullable({"type": "number"}),
        "budget_max": _nullable({"type": "number"}),
        "currency": _nullable({"type": "string", "enum": ["EGP", "USD", "EUR"]}),
        "delivery_preference": _nullable(
            {"type": "string", "enum": ["ready", "under_construction", "off_plan", "any"]}),
        "purchase_timeline_months": _nullable({"type": "integer"}),
        "purchase_intent": {"type": "string", "enum": ["high", "medium", "low", "unknown"]},
        "requests_human": {"type": "boolean"},
        "opt_out": {"type": "boolean"},
        "has_conflict": {"type": "boolean"},
        "conflict_note": _nullable({"type": "string"}),
        "injection_suspected": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
}
QUALIFICATION_SCHEMA["required"] = list(QUALIFICATION_SCHEMA["properties"])


class ModelExtraction(BaseModel):
    """What the model must return (mirrors QUALIFICATION_SCHEMA)."""

    model_config = ConfigDict(extra="forbid")

    language: str = Field(min_length=2, max_length=10)
    inquiry_type: Literal["purchase", "rental", "other", "none"]
    property_type: Literal[tuple(PROPERTY_TYPES)] | None  # type: ignore[valid-type]
    location: str | None = Field(max_length=200)
    bedrooms: int | None
    budget_min: float | None
    budget_max: float | None
    currency: Literal["EGP", "USD", "EUR"] | None
    delivery_preference: Literal["ready", "under_construction", "off_plan", "any"] | None
    purchase_timeline_months: int | None
    purchase_intent: Literal["high", "medium", "low", "unknown"]
    requests_human: bool
    opt_out: bool
    has_conflict: bool
    conflict_note: str | None = Field(max_length=500)
    injection_suspected: bool
    confidence: float = Field(ge=0, le=1)


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_INJECTION = [re.compile(p, re.I) for p in (
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"\bsystem\s*:", r"system prompt", r"\bapi[ _-]?keys?\b", r"</?\s*user_input\s*>",
    r"\b(admin|developer|god) mode\b", r"\byou are now\b", r"<<<\s*inquiry|inquiry\s*>>>",
)]
_OPT_OUT = [re.compile(p, re.I) for p in (
    r"^\W*(stop|unsubscribe)\W*$", r"\bunsubscribe\b", r"\bremove me from\b",
    r"\b(do not|don'?t) (contact|message|email|call) me\b",
    r"\bstop (sending|messaging|contacting|emailing)\b",
    r"وقف الرسائل", r"إلغاء الاشتراك", r"الغاء الاشتراك", r"لا تتصلوا",
)]


class QState(TypedDict, total=False):
    message: str
    text: str
    flags: list[str]
    attempts: int
    raw_output: str | None
    model: str | None
    unavailable: str | None
    validation_errors: list[str]
    extraction: dict | None
    status: str
    reasons: list[str]
    warnings: list[str]


@dataclass
class QualificationResult:
    status: Literal["valid", "repaired", "invalid", "fallback", "skipped",
                    "unsupported_language"]
    needs_human_review: bool
    reasons: list[str]
    opt_out: bool
    requests_human: bool
    extraction: dict | None
    confidence: float | None
    model: str | None
    prompt_version: str
    attempts: int
    raw_output: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def render_user_message(text: str, previous: str | None = None,
                        errors: list[str] | None = None) -> str:
    # Neutralise anything that looks like our delimiters inside the customer text.
    safe = re.sub(r"<<<|>>>", "»", text)
    parts = ["Extract the requirements from this inquiry.", "<<<INQUIRY", safe, "INQUIRY>>>"]
    if previous is not None:
        parts += ["", "Your previous answer was rejected for these reasons:",
                  *[f"- {e}" for e in (errors or [])],
                  "Return a corrected JSON object that follows the schema exactly."]
    return "\n".join(parts)


def post_check(ext: ModelExtraction) -> tuple[dict, list[str], list[str]]:
    """Deterministic checks and read-only lookups on a schema-valid extraction.
    Returns (extraction, conflicts, warnings)."""
    data = ext.model_dump()
    conflicts: list[str] = []
    warnings: list[str] = []

    raw_location = data.pop("location")
    data["location_raw"] = raw_location
    data["location"] = normalize_location(raw_location)
    if raw_location and not data["location"]:
        warnings.append("location_unrecognized")

    if data["bedrooms"] is not None and not 0 <= data["bedrooms"] <= 20:
        data["bedrooms"] = None
        warnings.append("bedrooms_invalid")
    if data["property_type"] == "studio":
        if data["bedrooms"] is None:
            data["bedrooms"] = 0
        elif data["bedrooms"] > 0:
            conflicts.append("studio_with_bedrooms")

    for key in ("budget_min", "budget_max"):
        if data[key] is not None:
            data[key] = int(round(data[key])) if data[key] > 0 else None
    if (data["budget_min"] is not None and data["budget_max"] is not None
            and data["budget_min"] > data["budget_max"]):
        conflicts.append("budget_min_gt_max")
        data["budget_min"] = data["budget_max"] = None
    if data["budget_min"] is None and data["budget_max"] is None:
        data["currency"] = None
    elif data["currency"] is None:
        data["currency"] = "EGP"

    months = data["purchase_timeline_months"]
    if months is not None and not 0 < months <= 240:
        data["purchase_timeline_months"] = None
        warnings.append("timeline_invalid")

    if data["has_conflict"] and not conflicts:
        conflicts.append("requirements_conflict")
    return data, conflicts, warnings


def build_graph(llm: LLMClient, min_confidence: float = 0.6):
    def sanitize(state: QState) -> QState:
        text = _CONTROL_CHARS.sub("", state.get("message") or "")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        flags: list[str] = []
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]
            flags.append("truncated")
        if _ARABIC.search(text):
            flags.append("arabic_script")
        if any(p.search(text) for p in _INJECTION):
            flags.append("injection_pattern")
        if any(p.search(text) for p in _OPT_OUT):
            flags.append("opt_out_keyword")
        return {"text": text, "flags": flags, "attempts": 0, "validation_errors": [],
                "raw_output": None, "model": None, "unavailable": None, "warnings": []}

    def after_sanitize(state: QState) -> str:
        if not state["text"]:
            return "skipped"
        if "arabic_script" in state["flags"]:
            return "unsupported_language"
        return "extract"

    def extract(state: QState) -> QState:
        attempts = state["attempts"] + 1
        repair = attempts > 1
        user = render_user_message(state["text"], state.get("raw_output") if repair else None,
                                   state.get("validation_errors") if repair else None)
        try:
            result = llm.complete_json(system=SYSTEM_PROMPT, user=user,
                                       schema=QUALIFICATION_SCHEMA, schema_name=SCHEMA_NAME)
        except LLMUnavailable as exc:
            return {"attempts": attempts, "unavailable": str(exc)}
        except LLMBadOutput as exc:
            return {"attempts": attempts, "raw_output": None,
                    "validation_errors": [f"provider rejected the output: {exc}"]}
        return {"attempts": attempts, "raw_output": result.content, "model": result.model,
                "validation_errors": []}

    def validate(state: QState) -> QState:
        if state.get("unavailable") or state.get("validation_errors"):
            return {}
        try:
            parsed = ModelExtraction.model_validate(json.loads(state["raw_output"] or ""))
        except json.JSONDecodeError as exc:
            return {"validation_errors": [f"not valid JSON: {exc.msg}"]}
        except ValidationError as exc:
            errors = [f"{'.'.join(map(str, e['loc'])) or 'root'}: {e['msg']}"
                      for e in exc.errors()[:10]]
            return {"validation_errors": errors}
        extraction, conflicts, warnings = post_check(parsed)
        extraction["conflicts"] = conflicts
        return {"extraction": extraction, "warnings": warnings,
                "status": "repaired" if state["attempts"] > 1 else "valid"}

    def after_validate(state: QState) -> str:
        if state.get("unavailable"):
            return "fallback"
        if state.get("validation_errors"):
            return "extract" if state["attempts"] < MAX_ATTEMPTS else "fallback"
        return "gate"

    def gate(state: QState) -> QState:
        ext, flags = state["extraction"], state["flags"]
        reasons = []
        if ext["injection_suspected"] or "injection_pattern" in flags:
            reasons.append("injection_suspected")
        if ext["conflicts"]:
            reasons.append("conflicting_requirements")
        if ext["requests_human"]:
            reasons.append("customer_requested_human")
        if ext["language"].lower()[:2] not in SUPPORTED_LANGUAGES:
            reasons.append("unsupported_language")
        if ext["inquiry_type"] == "rental":
            reasons.append("out_of_scope_rental")
        if ext["confidence"] < min_confidence and ext["inquiry_type"] != "none":
            reasons.append("low_confidence")
        return {"reasons": reasons}

    def fallback(state: QState) -> QState:
        reasons = ["ai_unavailable" if state.get("unavailable") else "ai_output_invalid"]
        if "injection_pattern" in state["flags"]:
            reasons.append("injection_suspected")
        return {"status": "fallback" if state.get("unavailable") else "invalid",
                "extraction": None, "reasons": reasons}

    def unsupported_language(state: QState) -> QState:
        return {"status": "unsupported_language", "extraction": None,
                "reasons": ["unsupported_language"]}

    def skipped(state: QState) -> QState:
        return {"status": "skipped", "extraction": None, "reasons": []}

    graph = StateGraph(QState)
    for name, fn in [("sanitize", sanitize), ("extract", extract), ("validate", validate),
                     ("gate", gate), ("fallback", fallback),
                     ("unsupported_language", unsupported_language), ("skipped", skipped)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "sanitize")
    graph.add_conditional_edges("sanitize", after_sanitize,
                                ["extract", "unsupported_language", "skipped"])
    graph.add_edge("extract", "validate")
    graph.add_conditional_edges("validate", after_validate, ["extract", "gate", "fallback"])
    for terminal in ("gate", "fallback", "unsupported_language", "skipped"):
        graph.add_edge(terminal, END)
    return graph.compile()


def qualify(llm: LLMClient, message: str | None, min_confidence: float = 0.6
            ) -> QualificationResult:
    state = build_graph(llm, min_confidence).invoke({"message": message or ""})
    ext, flags = state.get("extraction"), state["flags"]
    reasons = state["reasons"]
    if "arabic_script" in flags and "unsupported_language" not in reasons:
        reasons.append("unsupported_language")
    return QualificationResult(
        status=state["status"],
        needs_human_review=bool(reasons),
        reasons=reasons,
        opt_out="opt_out_keyword" in flags or bool(ext and ext["opt_out"]),
        requests_human=bool(ext and ext["requests_human"]),
        extraction=ext,
        confidence=ext["confidence"] if ext else None,
        model=state.get("model"),
        prompt_version=PROMPT_VERSION,
        attempts=state["attempts"],
        raw_output=state.get("raw_output"),
        warnings=state.get("warnings", []),
    )


MERGE_FIELDS = ("property_type", "location", "bedrooms", "budget_min", "budget_max", "currency",
                "delivery_preference", "purchase_timeline_months")


def merge_lead(form_lead: dict, result: QualificationResult) -> dict:
    """Customer-entered form fields win; the AI extraction only fills gaps. An extraction from
    an unsupported language is not used."""
    merged = dict(form_lead)
    ext = result.extraction
    if ext is None or "unsupported_language" in result.reasons:
        return merged
    for key in MERGE_FIELDS:
        if merged.get(key) is None and ext.get(key) is not None:
            merged[key] = ext[key]
    if merged.get("location_raw") is None:
        merged["location_raw"] = ext.get("location_raw")
    if merged.get("purchase_intent", "unknown") == "unknown":
        merged["purchase_intent"] = ext["purchase_intent"]
    merged["conflicts"] = sorted(set(merged.get("conflicts", [])) | set(ext["conflicts"]))
    return merged
