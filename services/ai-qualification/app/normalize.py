"""Deterministic normalization of inbound lead fields (task 1.2).

Every function is pure. Field-level problems never raise to the caller: they come back as
warning or conflict codes and the field is left empty, so one bad field does not lose the
lead. Only a lead with no usable contact or no content is invalid (see `normalize_lead`).
"""

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import phonenumbers

DEFAULT_REGION = "EG"
DATA_DIR = Path(__file__).parent / "data"
MAX_MESSAGE_CHARS = 5000
MAX_NAME_CHARS = 120

# Arabic-Indic and Persian digits, Arabic decimal and thousands separators
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")

# Web-form choice keys (documented in docs/api-specification.md)
TIMELINE_CHOICES = {
    "immediately": 1,
    "within_3_months": 3,
    "3_6_months": 6,
    "6_12_months": 12,
    "over_12_months": 18,
}
PURCHASE_STAGE_CHOICES = {
    "ready_to_buy": "high", "comparing_options": "medium", "just_browsing": "low",
}


def to_ascii_digits(text: str) -> str:
    return text.translate(_DIGITS)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", to_ascii_digits(text)).strip()


# --- contact ----------------------------------------------------------------------------------

def normalize_phone(raw: str | None, region: str = DEFAULT_REGION) -> str | None:
    """Return the E.164 form of a valid phone number, else None."""
    if not raw or not raw.strip():
        return None
    try:
        number = phonenumbers.parse(to_ascii_digits(raw), region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def normalize_email(raw: str | None) -> str | None:
    """Lowercase and trim; None if it does not look like an address."""
    if not raw:
        return None
    email = raw.strip().lower()
    return email if _EMAIL_RE.match(email) else None


# --- vocabulary lookups ---------------------------------------------------------------------------

@cache
def _aliases(filename: str) -> list[tuple[str, str]]:
    """(alias, canonical) pairs, longest alias first so 'new cairo' beats 'cairo'."""
    data = json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
    pairs = [
        (alias.lower(), canonical)
        for canonical, aliases in data.items()
        if not canonical.startswith("_")
        for alias in [canonical, *aliases]
    ]
    return sorted(pairs, key=lambda p: len(p[0]), reverse=True)


def _lookup(raw: str | None, filename: str) -> str | None:
    if not raw or not raw.strip():
        return None
    text = _clean(raw).lower()
    for alias, canonical in _aliases(filename):
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text):
            return canonical
    return None


def normalize_location(raw: str | None) -> str | None:
    return _lookup(raw, "locations.json")


def normalize_property_type(raw: str | None) -> str | None:
    return _lookup(raw, "property_types.json")


# --- numbers ----------------------------------------------------------------------------------

def normalize_bedrooms(raw: int | str | None) -> int | None:
    """'studio' -> 0, '3', '3br', '3 bedrooms' -> 3. None if missing or out of range."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        value = raw
    else:
        text = _clean(raw).lower()
        if not text:
            return None
        if "studio" in text:
            return 0
        match = re.fullmatch(r"(\d{1,2})\s*(?:br|bd|bed|beds|bedroom|bedrooms|rooms?)?\+?", text)
        if not match:
            return None
        value = int(match.group(1))
    return value if 0 <= value <= 20 else None


_MULTIPLIERS = {
    "billion": 1_000_000_000, "bn": 1_000_000_000,
    "million": 1_000_000, "millions": 1_000_000, "mil": 1_000_000, "mn": 1_000_000,
    "m": 1_000_000, "مليون": 1_000_000,
    "thousand": 1_000, "k": 1_000, "ألف": 1_000, "الف": 1_000,
}
_NUM_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(" + "|".join(sorted(map(re.escape, _MULTIPLIERS), key=len, reverse=True))
    + r")?(?!\w)",
)
_MAX_WORDS = re.compile(r"\b(up to|upto|under|below|max(?:imum)?|less than|no more than|"
                        r"not more than|within)\b|حد أقصى|بحد أقصى")
_MIN_WORDS = re.compile(r"\b(at least|min(?:imum)?|from|over|above|more than|starting)\b")
_RANGE_SEP = re.compile(r"^\s*(?:-|–|—|to|and|or|لـ|ل|الى|إلى)\s*$")


class BudgetError(ValueError):
    """Raised with a short code: 'budget_unparseable', 'budget_ambiguous_unit',
    'budget_min_gt_max'."""


@dataclass(frozen=True)
class Budget:
    min: int | None
    max: int | None
    currency: str


def _currency(text: str) -> str:
    if re.search(r"\$|\busd\b|dollar", text):
        return "USD"
    if re.search(r"€|\beur\b|euro", text):
        return "EUR"
    return "EGP"


def parse_budget(raw: str | int | float | None) -> Budget | None:
    """Parse free-text budgets such as '6-8 million', 'up to 15M', 'USD 150,000'.

    Conventions (sample-data/README.md): a range gives min and max; a single figure, or one
    qualified by 'up to'/'under', gives max only; 'at least'/'from' gives min only.
    A bare number below 10,000 with no unit is ambiguous (thousands? millions?) and rejected.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        if raw <= 0:
            raise BudgetError("budget_unparseable")
        return Budget(None, int(round(raw)), "EGP")

    text = _clean(str(raw)).lower()
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)  # 150,000 -> 150000
    currency = _currency(text)

    matches = list(_NUM_RE.finditer(text))
    if not matches:
        raise BudgetError("budget_unparseable")

    values: list[float] = []
    units: list[int | None] = []
    for m in matches:
        values.append(float(m.group(1)))
        units.append(_MULTIPLIERS[m.group(2)] if m.group(2) else None)

    def amount(i: int, fallback_unit: int | None) -> int:
        unit = units[i] or fallback_unit
        if unit is None:
            if values[i] < 10_000:
                raise BudgetError("budget_ambiguous_unit")
            unit = 1
        return int(round(values[i] * unit))

    # "min 9 million max 6 million" style: assign by keyword
    min_kw = re.search(r"\bmin(?:imum)?\b\D*?(\d)", text)
    max_kw = re.search(r"\bmax(?:imum)?\b\D*?(\d)", text)
    if len(matches) >= 2 and min_kw and max_kw:
        lo_i = next(i for i, m in enumerate(matches) if m.start() >= min_kw.start(1))
        hi_i = next(i for i, m in enumerate(matches) if m.start() >= max_kw.start(1))
        lo, hi = amount(lo_i, units[hi_i]), amount(hi_i, units[lo_i])
    elif len(matches) >= 2 and _RANGE_SEP.match(text[matches[0].end():matches[1].start()]):
        lo, hi = amount(0, units[1]), amount(1, units[0])
    elif len(matches) == 1 or not _RANGE_SEP.match(text[matches[0].end():matches[1].start()]):
        value = amount(0, None)
        if _MIN_WORDS.search(text) and not _MAX_WORDS.search(text):
            return Budget(value, None, currency)
        return Budget(None, value, currency)
    if lo > hi:
        raise BudgetError("budget_min_gt_max")
    return Budget(lo, hi, currency)


