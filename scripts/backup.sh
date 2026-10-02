#!/usr/bin/env bash
# Nightly backup: both databases and the n8n and Odoo data volumes, kept for 7 days.
# Optional: HEALTHCHECK_URL in .env (Healthchecks.io) is pinged on success, so a silent
# failure raises an alert. Copy /opt/propflow-backups off the server from time to time.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

dest="${BACKUP_DIR:-/opt/propflow-backups}/$(date +%Y%m%d-%H%M)"
mkdir -p "$dest"
docker compose exec -T propflow-db pg_dump -U "${PROPFLOW_DB_USER:-propflow}" -Fc \
  "${PROPFLOW_DB_NAME:-propflow}" > "$dest/propflow.dump"
docker compose exec -T odoo-db pg_dump -U "${ODOO_DB_USER:-odoo}" -Fc \
  "${ODOO_DB_NAME:-propflow_odoo}" > "$dest/odoo.dump"
for volume in n8n_data odoo_web_data; do
  docker run --rm -v "propflow_${volume}:/data:ro" -v "$dest:/backup" alpine \
    tar czf "/backup/${volume}.tgz" -C /data .
done
find "$(dirname "$dest")" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +
echo "$(date -Is) backup ok: $dest ($(du -sh "$dest" | cut -f1))"
[ -n "${HEALTHCHECK_URL:-}" ] && curl -fsS -m 10 --retry 3 "$HEALTHCHECK_URL" >/dev/null || true
