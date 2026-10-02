import logging
import re
import uuid

import psycopg
from fastapi import Depends, FastAPI, Request, Response

from app.config import Settings, get_settings
from app.routers import v1

logger = logging.getLogger("propflow.ai")

app = FastAPI(title="PropFlow AI Qualification Service", version=get_settings().version)
app.include_router(v1.router)

_CORRELATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


@app.middleware("http")
async def correlation_id(request: Request, call_next):
    """Echo X-Correlation-ID (minted by the webhook) on every response; generate one if absent
    or malformed so every log line can be tied to a request."""
    incoming = request.headers.get("x-correlation-id", "")
    cid = incoming if _CORRELATION_RE.match(incoming) else str(uuid.uuid4())
    request.state.correlation_id = cid
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = cid
    return response


@app.get("/healthz")
def healthz(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    """Liveness: the process is up. No dependencies are checked."""
    return {"status": "ok", "version": settings.version}


@app.get("/readyz")
def readyz(response: Response, settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """Readiness: dependencies this service needs are reachable."""
    checks: dict[str, str] = {}
    if settings.database_url is None:
        checks["database"] = "not_configured"
    else:
        try:
            with psycopg.connect(settings.database_url, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            checks["database"] = "ok"
        except psycopg.Error:
            logger.warning("readiness: database check failed")
            checks["database"] = "unavailable"
    ready = checks["database"] == "ok"
    if not ready:
        response.status_code = 503
    return {"status": "ready" if ready else "not_ready", "checks": checks}
