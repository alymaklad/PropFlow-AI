"""HTML versions of the email templates, sent next to the plain text (multipart/alternative).

Email-safe on purpose: one 600px table column, inline styles, no web fonts that
matter (Readex Pro where the client loads it, Arial otherwise), no links to the demo host.
Listing photos load from the buyer site when PUBLIC_SITE_URL is set (left out otherwise).
The wording comes from the same data as the plain text in messages.py, so both parts say the
same thing. Every value is escaped.
"""

from html import escape

from app.messages import first_name, money, summary
from app.photos import photo_path

PAPER = "#eeeee8"
CARD = "#ffffff"
INK = "#1d2a33"
INK_SOFT = "#4a5a66"
INK_FAINT = "#7a8792"
NILE = "#0f5c6e"
NILE_WASH = "#e3eef0"
SAND = "#c9a46a"
SAND_DEEP = "#8a6a33"
RULE = "#d9dcd8"
FONT = "'Readex Pro', Arial, Helvetica, sans-serif"
DISPLAY = "'Reem Kufi', 'Readex Pro', Arial, Helvetica, sans-serif"

DELIVERY = {"ready": "Ready to move in", "under_construction": "Under construction",
            "off_plan": "Off plan"}


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def checked_label(days: int) -> str:
    if days <= 0:
        return "Checked today"
    if days == 1:
        return "Checked yesterday"
    return f"Checked {days} days ago"


def listing_title(m: dict) -> str:
    kind = "shop" if m["property_type"] == "commercial" else m["property_type"]
    if m["property_type"] == "studio" or not m.get("bedrooms"):
        text = kind
    else:
        text = f"{m['bedrooms']}-bedroom {kind}"
    return f"{text[:1].upper()}{text[1:]} in {m['location']}"


def _p(text: str, *, size: int = 16, color: str = INK, margin: str = "0 0 16px") -> str:
    return (f'<p style="margin:{margin};font-family:{FONT};font-size:{size}px;line-height:1.55;'
            f'color:{color};">{text}</p>')


def _heading(text: str) -> str:
    return (f'<h2 style="margin:28px 0 12px;font-family:{DISPLAY};font-size:19px;'
            f'font-weight:600;color:{INK};">{_e(text)}</h2>')


def _request_box(req: dict) -> str:
    rows = []
    if req.get("property_type"):
        rows.append(("Type", req["property_type"].capitalize()))
    if req.get("location"):
        rows.append(("Area", req["location"]))
    if req.get("bedrooms") is not None:
        rows.append(("Bedrooms", "Studio" if req["bedrooms"] == 0 else str(req["bedrooms"])))
    if req.get("budget_max") is not None:
        rows.append(("Budget", f"up to {money(req['budget_max'], req.get('currency'))}"))
    elif req.get("budget_min") is not None:
        rows.append(("Budget", f"from {money(req['budget_min'], req.get('currency'))}"))
    if not rows:
        return ""
    def cell(k: str, v: str) -> str:
        return (f'<td width="50%" valign="top" style="padding:6px 0;">'
                f'<p style="margin:0;font-family:{FONT};font-size:11px;letter-spacing:0.5px;'
                f'text-transform:uppercase;color:{INK_SOFT};">{_e(k)}</p>'
                f'<p style="margin:2px 0 0;font-family:{FONT};font-size:15px;font-weight:500;'
                f'color:{INK};">{_e(v)}</p></td>')
    pairs = [rows[i:i + 2] for i in range(0, len(rows), 2)]
    cells = "".join("<tr>" + "".join(cell(k, v) for k, v in pair)
                    + ("<td></td>" if len(pair) == 1 else "") + "</tr>" for pair in pairs)
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:{NILE_WASH};border-radius:8px;margin:0 0 8px;">'
            f'<tr><td style="padding:16px 20px;">'
            f'<p style="margin:0 0 6px;font-family:{FONT};font-size:12px;letter-spacing:1px;'
            f'text-transform:uppercase;color:{NILE};font-weight:600;">Your request</p>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{cells}'
            f'</table></td></tr></table>')


