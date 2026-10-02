#!/usr/bin/env bash
# Create /opt/propflow/.env for the public demo with fresh random secrets.
# Asks for: the public host name, the Groq API key (hidden) and a mail-viewer password (hidden).
#   cd /opt/propflow && deploy/make-env.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ ! -f .env ] || { echo ".env already exists; move it away first to regenerate." >&2; exit 1; }

secret() { openssl rand -hex "${1:-32}"; }
read -rp "Public host name (e.g. propflow-demo.duckdns.org): " host
read -rsp "Groq API key (hidden): " groq; echo
read -rsp "Password for the mail viewer at /mail/ (hidden): " viewer; echo
[ -n "$host" ] && [ -n "$groq" ] && [ ${#viewer} -ge 10 ] \
  || { echo "host, Groq key and a mail-viewer password of 10+ characters are required" >&2; exit 1; }

hash=$(docker run --rm caddy:2.11-alpine caddy hash-password --plaintext "$viewer")
staff=$(secret 18)

python3 - "$host" "$groq" "$hash" "$staff" \
  "$(secret)" "$(secret)" "$(secret)" "$(secret)" "$(secret)" <<'PY'
import re, sys
host, groq, hash_, staff, pf_db, odoo_db, n8n_key, hmac_secret, api_key = sys.argv[1:]
values = {
    "PUBLIC_HOST": host, "GROQ_API_KEY": groq, "MAIL_VIEWER_PASSWORD_HASH": f"'{hash_}'",
    "STAFF_TOKEN": staff, "PROPFLOW_DB_PASSWORD": pf_db, "ODOO_DB_PASSWORD": odoo_db,
    "N8N_ENCRYPTION_KEY": n8n_key, "WEBHOOK_HMAC_SECRET": hmac_secret, "AI_SERVICE_API_KEY": api_key,
}
text = open(".env.production.example").read()
for key, value in values.items():
    text, n = re.subn(rf"^{key}=.*$", lambda m: f"{key}={value}", text, flags=re.M)
    assert n == 1, key
open(".env", "w").write(text)
PY
chmod 600 .env
cat <<DONE
Wrote .env (mode 600).
Share with reviewers:  https://$host  (buyer site)
                       https://$host/staff  staff token: see STAFF_TOKEN in .env
                       https://$host/mail/  user "reviewer" and the password you just typed
Keep N8N_ENCRYPTION_KEY safe: n8n credentials cannot be read without it.
DONE
