"""Minimal Odoo 17 external-API client (JSON-RPC `/jsonrpc`, API key in place of a password).

Errors are classified so callers can decide what to retry:
- OdooTransientError: timeouts, connection failures, 429/5xx, DB concurrency errors. Retried
  here with bounded exponential backoff, then raised.
- OdooDuplicateError: the propflow_correlation_id unique constraint fired (the record exists).
- OdooPermanentError: authentication, access, validation and programming errors. Not retried.

Retrying a `create` is safe only because leads carry a unique correlation id: if the first
attempt succeeded but its response was lost, the retry fails with OdooDuplicateError and the
caller looks the lead up instead of creating a second one.
"""

import itertools
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger("propflow.odoo")

DUPLICATE_MARKERS = ("propflow_correlation_id_unique", "PropFlow correlation ID already exists")
TRANSIENT_ERROR_MARKERS = ("SerializationFailure", "ConcurrencyError", "LockNotAvailable",
                           "could not serialize access", "TransactionRollbackError")
TRANSIENT_HTTP = {429, 500, 502, 503, 504}


class OdooError(Exception):
    pass


class OdooTransientError(OdooError):
    pass


class OdooPermanentError(OdooError):
    pass


class OdooDuplicateError(OdooPermanentError):
    pass


def classify_rpc_error(error: dict) -> OdooError:
    data = error.get("data") or {}
    name = data.get("name", "")
    message = data.get("message") or error.get("message") or "Odoo error"
    text = f"{name}: {message}"
    if any(marker in text for marker in DUPLICATE_MARKERS):
        return OdooDuplicateError(text)
    if any(marker in text for marker in TRANSIENT_ERROR_MARKERS):
        return OdooTransientError(text)
    return OdooPermanentError(text)


class OdooClient:
    def __init__(
        self,
        url: str,
        db: str,
        login: str,
        api_key: str,
        *,
        timeout: float = 10.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.db, self.login, self._key = db, login, api_key
        self._http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout, transport=transport)
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._sleep = sleep
        self._ids = itertools.count(1)
        self._uid: int | None = None

    def close(self) -> None:
        self._http.close()

    # --- transport ---------------------------------------------------------------------------

    def _post(self, service: str, method: str, args: list) -> Any:
        payload = {"jsonrpc": "2.0", "method": "call", "id": next(self._ids),
                   "params": {"service": service, "method": method, "args": args}}
        try:
            response = self._http.post("/jsonrpc", json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise OdooTransientError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code in TRANSIENT_HTTP:
            raise OdooTransientError(f"HTTP {response.status_code}")
        if response.status_code != 200:
            raise OdooPermanentError(f"HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise OdooTransientError("invalid JSON from Odoo") from exc
        if "error" in body:
            raise classify_rpc_error(body["error"])
        return body.get("result")

    def _with_retry(self, fn: Callable[[], Any]) -> Any:
        for attempt in range(1, self._max_attempts + 1):
            try:
                return fn()
            except OdooTransientError as exc:
                if attempt == self._max_attempts:
                    raise
                delay = self._backoff * 2 ** (attempt - 1)
                logger.warning("odoo transient error (attempt %d/%d), retrying in %.1fs: %s",
                               attempt, self._max_attempts, delay, exc)
                self._sleep(delay)
        raise AssertionError("unreachable")

    # --- API ---------------------------------------------------------------------------------

    @property
    def uid(self) -> int:
        if self._uid is None:
            uid = self._with_retry(
                lambda: self._post("common", "authenticate", [self.db, self.login, self._key, {}])
            )
            if not uid:
                raise OdooPermanentError("authentication failed: check login and API key")
            self._uid = uid
        return self._uid

    def execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        uid = self.uid
        return self._with_retry(lambda: self._post(
            "object", "execute_kw", [self.db, uid, self._key, model, method, list(args), kwargs]))

    def search_read(self, model: str, domain: list, fields: list[str], **kwargs: Any) -> list[dict]:
        return self.execute(model, "search_read", domain, fields=fields, **kwargs)

    def version(self) -> str:
        return self._with_retry(lambda: self._post("common", "version", []))["server_version"]
