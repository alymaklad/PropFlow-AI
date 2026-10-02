import os
from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    api_key: str | None
    llm_provider: str
    odoo_url: str | None = None
    odoo_db: str | None = None
    odoo_login: str | None = None
    odoo_api_key: str | None = None
    odoo_sales_team_id: int | None = None
    odoo_public_url: str = "http://localhost:8069"
    webhook_hmac_secret: str | None = None
    webhook_max_skew_seconds: int = 300
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"
    groq_strict: bool = True
    groq_reasoning_effort: str | None = None
    qualify_min_confidence: float = 0.6
    version: str = "0.1.0"


def load_settings() -> Settings:
    team = os.environ.get("ODOO_SALES_TEAM_ID")
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or None,
        api_key=os.environ.get("AI_SERVICE_API_KEY") or None,
        llm_provider=os.environ.get("LLM_PROVIDER", "fake"),
        odoo_url=os.environ.get("ODOO_URL") or None,
        odoo_db=os.environ.get("ODOO_DB_NAME") or None,
        odoo_login=os.environ.get("ODOO_INTEGRATION_LOGIN") or None,
        odoo_api_key=os.environ.get("ODOO_API_KEY") or None,
        odoo_sales_team_id=int(team) if team else None,
        odoo_public_url=os.environ.get("ODOO_PUBLIC_URL") or "http://localhost:8069",
        webhook_hmac_secret=os.environ.get("WEBHOOK_HMAC_SECRET") or None,
        groq_api_key=os.environ.get("GROQ_API_KEY") or None,
        groq_model=os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b",
        groq_strict=os.environ.get("GROQ_STRICT", "true").lower() != "false",
        groq_reasoning_effort=os.environ.get("GROQ_REASONING_EFFORT") or None,
        qualify_min_confidence=float(os.environ.get("QUALIFY_MIN_CONFIDENCE") or 0.6),
    )


@cache
def get_settings() -> Settings:
    """FastAPI dependency; tests override it via app.dependency_overrides."""
    return load_settings()
