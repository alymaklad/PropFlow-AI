import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

ROOT = Path(__file__).resolve().parents[3]
TEST_API_KEY = "test-key"
TEST_WEBHOOK_SECRET = "test-webhook-secret"


def load_dataset() -> list[dict]:
    path = ROOT / "sample-data" / "synthetic-leads.json"
    return json.loads(path.read_text(encoding="utf-8"))["records"]


@pytest.fixture
def client():
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=None, api_key=TEST_API_KEY, llm_provider="fake"
    )
    yield TestClient(app, headers={"X-API-Key": TEST_API_KEY})
    app.dependency_overrides.clear()


# --- database-backed tests (skipped unless TEST_DATABASE_URL points at a throwaway server) ----

import os  # noqa: E402

import psycopg  # noqa: E402

from app.migrate import migrate  # noqa: E402

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS = ROOT / "database" / "migrations"
needs_db = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def migrated_db():
    """Fresh schema with all migrations applied; yields an autocommit connection."""
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    migrate(TEST_DATABASE_URL, MIGRATIONS)
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        yield conn


@pytest.fixture
def db_client(migrated_db):
    """API client wired to the test database."""
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=TEST_DATABASE_URL, api_key=TEST_API_KEY, llm_provider="fake",
        webhook_hmac_secret=TEST_WEBHOOK_SECRET,
    )
    yield TestClient(app, headers={"X-API-Key": TEST_API_KEY})
    app.dependency_overrides.clear()
