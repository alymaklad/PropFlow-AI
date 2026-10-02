from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.auth import require_api_key
from app.normalize import normalize_lead
from app.schemas import IntakePayload, NormalizedLeadOut, ScoreOut, ScoreRequest
from app.scoring import ScoringInput, score

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@router.post("/normalize", response_model=NormalizedLeadOut)
def normalize(payload: IntakePayload) -> NormalizedLeadOut:
    """Always 200: an unusable lead comes back with valid=false and error codes, so the
    workflow can record the rejection instead of dropping it."""
    lead = normalize_lead(payload.model_dump())
    return NormalizedLeadOut(valid=lead.valid, **asdict(lead))


@router.post("/score", response_model=ScoreOut)
def score_lead(body: ScoreRequest) -> ScoreOut:
    result = score(ScoringInput(**body.model_dump()))
    return ScoreOut(**asdict(result))
