#!/usr/bin/env bash
# Create/refresh the Odoo integration user and write its API key into .env (never printed).
# Re-running rotates the key. Requires the stack to be up and scripts/odoo-init.sh to have run.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; source .env; set +a
DB="${ODOO_DB_NAME:-propflow_odoo}"
LOGIN="${ODOO_INTEGRATION_LOGIN:-propflow-integration}"

out=$(docker compose exec -T -e PROPFLOW_INTEGRATION_LOGIN="$LOGIN" odoo sh -c \
  'odoo shell --no-http --db_host "$HOST" --db_user "$USER" --db_password "$PASSWORD" -d "$0" --log-level=warn' \
  "$DB" < odoo/bootstrap/create_integration_user.py)

key=$(printf '%s\n' "$out" | sed -n 's/^PROPFLOW_API_KEY=//p' | tail -1)
uid=$(printf '%s\n' "$out" | sed -n 's/^PROPFLOW_UID=//p' | tail -1)
if [ -z "$key" ]; then
  echo "bootstrap failed; Odoo output follows:" >&2
  printf '%s\n' "$out" | grep -v '^PROPFLOW_API_KEY=' >&2
  exit 1
fi

KEY="$key" python3 - <<'PY'
import os, re
p = ".env"
s = open(p).read()
s, n = re.subn(r"^ODOO_API_KEY=.*$", "ODOO_API_KEY=" + os.environ["KEY"], s, flags=re.M)
if n == 0:
    s += "\nODOO_API_KEY=" + os.environ["KEY"] + "\n"
open(p, "w").write(s)
PY
echo "Integration user '$LOGIN' (uid $uid) ready; API key written to .env."
echo "Restart n8n to pick it up: docker compose up -d n8n"