def _listing_card(m: dict, site_url: str | None = None) -> str:
    facts = []
    if m.get("bedrooms"):
        facts.append(f"{m['bedrooms']} bedroom{'s' if m['bedrooms'] != 1 else ''}")
    if m.get("bathrooms"):
        facts.append(f"{m['bathrooms']} bathroom{'s' if m['bathrooms'] != 1 else ''}")
    facts.append(DELIVERY.get(m["delivery_status"], m["delivery_status"].replace("_", " ")))
    amenities = m.get("amenities") or []
    extra = ""
    if amenities:
        text = ", ".join(amenities)
        extra += _p(f'<strong style="color:{INK};">Amenities:</strong> '
                    f'{_e(text[:1].upper() + text[1:])}', size=14, color=INK_SOFT,
                    margin="0 0 6px")
    if m.get("description"):
        extra += _p(_e(m["description"]), size=14, color=INK, margin="0")
    photo = ""
    if site_url:
        src = site_url + photo_path(m["listing_id"], m["property_type"])
        photo = (f'<tr><td style="padding:0;font-size:0;line-height:0;"><img src="{_e(src)}" '
                 f'width="542" alt="{_e(listing_title(m))}" style="display:block;width:100%;'
                 f'max-width:542px;height:auto;border:0;border-radius:8px 8px 0 0;"></td></tr>')
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border:1px solid {RULE};border-radius:8px;margin:0 0 16px;background:{CARD};">'
        f'{photo}<tr><td style="padding:18px 20px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td valign="top"><p style="margin:0 0 2px;font-family:{DISPLAY};font-size:22px;'
        f'font-weight:600;color:{NILE};">{_e(money(m["price"], m["currency"]))}</p>'
        f'<p style="margin:0 0 6px;font-family:{FONT};font-size:16px;font-weight:600;'
        f'color:{INK};">{_e(listing_title(m))}</p></td>'
        f'<td valign="top" align="right" style="padding-left:12px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="border:1px solid '
        f'{SAND};border-radius:12px;"><tr><td style="padding:3px 10px;font-family:{FONT};'
        f'font-size:11px;font-weight:600;color:{SAND_DEEP};white-space:nowrap;">'
        f'{_e(checked_label(m["verified_days_ago"]))}</td></tr></table>'
        f'<p style="margin:4px 0 0;font-family:{FONT};font-size:11px;color:{INK_FAINT};">'
        f'{_e(m["listing_id"])}</p></td></tr></table>'
        f'{_p(_e(" · ".join(facts)), size=14, color=INK_SOFT, margin="0 0 6px")}'
        f'{extra}</td></tr></table>')


def _steps(items: list[str]) -> str:
    rows = "".join(
        f'<tr><td width="34" valign="top" style="padding:0 0 12px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0"><tr><td width="24" '
        f'height="24" align="center" style="background:{NILE};border-radius:12px;'
        f'font-family:{FONT};font-size:12px;font-weight:600;color:#ffffff;">{i}</td></tr>'
        f'</table></td><td valign="top" style="padding:2px 0 12px;font-family:{FONT};'
        f'font-size:15px;line-height:1.5;color:{INK};">{item}</td></tr>'
        for i, item in enumerate(items, 1))
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="background:#fafaf8;border:1px solid {RULE};border-radius:8px;">'
            f'<tr><td style="padding:16px 18px 4px;"><table role="presentation" cellpadding="0" '
            f'cellspacing="0">{rows}</table></td></tr></table>')


def _advisor(name: str, detail: str = "Your PropFlow advisor") -> str:
    initials = "".join(w[0] for w in name.split()[:2]).upper() or "PF"
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:16px 0 0;border:1px solid {RULE};border-radius:8px;"><tr>'
        f'<td style="padding:14px 16px;"><table role="presentation" cellpadding="0" '
        f'cellspacing="0"><tr><td width="48" height="48" align="center" style="background:{SAND};'
        f'border-radius:24px;font-family:{DISPLAY};font-size:17px;font-weight:600;'
        f'color:#ffffff;">{_e(initials)}</td>'
        f'<td style="padding-left:14px;"><p style="margin:0;font-family:{FONT};font-size:16px;'
        f'font-weight:600;color:{INK};">{_e(name)}</p><p style="margin:2px 0 0;'
        f'font-family:{FONT};font-size:13px;color:{INK_SOFT};">{detail}</p></td></tr></table>'
        f'</td></tr></table>')


def _callout(text: str) -> str:
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="margin:24px 0 0;"><tr><td style="background:{NILE};border-radius:8px;'
            f'padding:16px 20px;font-family:{FONT};font-size:16px;font-weight:500;'
            f'color:#ffffff;text-align:center;">{text}</td></tr></table>')


def layout(*, preheader: str, body: str, footer: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light only">'
        '<title>PropFlow Real Estate</title></head>'
        f'<body style="margin:0;padding:0;background:{PAPER};">'
        f'<div style="display:none;max-height:0;overflow:hidden;">{_e(preheader)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{PAPER};"><tr><td align="center" style="padding:24px 12px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="max-width:600px;">'
        f'<tr><td align="center" style="background:{NILE};border-radius:10px 10px 0 0;'
        f'padding:24px 28px;">'
        f'<p style="margin:0;font-family:{DISPLAY};font-size:24px;font-weight:600;'
        f'color:#ffffff;">PropFlow</p>'
        f'<table role="presentation" cellpadding="0" cellspacing="0"><tr><td width="36" '
        f'height="3" style="background:{SAND};font-size:0;line-height:0;">&nbsp;</td></tr>'
        f'</table><p style="margin:8px 0 0;font-family:{FONT};font-size:13px;'
        f'color:{NILE_WASH};">Verified homes in Cairo</p></td></tr>'
        f'<tr><td style="background:{CARD};border-radius:0 0 10px 10px;padding:28px;">'
        f'{body}</td></tr>'
        f'<tr><td style="padding:20px 28px;font-family:{FONT};font-size:12px;line-height:1.5;'
        f'color:{INK_FAINT};text-align:center;">{_e(footer)}<br>PropFlow Real Estate · '
        f'Cairo, Egypt</td></tr></table></td></tr></table></body></html>')