def normalize_timeline(raw: int | str | None) -> int | None:
    """Months until purchase: an integer, a numeric string, or a form choice key."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 0 < raw <= 120 else None
    text = _clean(raw).lower()
    if text in TIMELINE_CHOICES:
        return TIMELINE_CHOICES[text]
    if text.isdigit():
        return normalize_timeline(int(text))
    return None


# --- whole lead ---------------------------------------------------------------------------------

@dataclass
class NormalizedLead:
    source: str
    name: str | None
    phone: str | None
    email: str | None
    contact_key: str | None
    message: str | None
    property_type: str | None = None
    location: str | None = None
    location_raw: str | None = None
    bedrooms: int | None = None
    budget_min: int | None = None
    budget_max: int | None = None
    currency: str | None = None
    purchase_timeline_months: int | None = None
    purchase_intent: str = "unknown"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def normalize_lead(payload: dict) -> NormalizedLead:
    """Normalize a raw intake payload. Invalid only if there is no usable contact or content."""
    warnings: list[str] = []
    conflicts: list[str] = []
    errors: list[str] = []

    name = _clean(payload.get("name") or "")[:MAX_NAME_CHARS] or None
    if name is None:
        warnings.append("name_missing")

    raw_phone, raw_email = payload.get("phone"), payload.get("email")
    phone = normalize_phone(raw_phone)
    if raw_phone and not phone:
        warnings.append("phone_invalid")
    email = normalize_email(raw_email)
    if raw_email and not email:
        warnings.append("email_invalid")
    if not phone and not email:
        errors.append("contact_missing")

    message = (payload.get("message") or "").strip() or None
    if message and len(message) > MAX_MESSAGE_CHARS:
        message = message[:MAX_MESSAGE_CHARS]
        warnings.append("message_truncated")

    lead = NormalizedLead(
        source=payload.get("source") or "form",
        name=name,
        phone=phone,
        email=email,
        contact_key=phone or email,
        message=message,
    )

    raw_type = payload.get("property_type")
    lead.property_type = normalize_property_type(raw_type)
    if raw_type and not lead.property_type:
        warnings.append("property_type_unrecognized")

    raw_location = payload.get("location")
    lead.location = normalize_location(raw_location)
    lead.location_raw = _clean(raw_location)[:200] if raw_location else None
    if raw_location and not lead.location:
        warnings.append("location_unrecognized")

    raw_bedrooms = payload.get("bedrooms")
    lead.bedrooms = normalize_bedrooms(raw_bedrooms)
    if raw_bedrooms not in (None, "") and lead.bedrooms is None:
        warnings.append("bedrooms_invalid")
    if lead.property_type == "studio" and lead.bedrooms not in (None, 0):
        conflicts.append("studio_with_bedrooms")

    budget = None
    try:
        if payload.get("budget_min") is not None or payload.get("budget_max") is not None:
            lo, hi = payload.get("budget_min"), payload.get("budget_max")
            lo = parse_budget(lo).max if lo is not None else None
            hi = parse_budget(hi).max if hi is not None else None
            if lo is not None and hi is not None and lo > hi:
                raise BudgetError("budget_min_gt_max")
            budget = Budget(lo, hi, (payload.get("currency") or "EGP").upper()[:3])
        else:
            budget = parse_budget(payload.get("budget"))
    except BudgetError as exc:
        (conflicts if str(exc) == "budget_min_gt_max" else warnings).append(str(exc))
    if budget:
        lead.budget_min, lead.budget_max, lead.currency = budget.min, budget.max, budget.currency

    raw_timeline = payload.get("timeline")
    lead.purchase_timeline_months = normalize_timeline(raw_timeline)
    if raw_timeline not in (None, "") and lead.purchase_timeline_months is None:
        warnings.append("timeline_invalid")

    stage = (payload.get("purchase_stage") or "").strip().lower()
    lead.purchase_intent = PURCHASE_STAGE_CHOICES.get(stage, "unknown")
    if stage and stage not in PURCHASE_STAGE_CHOICES:
        warnings.append("purchase_stage_invalid")

    has_content = message or any(
        v is not None for v in (lead.property_type, lead.location, lead.bedrooms, lead.budget_max,
                                lead.budget_min)
    )
    if not has_content:
        errors.append("content_missing")

    lead.errors, lead.warnings, lead.conflicts = errors, warnings, conflicts
    return lead
