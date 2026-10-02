"""Shared FastAPI dependencies: database connection and Odoo client."""

from collections.abc import Iterator
from functools import cache

import psycopg
from fastapi import Depends, HTTPException, status

from app.config import Settings, get_settings
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
