#!/usr/bin/env bash
# Load n8n/credentials/*.json and n8n/workflows/*.json into the running n8n, publish the
# workflows marked "active": true, and restart n8n so webhooks are registered.
# Files are the source of truth: re-importing overwrites workflows with the same id.
set -euo pipefail
cd "$(dirname "$0")/.."

tmp=/tmp/propflow-n8n
docker compose exec -T n8n sh -c "rm -rf $tmp && mkdir -p $tmp/credentials $tmp/workflows"
for f in n8n/credentials/*.json n8n/workflows/*.json; do
  docker compose cp "$f" "n8n:$tmp/${f#n8n/}" >/dev/null 2>&1
done
docker compose exec -T n8n n8n import:credentials --separate --input="$tmp/credentials" 2>&1 | tail -1
docker compose exec -T n8n n8n import:workflow --separate --input="$tmp/workflows" 2>&1 | tail -1

for f in n8n/workflows/*.json; do
  read -r id active < <(python3 -c 'import json,sys; w=json.load(open(sys.argv[1])); print(w["id"], w.get("active", False))' "$f")
  if [ "$active" = "True" ]; then
    docker compose exec -T n8n n8n publish:workflow --id="$id" 2>&1 | grep -v "restart n8n" | tail -1 || true
    echo "published $id"
  fi
done

docker compose restart n8n >/dev/null 2>&1
for _ in $(seq 1 30); do
  curl -sf "http://localhost:${N8N_PORT:-5678}/healthz" >/dev/null && { echo "n8n restarted"; exit 0; }
  sleep 2
done
echo "n8n did not become healthy" >&2; exit 1
