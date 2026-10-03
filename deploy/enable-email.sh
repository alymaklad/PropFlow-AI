#!/usr/bin/env bash
# Turn real email delivery on (or off) for the public demo.
#   cd /opt/propflow && deploy/enable-email.sh            # asks for a Gmail address + App Password
#   cd /opt/propflow && deploy/enable-email.sh --disable  # back to capture-only
#
# Customer emails then reach the visitor through that account; Mailpit keeps a copy of every
# email for /mail/ and never relays to the fictional staff and test domains. In this mode the
# customer emails carry a demo notice instead of the STOP line and no reminders are sent.
# The App Password is checked against Gmail before it is saved in .env (mode 600).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo ".env missing: run deploy/make-env.sh first" >&2; exit 1; }

set_env() {
  python3 - "$@" <<'PY'
import re, sys
pairs = dict(zip(sys.argv[1::2], sys.argv[2::2]))
text = open(".env").read()
for key, value in pairs.items():
    text, n = re.subn(rf"^{key}=.*$", lambda m: f"{key}={value}", text, flags=re.M)
    if n == 0:
        text = text.rstrip("\n") + f"\n{key}={value}\n"
open(".env", "w").write(text)
PY
  chmod 600 .env
}

if [ "${1:-}" = "--disable" ]; then
  set_env MAIL_RELAY_ENABLED false MAIL_RELAY_PASSWORD "" NOTIFY_FROM_EMAIL propflow-noreply@example.com
else
  read -rp "Gmail address that sends the emails: " address
  read -rsp "App Password for it (hidden; spaces are fine): " password; echo
  password=${password// /}
  [[ "$address" == *@* && ${#password} -ge 16 ]] \
    || { echo "need an email address and the 16-character App Password" >&2; exit 1; }
  echo "Checking the login with smtp.gmail.com..."
  MAIL_USER="$address" MAIL_PASS="$password" python3 - <<'PY'
import os, smtplib, ssl, sys
try:
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(os.environ["MAIL_USER"], os.environ["MAIL_PASS"])
except smtplib.SMTPAuthenticationError:
    sys.exit("Gmail refused the login: check the address and create a new App Password "
             "(2-Step Verification must be on).")
except OSError as exc:
    sys.exit(f"Could not reach smtp.gmail.com: {exc}")
print("Login OK.")
PY
  set_env MAIL_RELAY_ENABLED true MAIL_RELAY_HOST smtp.gmail.com MAIL_RELAY_PORT 587 \
    MAIL_RELAY_USERNAME "$address" MAIL_RELAY_PASSWORD "$password" NOTIFY_FROM_EMAIL "$address"
fi

docker compose up -d mailpit ai-service n8n
echo "Done. Real delivery is now $(grep '^MAIL_RELAY_ENABLED=' .env | cut -d= -f2)."