def _greeting(d: dict) -> str:
    return _p(f"Hi {_e(first_name(d.get('name')))},", size=17, margin="0 0 12px")


def _shortlist(d: dict) -> tuple[str, str]:
    matches = d["matches"]
    count = len(matches)
    days = max(m["verified_days_ago"] for m in matches) or 1
    advisor = d["advisor_name"]
    noun = "listing that matches" if count == 1 else "listings that match"
    body = (
        _greeting(d)
        + _p(f"Thank you for your inquiry. Here {'is' if count == 1 else 'are'} {count} "
             f"verified {noun} what you asked for.")
        + _request_box(d["requirements"])
        + _heading("Matching listings")
        + "".join(_listing_card(m, d.get("site_url")) for m in matches)
        + _p(f"Availability and prices were checked within the last {days} day(s) and can "
             "change." + (" Photos are illustrative." if d.get("site_url") else ""),
             size=13, color=INK_SOFT, margin="4px 0 0")
        + _heading("What happens next")
        + _steps([f"{_e(advisor)}, your advisor, reviews your request.",
                  "Reply to this email with the listings you like and a time that suits you.",
                  "We confirm price and availability before any viewing."])
        + _advisor(advisor)
        + _callout("Reply to this email to arrange a viewing"))
    return f"{count} verified {noun} your request", body


def _clarification(d: dict) -> tuple[str, str]:
    questions = {
        "location": "Which area or city are you interested in?",
        "budget": "What budget range do you have in mind?",
        "property_type": "What type of property are you looking for (apartment, villa, ...)?",
        "bedrooms": "How many bedrooms do you need?",
    }
    asked = [_e(questions[m]) for m in d["missing"] if m in questions]
    body = (_greeting(d)
            + _p("Thank you for your inquiry. To find the right options for you, could you "
                 "tell us:")
            + _steps(asked)
            + _callout("Just reply to this email"))
    return "A couple of details and we can match you with listings", body


def _handoff_ack(d: dict) -> tuple[str, str]:
    contact = _e(d["advisor_email"])
    if d.get("advisor_phone"):
        contact += f" · {_e(d['advisor_phone'])}"
    body = (_greeting(d)
            + _p(f"Thank you for your inquiry. {_e(d['advisor_name'])} from our sales team will "
                 f"contact you by <strong>{_e(d['contact_by'])}</strong>.")
            + _advisor(d["advisor_name"], contact))
    return f"{d['advisor_name']} will contact you by {d['contact_by']}", body


def _reminder(d: dict) -> tuple[str, str]:
    body = (_greeting(d)
            + _p(f"Following up on your inquiry about a {_e(summary(d['requirements']))}. "
                 "Are you still looking?")
            + _advisor(d["advisor_name"])
            + _callout(f"Reply and {_e(d['advisor_name'])} will help with options or a "
                       "viewing"))
    return "Still looking for a property?", body


CUSTOMER = {"customer_shortlist": _shortlist, "customer_clarification": _clarification,
            "customer_handoff_ack": _handoff_ack, "customer_reminder": _reminder}


def _plain(text: str) -> str:
    """Internal notifications: the plain text in the same frame, links clickable."""
    parts = []
    for line in text.splitlines():
        if line.startswith("Open the lead: "):
            url = line.removeprefix("Open the lead: ")
            parts.append(f'<p style="margin:16px 0;"><a href="{_e(url)}" style="color:{NILE};'
                         f'font-family:{FONT};font-weight:600;">Open the lead</a></p>')
        elif line.strip():
            parts.append(_p(_e(line), size=15, margin="0 0 8px"))
        else:
            parts.append('<div style="height:8px;"></div>')
    return "".join(parts)


def render_html(template: str, data: dict, text: str, footer: str,
                site_url: str | None = None) -> str:
    """HTML part for an already rendered template (render() validated the data)."""
    if template in CUSTOMER:
        preheader, body = CUSTOMER[template]({**data, "site_url": site_url})
    else:
        preheader, body = text.splitlines()[0], _plain(text)
    return layout(preheader=preheader, body=body, footer=footer)
