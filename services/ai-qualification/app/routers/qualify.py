"""AI qualification endpoint. Returns data only; it never writes to Odoo or sends anything."""

from dataclasses import asdict

import psycopg
from fastapi import APIRouter, Depends
from psycopg.types.json import Jsonb

from app.auth import require_api_key
from app.config import Settings, get_settings
from app.deps import get_db, get_llm
from app.llm import LLMClient
from app.qualification import QualificationResult, merge_lead, qualify
from app.schemas import NormalizedLeadOut, QualifyOut, QualifyRequest

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


def record_trace(conn: psycopg.Connection, body: QualifyRequest,
                 result: QualificationResult) -> None:
    conn.execute(
        """
        INSERT INTO qualifications (event_id, correlation_id, model, prompt_version, raw_output,
                                    validated_output, validation_status, confidence,
                                    needs_human_review, reasons, attempts)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (body.event_id, body.correlation_id, result.model, result.prompt_version,
         result.raw_output, Jsonb(result.extraction) if result.extraction else None,
         result.status, result.confidence, result.needs_human_review, result.reasons,
         result.attempts),
    )


@router.post("/qualify", response_model=QualifyOut)
def qualify_lead(body: QualifyRequest, conn: psycopg.Connection = Depends(get_db),
                 llm: LLMClient = Depends(get_llm),
                 settings: Settings = Depends(get_settings)) -> QualifyOut:
    """Always 200. Provider failures produce status `fallback` with needs_human_review=true,
    and the merged lead then contains the form fields only."""
    result = qualify(llm, body.lead.message, settings.qualify_min_confidence)
    if body.event_id:
        record_trace(conn, body, result)
    merged = merge_lead(body.lead.model_dump(), result)
    data = asdict(result)
    for key in ("attempts", "raw_output", "warnings"):
        data.pop(key)
    return QualifyOut(**data, lead=NormalizedLeadOut(**merged))
