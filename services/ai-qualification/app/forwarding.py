"""Signed delivery of a payload to the n8n intake webhook. Used to feed email inquiries into
the same intake workflow as web forms, and to replay dead-lettered events."""

import json
import time

import httpx

from app.config import Settings
from app.signing import sign


class ForwardError(Exception):
    pass


def forward_to_intake(settings: Settings, payload: dict, *, source: str, idempotency_key: str,
                      transport: httpx.BaseTransport | None = None) -> tuple[int, dict]:
    if not settings.webhook_hmac_secret:
        raise ForwardError("webhook secret not configured")
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    ts = int(time.time())
    headers = {"Content-Type": "application/json", "X-PropFlow-Timestamp": str(ts),
               "X-PropFlow-Signature": sign(settings.webhook_hmac_secret, ts, body),
               "X-PropFlow-Source": source, "X-Idempotency-Key": idempotency_key}
    try:
        with httpx.Client(timeout=30, transport=transport) as client:
            response = client.post(settings.n8n_intake_url, content=body.encode(),
                                   headers=headers)
    except httpx.HTTPError as exc:
        raise ForwardError(f"intake webhook unreachable: {exc}") from exc
    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text[:300]}
    return response.status_code, data
