"""Property matching endpoint (read-only search plus an outcome record)."""

import psycopg
from fastapi import APIRouter, Depends
from psycopg.types.json import Jsonb

from app.auth import require_api_key
from app.deps import get_db
from app.matching import find_matches
from app.schemas import MatchOut, MatchRequest

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@router.post("/match", response_model=MatchOut)
def match(body: MatchRequest, conn: psycopg.Connection = Depends(get_db)) -> MatchOut:
    result = find_matches(conn, body.lead.model_dump())
    conn.execute(
        "INSERT INTO match_results (event_id, correlation_id, status, listing_ids, criteria)"
        " VALUES (%s, %s, %s, %s, %s)",
        (body.event_id, body.correlation_id, result.status,
         [m["listing_id"] for m in result.matches], Jsonb(result.criteria)),
    )
    return MatchOut(status=result.status, matches=result.matches, missing=result.missing,
                    criteria=result.criteria)
