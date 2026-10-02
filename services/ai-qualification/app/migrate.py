"""Minimal SQL migration runner.

Applies database/migrations/NNNN_name.sql files in order, each in its own transaction,
recording version and checksum in schema_migrations. Safe to re-run: applied files are
skipped, and a changed checksum on an applied file is an error (migrations are immutable).

Usage: DATABASE_URL=postgresql://... python -m app.migrate
"""

import hashlib
import logging
import os
import re
import sys
from pathlib import Path

import psycopg

logger = logging.getLogger("propflow.migrate")

FILENAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
LOCK_KEY = 727_001  # arbitrary app-wide advisory lock id


class MigrationError(Exception):
    pass


def discover(directory: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        match = FILENAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"bad migration filename: {path.name}")
        found.append((match.group(1), path))
    versions = [v for v, _ in found]
    if len(versions) != len(set(versions)):
        raise MigrationError("duplicate migration version numbers")
    return found


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def migrate(database_url: str, directory: Path) -> list[str]:
    """Apply pending migrations; return the versions applied in this run."""
    migrations = discover(directory)
    applied_now: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version text PRIMARY KEY, filename text NOT NULL,"
                " checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            applied = {
                row[0]: row[1]
                for row in conn.execute("SELECT version, checksum FROM schema_migrations")
            }
            for version, path in migrations:
                digest = checksum(path)
                if version in applied:
                    if applied[version] != digest:
                        raise MigrationError(
                            f"{path.name} was modified after being applied; add a new migration"
                        )
                    continue
                logger.info("applying %s", path.name)
                with conn.transaction():
                    conn.execute(path.read_text())
                    conn.execute(
                        "INSERT INTO schema_migrations (version, filename, checksum)"
                        " VALUES (%s, %s, %s)",
                        (version, path.name, digest),
                    )
                applied_now.append(version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return applied_now


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL is not set")
        return 2
    directory = Path(os.environ.get("MIGRATIONS_DIR", "database/migrations"))
    try:
        applied = migrate(database_url, directory)
    except (MigrationError, psycopg.Error) as exc:
        logger.error("migration failed: %s", exc)
        return 1
    logger.info("applied %d migration(s)", len(applied))
    return 0


if __name__ == "__main__":
    sys.exit(main())
