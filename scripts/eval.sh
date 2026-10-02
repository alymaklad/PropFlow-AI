#!/usr/bin/env bash
# Run the extraction evaluation against the configured provider (needs GROQ_API_KEY and
# LLM_PROVIDER=groq in .env). Writes docs/eval/<model>-<date>.json and docs/eval/latest.json.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
[ "${LLM_PROVIDER:-none}" = "groq" ] && [ -n "${GROQ_API_KEY:-}" ] || {
  echo "Set LLM_PROVIDER=groq and GROQ_API_KEY in .env, then: docker compose up -d ai-service" >&2
  exit 2
}
out="docs/eval/$(echo "${GROQ_MODEL:-model}" | tr '/:' '--')-$(date +%Y%m%d-%H%M).json"
docker compose exec -T ai-service python -m app.evaluate --delay "${EVAL_DELAY:-2.5}" "$@" \
  < sample-data/synthetic-leads.json > "$out"
cp "$out" docs/eval/latest.json
python3 - "$out" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
c = r["conditions"]
print(f"model {c['model']} | prompt {c['prompt_version']} | {c['records']} records "
      f"({c['english_records']} English)")
print("extraction accuracy:", r["extraction_accuracy"])
for f, v in r["field_accuracy"].items():
    print(f"  {f:26} {v['numerator']}/{v['denominator']}")
print("review decision:", {k: r["review_decision"][k] for k in ("precision", "recall", "accuracy")})
print("opt-out detection:", {k: r["opt_out_detection"][k] for k in ("precision", "recall")})
print("injection detection:", r["injection_detection"])
print("non-English routed:", r["non_english_routed_to_review"])
print("statuses:", r["statuses"], "| latency:", r["latency_seconds"])
PY
echo "report: $out"
