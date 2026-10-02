"""Round-robin salesperson assignment (task 1.6).

The candidate list comes from Odoo (active members of the configured sales team); the pointer
and the per-lead assignment live in Postgres. The pointer row is locked for the duration of
the pick, so concurrent intakes never take the same slot, and an assignment is recorded per
correlation id, so retries return the same owner instead of advancing the pointer again.
"""

from dataclasses import dataclass
from uuid import UUID

import psycopg

from app.odoo_client import OdooClient


@dataclass(frozen=True)
class Assignment:
    team_id: int
    user_id: int | None  # None when the team has no active salespeople
    reused: bool


def resolve_team_id(odoo: OdooClient, configured: int | None) -> int:
    if configured:
        return configured
    teams = odoo.search_read("crm.team", [], ["id"], limit=1, order="id")
    if not teams:
        raise LookupError("no sales team exists in Odoo")
    return teams[0]["id"]


def active_salespeople(odoo: OdooClient, team_id: int) -> list[int]:
    members = odoo.search_read(
        "crm.team.member",
        [("crm_team_id", "=", team_id), ("user_id.active", "=", True)],
        ["user_id"],
    )
    return sorted({m["user_id"][0] for m in members if m.get("user_id")})


def pick_next(candidates: list[int], last_user_id: int | None) -> int:
    """The first candidate after the last one assigned, wrapping around. Works even if the
    last user has since left the team."""
    if last_user_id is not None:
        for user_id in candidates:
            if user_id > last_user_id:
                return user_id
    return candidates[0]


def assign(conn: psycopg.Connection, correlation_id: UUID, team_id: int,
           candidates: list[int]) -> Assignment:
    try:
        return _assign(conn, correlation_id, team_id, candidates)
    except psycopg.errors.UniqueViolation:
        # A concurrent request assigned this lead first; its owner wins.
        return _assign(conn, correlation_id, team_id, candidates)


def _assign(conn: psycopg.Connection, correlation_id: UUID, team_id: int,
            candidates: list[int]) -> Assignment:
    with conn.transaction():
        row = conn.execute(
            "SELECT team_id, user_id FROM lead_assignments WHERE correlation_id = %s",
            (correlation_id,),
        ).fetchone()
        if row:
            return Assignment(team_id=row[0], user_id=row[1], reused=True)
        if not candidates:
            return Assignment(team_id=team_id, user_id=None, reused=False)

        conn.execute(
            "INSERT INTO round_robin_state (team_id) VALUES (%s) ON CONFLICT DO NOTHING",
            (team_id,),
        )
        (last_user_id,) = conn.execute(
            "SELECT last_user_id FROM round_robin_state WHERE team_id = %s FOR UPDATE",
            (team_id,),
        ).fetchone()
        user_id = pick_next(candidates, last_user_id)
        conn.execute(
            "UPDATE round_robin_state SET last_user_id = %s, updated_at = now()"
            " WHERE team_id = %s",
            (user_id, team_id),
        )
        conn.execute(
            "INSERT INTO lead_assignments (correlation_id, team_id, user_id) VALUES (%s, %s, %s)",
            (correlation_id, team_id, user_id),
        )
        return Assignment(team_id=team_id, user_id=user_id, reused=False)
