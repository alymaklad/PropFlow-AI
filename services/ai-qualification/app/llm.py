"""LLM providers behind one small interface (task 2.1).

Only one operation is needed: return JSON that matches a schema. Providers:
- GroqClient: Groq's OpenAI-compatible chat API with strict JSON-schema output. Retries 429
  (honouring Retry-After, capped), 5xx and timeouts with bounded backoff.
- FakeLLM: scripted responses for tests and CI (no network, no key, no quota).

Errors:
- LLMUnavailable: the provider cannot be used right now (auth, quota, outage after retries).
  Callers fall back to deterministic handling.
- LLMBadOutput: the provider answered but not with usable JSON. Callers may ask once more.
"""

import itertools
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import httpx

logger = logging.getLogger("propflow.llm")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MAX_RETRY_AFTER_SECONDS = 10.0


class LLMError(Exception):
    pass


class LLMUnavailable(LLMError):
    pass


class LLMBadOutput(LLMError):
    pass


@dataclass(frozen=True)
class LLMResult:
    content: str
    model: str
    usage: dict | None = None


class LLMClient(Protocol):
    model: str

    def complete_json(self, *, system: str, user: str, schema: dict,
                      schema_name: str) -> LLMResult: ...


class GroqClient:
    def __init__(self, api_key: str, model: str, *, base_url: str = GROQ_BASE_URL,
                 timeout: float = 30.0, max_attempts: int = 3, backoff_seconds: float = 1.0,
                 strict: bool = True, reasoning_effort: str | None = None,
                 transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not api_key or not model:
            raise LLMUnavailable("Groq API key and model are required")
        self.model = model
        self._strict = strict
        self._reasoning_effort = reasoning_effort
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._sleep = sleep
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport,
                                  headers={"Authorization": f"Bearer {api_key}"})

    def complete_json(self, *, system: str, user: str, schema: dict,
                      schema_name: str) -> LLMResult:
        body = {
            "model": self.model,
            "temperature": 0,
            "max_completion_tokens": 2048,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": schema_name, "strict": self._strict, "schema": schema}},
        }
        if self._reasoning_effort:
            body["reasoning_effort"] = self._reasoning_effort

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._http.post("/chat/completions", json=body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                error: Exception = LLMUnavailable(f"{type(exc).__name__}: {exc}")
                delay = self._backoff * 2 ** (attempt - 1)
            else:
                if response.status_code == 200:
                    return self._parse(response)
                if response.status_code in (401, 403):
                    raise LLMUnavailable(f"Groq rejected the credentials (HTTP "
                                         f"{response.status_code})")
                if response.status_code in (400, 422):
                    # Includes the model failing schema validation server-side.
                    raise LLMBadOutput(f"HTTP {response.status_code}: {response.text[:300]}")
                if response.status_code == 429 or response.status_code >= 500:
                    error = LLMUnavailable(f"HTTP {response.status_code}")
                    delay = self._retry_after(response) or self._backoff * 2 ** (attempt - 1)
                else:
                    raise LLMUnavailable(f"HTTP {response.status_code}: {response.text[:300]}")
            if attempt == self._max_attempts:
                raise error
            logger.warning("Groq call failed (attempt %d/%d), retrying in %.1fs: %s",
                           attempt, self._max_attempts, delay, error)
            self._sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("retry-after")
        try:
            return min(float(value), MAX_RETRY_AFTER_SECONDS) if value else None
        except ValueError:
            return None

    def _parse(self, response: httpx.Response) -> LLMResult:
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMBadOutput("unexpected response shape from Groq") from exc
        if not content:
            raise LLMBadOutput("empty completion")
        return LLMResult(content=content, model=data.get("model", self.model),
                         usage=data.get("usage"))


# Returned by FakeLLM when nothing is scripted: no information, zero confidence.
EMPTY_EXTRACTION = {
    "language": "en", "inquiry_type": "none", "property_type": None, "location": None,
    "bedrooms": None, "budget_min": None, "budget_max": None, "currency": None,
    "delivery_preference": None, "purchase_timeline_months": None, "purchase_intent": "unknown",
    "requests_human": False, "opt_out": False, "has_conflict": False, "conflict_note": None,
    "injection_suspected": False, "confidence": 0.0,
}


@dataclass
class FakeLLM:
    """Scripted provider. Each call consumes the next item: a dict (returned as JSON), a str
    (returned verbatim) or an exception (raised)."""

    script: list = field(default_factory=list)
    model: str = "fake"
    calls: list[dict] = field(default_factory=list)
    _ids: itertools.count = field(default_factory=itertools.count, repr=False)

    def complete_json(self, *, system: str, user: str, schema: dict,
                      schema_name: str) -> LLMResult:
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        item = self.script.pop(0) if self.script else EMPTY_EXTRACTION
        if isinstance(item, Exception):
            raise item
        content = item if isinstance(item, str) else json.dumps(item)
        return LLMResult(content=content, model=self.model)
