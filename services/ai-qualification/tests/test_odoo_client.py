import json

import httpx
import pytest

from app.odoo_client import (
    OdooClient,
    OdooDuplicateError,
    OdooPermanentError,
    OdooTransientError,
)


def rpc_error(name, message):
    return {"jsonrpc": "2.0", "id": 1, "error": {"code": 200, "message": "Odoo Server Error",
                                                 "data": {"name": name, "message": message}}}


def make_client(responses, attempts=3):
    """responses: list of callables or values consumed in order (one per HTTP call)."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["params"])
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, int):
            return httpx.Response(item)
        return httpx.Response(200, json=item)

    client = OdooClient("http://odoo", "db", "login", "key", max_attempts=attempts,
                        transport=httpx.MockTransport(handler), sleep=lambda s: None)
    return client, calls


def ok(result):
    return {"jsonrpc": "2.0", "id": 1, "result": result}


def test_authenticates_once_and_executes():
    client, calls = make_client([ok(6), ok([1, 2]), ok(True)])
    assert client.execute("crm.lead", "search", [("type", "=", "lead")]) == [1, 2]
    assert client.execute("crm.lead", "write", [1], {"name": "x"}) is True
    assert [c["method"] for c in calls] == ["authenticate", "execute_kw", "execute_kw"]
    assert calls[1]["args"][:5] == ["db", 6, "key", "crm.lead", "search"]


def test_failed_authentication_is_permanent():
    client, _ = make_client([ok(False)])
    with pytest.raises(OdooPermanentError, match="authentication failed"):
        client.execute("crm.lead", "search", [])


def test_duplicate_is_classified():
    client, _ = make_client([ok(6), rpc_error(
        "odoo.exceptions.ValidationError",
        "The operation cannot be completed: A lead with this PropFlow correlation ID already "
        "exists.")])
    with pytest.raises(OdooDuplicateError):
        client.execute("crm.lead", "create", [{}])


def test_access_error_is_permanent_and_not_retried():
    client, calls = make_client([ok(6), rpc_error("odoo.exceptions.AccessError", "nope")])
    with pytest.raises(OdooPermanentError):
        client.execute("crm.lead", "unlink", [1])
    assert len(calls) == 2


def test_transient_errors_are_retried_then_succeed():
    client, calls = make_client([
        ok(6),
        httpx.ReadTimeout("slow"),
        503,
        rpc_error("psycopg2.errors.SerializationFailure", "could not serialize access"),
        ok(42),
    ], attempts=4)
    assert client.execute("crm.lead", "create", [{}]) == 42
    assert len(calls) == 5


def test_transient_errors_give_up_after_max_attempts():
    client, calls = make_client([ok(6), httpx.ConnectError("down"), 502, 504])
    with pytest.raises(OdooTransientError):
        client.execute("crm.lead", "search", [])
    assert len(calls) == 4  # authenticate + 3 attempts


def test_lost_create_response_surfaces_as_duplicate_on_retry():
    client, _ = make_client([ok(6), httpx.ReadTimeout("lost"), rpc_error(
        "odoo.exceptions.ValidationError", "A lead with this PropFlow correlation ID already "
        "exists.")])
    with pytest.raises(OdooDuplicateError):
        client.execute("crm.lead", "create", [{"propflow_correlation_id": "c"}])


def test_client_error_status_is_permanent():
    client, calls = make_client([ok(6), 404])
    with pytest.raises(OdooPermanentError):
        client.execute("crm.lead", "search", [])
    assert len(calls) == 2


def test_kwargs_are_passed_through():
    client, calls = make_client([ok(6), ok([])])
    client.search_read("crm.lead", [], ["id"], limit=1, context={"active_test": False})
    assert calls[1]["args"][6] == {"fields": ["id"], "limit": 1,
                                   "context": {"active_test": False}}
