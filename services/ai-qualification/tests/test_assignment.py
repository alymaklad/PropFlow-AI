import threading
import uuid

import psycopg
import pytest

from app.assignment import assign, pick_next
from tests.conftest import TEST_DATABASE_URL, needs_db


@pytest.mark.parametrize(("last", "expected"), [
    (None, 10), (10, 11), (11, 12), (12, 10), (99, 10), (5, 10), (11.5, 12),
])
def test_pick_next(last, expected):
    assert pick_next([10, 11, 12], last) == expected


@needs_db
def test_round_robin_cycles(migrated_db):
    picks = [assign(migrated_db, uuid.uuid4(), 1, [10, 11, 12]).user_id for _ in range(7)]
    assert picks == [10, 11, 12, 10, 11, 12, 10]


@needs_db
def test_same_lead_keeps_its_owner_and_does_not_advance(migrated_db):
    cid = uuid.uuid4()
    first = assign(migrated_db, cid, 1, [10, 11, 12])
    again = assign(migrated_db, cid, 1, [10, 11, 12])
    assert (first.user_id, again.user_id, again.reused) == (10, 10, True)
    assert assign(migrated_db, uuid.uuid4(), 1, [10, 11, 12]).user_id == 11


@needs_db
def test_teams_have_independent_pointers(migrated_db):
    assert assign(migrated_db, uuid.uuid4(), 1, [10, 11]).user_id == 10
    assert assign(migrated_db, uuid.uuid4(), 2, [20, 21]).user_id == 20
    assert assign(migrated_db, uuid.uuid4(), 1, [10, 11]).user_id == 11


@needs_db
def test_no_salespeople(migrated_db):
    result = assign(migrated_db, uuid.uuid4(), 1, [])
    assert result.user_id is None
    assert migrated_db.execute("SELECT count(*) FROM lead_assignments").fetchone()[0] == 0


@needs_db
def test_concurrent_assignments_never_share_a_slot(migrated_db):
    results, errors = [], []

    def worker():
        try:
            with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
                results.append(assign(conn, uuid.uuid4(), 1, [10, 11, 12]).user_id)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sorted(results) == [10, 10, 10, 11, 11, 11, 12, 12, 12]


@needs_db
def test_concurrent_assignment_of_same_lead_gets_one_owner(migrated_db):
    cid, results = uuid.uuid4(), []

    def worker():
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            results.append(assign(conn, cid, 1, [10, 11, 12]).user_id)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(results)) == 1
