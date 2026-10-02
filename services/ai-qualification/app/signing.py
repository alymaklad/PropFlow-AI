"""HMAC signatures for inbound webhooks.

The sender computes  HMAC-SHA256(secret, f"{timestamp}.{raw_body}")  and sends
  X-PropFlow-Timestamp: <unix seconds>
  X-PropFlow-Signature: sha256=<hex digest>
Signing the timestamp with the body limits replay to the allowed clock skew.
"""

import hashlib
import hmac
import time


class SignatureError(ValueError):
    pass


def sign(secret: str, timestamp: int | str, raw_body: str) -> str:
    message = f"{timestamp}.{raw_body}".encode()
    return "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str | None, signature: str | None, raw_body: str,
           max_skew_seconds: int = 300, now: float | None = None) -> None:
    if not timestamp or not signature:
        raise SignatureError("missing signature headers")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise SignatureError("malformed timestamp") from exc
    if abs((now if now is not None else time.time()) - ts) > max_skew_seconds:
        raise SignatureError("timestamp outside the allowed window")
    if not hmac.compare_digest(sign(secret, ts, raw_body), signature.strip()):
        raise SignatureError("signature mismatch")
