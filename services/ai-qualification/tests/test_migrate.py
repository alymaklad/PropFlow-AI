"""Migration runner tests. Need a Postgres: set TEST_DATABASE_URL (skipped otherwise).

The target database is dropped and recreated per test, so point it at a throwaway server.
"""

import os
import shutil
from pathlib import Path

import psycopg
import pytest

from app.migrate import MigrationError, migrate

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
REAL_MIGRATIONS = Path(__file__).resolve().parents[3] / "database" / "migrations"

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def db_url():
    """A clean schema: drop everything in public before each test."""
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    return TEST_DATABASE_URL


def tables(url: str) -> set[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


def test_applies_to_empty_database(db_url):
    applied = migrate(db_url, REAL_MIGRATIONS)
    assert applied == ["0001", "0002", "0003", "0004"]
    assert {
        "intake_events", "qualifications", "score_results", "properties",
        "outbound_messages", "consents", "escalations", "dead_letters", "schema_migrations",
    } <= tables(db_url)


def test_is_rerunnable(db_url):
    migrate(db_url, REAL_MIGRATIONS)
    assert migrate(db_url, REAL_MIGRATIONS) == []


def test_modified_applied_migration_is_rejected(db_url, tmp_path):
    shutil.copytree(REAL_MIGRATIONS, tmp_path / "m")
    migrate(db_url, tmp_path / "m")
    with (tmp_path / "m" / "0001_initial_schema.sql").open("a") as f:
        f.write("\n-- edited\n")
    with pytest.raises(MigrationError):
        migrate(db_url, tmp_path / "m")


def test_failed_migration_rolls_back(db_url, tmp_path):
    d = tmp_path / "m"
    d.mkdir()
    (d / "0001_ok.sql").write_text("CREATE TABLE a (id int);")
    (d / "0002_bad.sql").write_text("CREATE TABLE b (id int); SELECT broken_function();")
    with pytest.raises(psycopg.Error):
        migrate(db_url, d)
    t = tables(db_url)
    assert "a" in t and "b" not in t


def test_bad_filename_rejected(db_url, tmp_path):
    (tmp_path / "init.sql").write_text("SELECT 1;")
    with pytest.raises(MigrationError):
        migrate(db_url, tmp_path)


def test_idempotency_key_is_unique(db_url):
    migrate(db_url, REAL_MIGRATIONS)
    with psycopg.connect(db_url, autocommit=True) as conn:
        insert = (
            "INSERT INTO intake_events (idempotency_key, source, raw_payload)"
            " VALUES ('k1', 'form', '{}')"
        )
        conn.execute(insert)
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert)


def test_outbound_message_cannot_be_duplicated(db_url):
    migrate(db_url, REAL_MIGRATIONS)
    with psycopg.connect(db_url, autocommit=True) as conn:
        insert = (
            "INSERT INTO outbound_messages (lead_ref, channel, template, sequence_no)"
            " VALUES ('lead-1', 'email', 'ack', 1)"
        )
        conn.execute(insert)
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert)
