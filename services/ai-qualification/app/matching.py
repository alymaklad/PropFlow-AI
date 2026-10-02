"""Deterministic property matching (tasks 2.7, 2.8).

Only listings that are `available` and were verified within the freshness window are ever
returned, so nothing stale or sold can be presented as available. Outcomes:
- matched: at least one listing fits
- none: the criteria are usable but nothing fits (the lead is handed to a salesperson)
- insufficient_criteria: no location or no budget (ask the customer)
- conflict: contradictory requirements (handed to a salesperson; no search)
"""

from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row

FRESHNESS_DAYS = 14
PRICE_TOLERANCE = 0.05  # listings up to 5% above the stated maximum still count
MAX_MATCHES = 5
DELIVERY_FILTER = {
    "ready": ["ready"],
    "under_construction": ["under_construction", "off_plan"],
    "off_plan": ["under_construction", "off_plan"],
}


@dataclass
class MatchResult:
    status: str
    matches: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    criteria: dict = field(default_factory=dict)


def criteria_from_lead(lead: dict) -> dict:
    return {k: lead.get(k) for k in ("property_type", "location", "bedrooms", "budget_min",
                                     "budget_max", "currency", "delivery_preference")}


def find_matches(conn: psycopg.Connection, lead: dict, *, freshness_days: int = FRESHNESS_DAYS,
                 tolerance: float = PRICE_TOLERANCE, limit: int = MAX_MATCHES) -> MatchResult:
    criteria = criteria_from_lead(lead)
    if lead.get("conflicts"):
        return MatchResult("conflict", criteria=criteria)
    missing = [name for name, present in (
        ("location", criteria["location"] is not None),
        ("budget", criteria["budget_min"] is not None or criteria["budget_max"] is not None),
    ) if not present]
    if missing:
        return MatchResult("insufficient_criteria", missing=missing, criteria=criteria)

    lo, hi = criteria["budget_min"], criteria["budget_max"]
    target = hi if hi is not None else lo
    conditions = [
        "availability = 'available'",
        "last_verified_at >= now() - make_interval(days => %(fresh)s)",
        "location = %(location)s",
        "currency = %(currency)s",
    ]
    params = {"fresh": freshness_days, "location": criteria["location"],
              "currency": criteria["currency"] or "EGP", "target": target, "limit": limit}
    if criteria["property_type"]:
        conditions.append("property_type = %(ptype)s")
        params["ptype"] = criteria["property_type"]
    if criteria["bedrooms"] is not None:
        conditions.append("bedrooms = %(bedrooms)s")
        params["bedrooms"] = criteria["bedrooms"]
    if hi is not None:
        conditions.append("price <= %(hi)s")
        params["hi"] = hi * (1 + tolerance)
    if lo is not None:
        conditions.append("price >= %(lo)s")
        params["lo"] = lo * (1 - tolerance)
    if criteria["delivery_preference"] in DELIVERY_FILTER:
        conditions.append("delivery_status = ANY(%(delivery)s)")
        params["delivery"] = DELIVERY_FILTER[criteria["delivery_preference"]]

    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT listing_id, property_type, location, price::float AS price, currency,"
            " bedrooms, bathrooms, delivery_status, amenities, description,"
            " EXTRACT(day FROM now() - last_verified_at)::int AS verified_days_ago"
            " FROM properties WHERE " + " AND ".join(conditions)
            + " ORDER BY abs(price - %(target)s), listing_id LIMIT %(limit)s",
            params,
        ).fetchall()
    return MatchResult("matched" if rows else "none", matches=rows, criteria=criteria)
