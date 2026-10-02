"""Customer message templates (Workflow F). Plain text, fixed wording, versioned in the repo.

Rules every template follows: no claim that a property is available, reserved or guaranteed
(listings are described as verified on a date and subject to change); one clear next step;
an opt-out line. The model never writes customer messages.
"""

from collections.abc import Callable

TEMPLATE_VERSION = "customer-v1"
OPT_OUT_LINE = "To stop receiving these emails, reply STOP."
SIGNATURE = "PropFlow Real Estate"


class TemplateError(ValueError):
    pass


def first_name(name: str | None) -> str:
    return (name or "").strip().split(" ")[0] or "there"


def _money(amount: float | None, currency: str | None) -> str:
    if amount is None:
        return ""
    if amount >= 1_000_000:
        text = f"{amount / 1_000_000:.2f}".rstrip("0").rstrip(".") + " million"
    else:
        text = f"{amount:,.0f}"
    return f"{text} {currency or 'EGP'}"


def summary(req: dict) -> str:
    parts = []
    if req.get("bedrooms") is not None:
        parts.append("studio" if req["bedrooms"] == 0 else f"{req['bedrooms']}-bedroom")
    if req.get("property_type") and req.get("property_type") != "studio":
        parts.append(req["property_type"])
    elif not parts:
        parts.append("property")
    text = " ".join(parts)
    if req.get("location"):
        text += f" in {req['location']}"
    if req.get("budget_max") is not None:
        text += f", up to {_money(req['budget_max'], req.get('currency'))}"
    elif req.get("budget_min") is not None:
        text += f", from {_money(req['budget_min'], req.get('currency'))}"
    return text


def _shortlist(d: dict) -> tuple[str, str]:
    lines = [f"Hi {first_name(d.get('name'))},", "",
             f"Thank you for your inquiry about a {summary(d['requirements'])}.",
             "These listings match what you described:", ""]
    for i, m in enumerate(d["matches"], 1):
        beds = "Studio" if m.get("bedrooms") == 0 else (
            f"{m['bedrooms']} bedrooms" if m.get("bedrooms") else m["property_type"].title())
        delivery = m["delivery_status"].replace("_", " ")
        lines.append(f"{i}. {m['listing_id']}: {beds}, {m['location']}, "
                     f"{_money(m['price'], m['currency'])} ({delivery})")
        if m.get("description"):
            lines.append(f"   {m['description']}")
    lines += ["", "Availability and prices were checked within the last "
              f"{max(m['verified_days_ago'] for m in d['matches']) or 1} day(s) and can change. "
              f"{d['advisor_name']}, your advisor, will confirm the details.",
              "Reply to this email to arrange a viewing.", "", OPT_OUT_LINE, SIGNATURE]
    return "Listings that match your request", "\n".join(lines)


def _clarification(d: dict) -> tuple[str, str]:
    questions = {
        "location": "Which area or city are you interested in?",
        "budget": "What budget range do you have in mind?",
        "property_type": "What type of property are you looking for (apartment, villa, ...)?",
        "bedrooms": "How many bedrooms do you need?",
    }
    asked = [questions[m] for m in d["missing"] if m in questions]
    if not asked:
        raise TemplateError("nothing to ask")
    lines = [f"Hi {first_name(d.get('name'))},", "",
             "Thank you for your inquiry. To find the right options for you, could you tell us:",
             "", *[f"- {q}" for q in asked], "",
             "Just reply to this email.", "", OPT_OUT_LINE, SIGNATURE]
    return "A quick question about your property search", "\n".join(lines)


def _handoff_ack(d: dict) -> tuple[str, str]:
    contact = d["advisor_email"]
    if d.get("advisor_phone"):
        contact += f" or {d['advisor_phone']}"
    lines = [f"Hi {first_name(d.get('name'))},", "",
             "Thank you for your inquiry. "
             f"{d['advisor_name']} from our sales team will contact you by {d['contact_by']}.",
             f"You can also reach them directly at {contact}.", "", OPT_OUT_LINE, SIGNATURE]
    return "Your advisor will be in touch", "\n".join(lines)


def _reminder(d: dict) -> tuple[str, str]:
    lines = [f"Hi {first_name(d.get('name'))},", "",
             f"Following up on your inquiry about a {summary(d['requirements'])}. "
             "Are you still looking?",
             f"Reply to this email and {d['advisor_name']} will help with options or a viewing.",
             "", OPT_OUT_LINE, SIGNATURE]
    return "Still looking for a property?", "\n".join(lines)


TEMPLATES: dict[str, tuple[Callable[[dict], tuple[str, str]], tuple[str, ...]]] = {
    "customer_shortlist": (_shortlist, ("requirements", "matches", "advisor_name")),
    "customer_clarification": (_clarification, ("missing",)),
    "customer_handoff_ack": (_handoff_ack, ("advisor_name", "advisor_email", "contact_by")),
    "customer_reminder": (_reminder, ("requirements", "advisor_name")),
}


def render(template: str, data: dict) -> tuple[str, str]:
    if template not in TEMPLATES:
        raise TemplateError(f"unknown template {template!r}")
    fn, required = TEMPLATES[template]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise TemplateError(f"{template} needs {', '.join(missing)}")
    return fn(data)
