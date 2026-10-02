import logging

import psycopg
from fastapi import FastAPI, Response

from app.config import load_settings

logger = logging.getLogger("propflow.ai")

settings = load_settings()
app = FastAPI(title="PropFlow AI Qualification Service", version=settings.version)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. No dependencies are checked."""
    return {"status": "ok", "version": settings.version}


@app.get("/readyz")
def readyz(response: Response) -> dict[str, object]:
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
