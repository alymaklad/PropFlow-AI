#!/usr/bin/env python3
"""Send a signed test lead to the n8n intake webhook (stdlib only).

Usage:
  python3 scripts/send_lead.py '{"name": "Test", "email": "t@example.com", "message": "hi"}'
  python3 scripts/send_lead.py --file lead.json [--event-id evt-1] [--bad-signature]

Reads WEBHOOK_HMAC_SECRET (and N8N_PORT) from the environment or from .env.
"""

import argparse
import hashlib
import hmac
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_env() -> None:
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def send(body: str, *, event_id: str | None = None, bad_signature: bool = False,
         url: str | None = None) -> tuple[int, dict]:
    secret = os.environ["WEBHOOK_HMAC_SECRET"]
    url = url or f"http://localhost:{os.environ.get('N8N_PORT', '5678')}/webhook/propflow/intake"
    ts = str(int(time.time()))
    digest = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-PropFlow-Timestamp": ts,
               "X-PropFlow-Signature": "sha256=" + ("0" * 64 if bad_signature else digest)}
    if event_id:
        headers["X-Idempotency-Key"] = event_id
    req = urllib.request.Request(url, body.encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw)
        except ValueError:
            return err.code, {"raw": raw.decode(errors="replace")[:500]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("payload", nargs="?", help="JSON payload")
    parser.add_argument("--file", help="read the payload from a file")
    parser.add_argument("--event-id", help="sent as X-Idempotency-Key")
    parser.add_argument("--bad-signature", action="store_true", help="send a wrong signature")
    args = parser.parse_args()
    load_env()
    body = pathlib.Path(args.file).read_text() if args.file else args.payload
    if not body:
        parser.error("give a payload or --file")
    status, response = send(body, event_id=args.event_id, bad_signature=args.bad_signature)
    print(status, json.dumps(response))
    return 0 if status < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
