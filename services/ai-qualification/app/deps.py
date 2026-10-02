"""Shared FastAPI dependencies: database connection and Odoo client."""

from collections.abc import Iterator
from functools import cache

import psycopg
from fastapi import Depends, HTTPException, status

from app.config import Settings, get_settings
from app.llm import GroqClient, LLMClient, LLMUnavailable
from app.odoo_client import OdooClient


def get_db(settings: Settings = Depends(get_settings)) -> Iterator[psycopg.Connection]:
    if not settings.database_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database not configured")
    try:
        conn = psycopg.connect(settings.database_url, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    try:
        yield conn
    finally:
        conn.close()


@cache
def _odoo_client(url: str, db: str, login: str, api_key: str) -> OdooClient:
    return OdooClient(url, db, login, api_key)


def get_odoo(settings: Settings = Depends(get_settings)) -> OdooClient:
    if not (settings.odoo_url and settings.odoo_db and settings.odoo_login
            and settings.odoo_api_key):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Odoo not configured")
    return _odoo_client(settings.odoo_url, settings.odoo_db, settings.odoo_login,
                        settings.odoo_api_key)


class UnavailableLLM:
    """Stands in when the configured provider cannot be built (e.g. no API key): every call
    raises LLMUnavailable, so qualification falls back to a salesperson handoff."""

    def __init__(self, reason: str) -> None:
        self.model = "unavailable"
        self._reason = reason

    def complete_json(self, **_: object):
        raise LLMUnavailable(self._reason)


@cache
def _llm(provider: str, api_key: str | None, model: str, strict: bool,
         reasoning_effort: str | None) -> LLMClient:
    # FakeLLM is for tests only (they override get_llm). At runtime "none"/"fake" means AI is
    # switched off: qualification falls back and free-text leads go to a salesperson.
    if provider in ("none", "fake"):
        return UnavailableLLM(f"AI qualification is disabled (LLM_PROVIDER={provider})")
    if provider == "groq":
        try:
            return GroqClient(api_key or "", model, strict=strict,
                              reasoning_effort=reasoning_effort)
        except LLMUnavailable as exc:
            return UnavailableLLM(str(exc))
    return UnavailableLLM(f"unknown LLM_PROVIDER {provider!r}")


def get_llm(settings: Settings = Depends(get_settings)) -> LLMClient:
    return _llm(settings.llm_provider, settings.groq_api_key, settings.groq_model,
                settings.groq_strict, settings.groq_reasoning_effort)
