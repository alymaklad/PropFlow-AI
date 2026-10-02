#!/usr/bin/env bash
# Export workflows edited in the n8n UI back into n8n/workflows/ (only "PropFlow" workflows).
# Volatile fields (timestamps, version ids, instance metadata, pinned test data) are dropped
# so diffs stay readable. Credentials are referenced by id and name only; n8n never exports
# their secrets here.
set -euo pipefail
cd "$(dirname "$0")/.."

tmp=/tmp/propflow-n8n-export
docker compose exec -T n8n sh -c "rm -rf $tmp && mkdir -p $tmp && n8n export:workflow --all --separate --output=$tmp >/dev/null"
rm -rf .n8n-export && mkdir .n8n-export
docker compose cp "n8n:$tmp/." .n8n-export/ >/dev/null 2>&1
python3 - <<'PY'
import json, pathlib, re
KEEP = ("id", "name", "active", "nodes", "connections", "settings")
out = pathlib.Path("n8n/workflows")
existing = {json.loads(p.read_text())["id"]: p for p in out.glob("*.json")}
for src in sorted(pathlib.Path(".n8n-export").glob("*.json")):
    wf = json.loads(src.read_text())
    if not wf.get("name", "").startswith("PropFlow"):
        continue
    clean = {k: wf[k] for k in KEEP if k in wf}
    target = existing.get(wf["id"]) or out / (re.sub(r"[^a-z0-9]+", "-", wf["name"].lower()).strip("-") + ".json")
    target.write_text(json.dumps(clean, indent=2, ensure_ascii=False) + "\n")
    print(f"exported {wf['name']} -> {target}")
PY
rm -rf .n8n-export
