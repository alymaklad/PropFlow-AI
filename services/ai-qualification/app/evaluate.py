"""Extraction evaluation harness (task 2.6).

Runs the labeled dataset through the qualification graph and reports per-field accuracy and
decision metrics, with sample size and conditions. Intended to run inside the service
container against the configured provider:

  docker compose exec -T ai-service python -m app.evaluate --delay 15 \
      < sample-data/synthetic-leads.json > docs/eval/latest.json

Field accuracy is exact match on English records only, skipping each record's `skip_fields`.
Every record counts for the decision metrics (review, opt-out, language routing).
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime

from app.config import load_settings
from app.llm import LLMClient
from app.qualification import PROMPT_VERSION, qualify

FIELDS = ("property_type", "location", "bedrooms", "budget_min", "budget_max", "currency",
          "delivery_preference", "purchase_timeline_months", "purchase_intent")


def _ratio(num: int, den: int) -> dict:
    return {"numerator": num, "denominator": den, "rate": round(num / den, 4) if den else None}


def evaluate(records: list[dict], llm: LLMClient, *, min_confidence: float = 0.6,
             delay: float = 0.0, sleep=time.sleep, clock=time.monotonic) -> dict:
    per_field = {f: [0, 0] for f in FIELDS}
    review = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    opt_out = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    injection_hits = injection_total = 0
    language_ok = language_total = 0
    statuses: dict[str, int] = {}
    latencies: list[float] = []
    mismatches: list[dict] = []
    decision_mismatches: list[dict] = []

    for i, record in enumerate(records):
        if i and delay:
            sleep(delay)
        labels = record["expected"]["extraction"]
        started = clock()
        result = qualify(llm, record["payload"].get("message"), min_confidence)
        latencies.append(clock() - started)
        statuses[result.status] = statuses.get(result.status, 0) + 1

        for name, predicted, actual in (
            ("review", result.needs_human_review, labels["needs_human_review"]),
            ("opt_out", result.opt_out, labels["opt_out"]),
        ):
            bucket = review if name == "review" else opt_out
            key = ("t" if predicted == actual else "f") + ("p" if predicted else "n")
            bucket[key] += 1
        if (result.needs_human_review != labels["needs_human_review"]
                or result.opt_out != labels["opt_out"]):
            decision_mismatches.append({
                "id": record["id"], "expected_review": labels["needs_human_review"],
                "got_review": result.needs_human_review, "reasons": result.reasons,
                "expected_opt_out": labels["opt_out"], "got_opt_out": result.opt_out})
        if labels["injection_attempt"]:
            injection_total += 1
            injection_hits += "injection_suspected" in result.reasons
        if record["language"] != "en":
            language_total += 1
            language_ok += "unsupported_language" in result.reasons
            continue

        extraction = result.extraction or {}
        for f in FIELDS:
            if f in labels["skip_fields"]:
                continue
            per_field[f][1] += 1
            if extraction.get(f) == labels[f]:
                per_field[f][0] += 1
            else:
                mismatches.append({"id": record["id"], "field": f, "expected": labels[f],
                                   "got": extraction.get(f)})

    def prf(b: dict) -> dict:
        precision = b["tp"] / (b["tp"] + b["fp"]) if b["tp"] + b["fp"] else None
        recall = b["tp"] / (b["tp"] + b["fn"]) if b["tp"] + b["fn"] else None
        accuracy = (b["tp"] + b["tn"]) / sum(b.values()) if sum(b.values()) else None
        return {**b, "precision": precision and round(precision, 4),
                "recall": recall and round(recall, 4), "accuracy": accuracy and round(accuracy, 4)}

    correct = sum(c for c, _ in per_field.values())
    evaluated = sum(t for _, t in per_field.values())
    latencies.sort()
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "conditions": {
            "model": getattr(llm, "model", "unknown"), "prompt_version": PROMPT_VERSION,
            "min_confidence": min_confidence, "records": len(records),
            "english_records": len(records) - language_total, "delay_seconds": delay,
            "dataset": "sample-data/synthetic-leads.json (synthetic, labeled)",
        },
        "extraction_accuracy": _ratio(correct, evaluated),
        "field_accuracy": {f: _ratio(c, t) for f, (c, t) in per_field.items()},
        "review_decision": prf(review),
        "opt_out_detection": prf(opt_out),
        "injection_detection": _ratio(injection_hits, injection_total),
        "non_english_routed_to_review": _ratio(language_ok, language_total),
        "statuses": statuses,
        "latency_seconds": {
            "median": round(latencies[len(latencies) // 2], 3) if latencies else None,
            "p90": round(latencies[int(len(latencies) * 0.9)], 3) if latencies else None,
        },
        "mismatches": mismatches,
        "decision_mismatches": decision_mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate extraction on the labeled dataset")
    parser.add_argument("--delay", type=float, default=15,
                        help="seconds between records (stay under provider rate limits)")
    parser.add_argument("--limit", type=int, help="only the first N records")
    args = parser.parse_args()

    from app.deps import _llm  # built the same way as in the API
    settings = load_settings()
    llm = _llm(settings.llm_provider, settings.groq_api_key, settings.groq_model,
               settings.groq_strict, settings.groq_reasoning_effort, settings.groq_max_attempts,
               settings.groq_max_retry_wait)
    records = json.load(sys.stdin)["records"][: args.limit]
    report = evaluate(records, llm, min_confidence=settings.qualify_min_confidence,
                      delay=args.delay)
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    if report["statuses"].get("fallback") == len(records):
        print("warning: every record fell back; is the provider configured?", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
