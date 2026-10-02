import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    api_key: str | None
    llm_provider: str
    version: str = "0.1.0"


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or None,
        api_key=os.environ.get("AI_SERVICE_API_KEY") or None,
        llm_provider=os.environ.get("LLM_PROVIDER", "fake"),
    )
