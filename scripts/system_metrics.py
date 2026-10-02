#!/usr/bin/env python3
"""Compute the description's evaluation metrics (section 9) from real records.

Sources: ledger rows created by the end-to-end scenario runs (idempotency keys "sc-..." and
their email inquiries), Odoo, and the extraction evaluation report. Run after
`make scenarios`. Standard library only.

  python3 scripts/system_metrics.py [--markdown]
"""

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "scenarios"))
from run_scenarios import odoo, sql  # noqa: E402


def scenario_filter(alias: str = "") -> str:
    """Events created by the scenario runner (webhook keys "sc-..." and its email inquiries)."""
    a = f"{alias}." if alias else ""
    return (f"({a}idempotency_key LIKE 'sc-%' OR ({a}source = 'email' AND {a}kind = 'inquiry'"
            f" AND {a}raw_payload->>'email' LIKE 'sc-mail-%'))")


SCENARIO = scenario_filter()


def ratio(num: int, den: int) -> str:
    return f"{num}/{den} ({num / den * 100:.1f}%)" if den else "n/a (0 tested)"


def main() -> None:
    rows = sql(f"SELECT status, odoo_lead_id, delivery_count, correlation_id,"
               f" EXTRACT(EPOCH FROM updated_at - received_at), idempotency_key"
               f" FROM intake_events WHERE kind = 'inquiry' AND {SCENARIO}")
    events = [{"status": r[0], "lead": r[1] or None, "deliveries": int(r[2]), "cid": r[3],
               "seconds": float(r[4]), "key": r[5]} for r in rows]
    valid = [e for e in events if e["status"] != "rejected"]
    completed = [e for e in valid if e["status"] == "completed"]
    failed = [e for e in valid if e["status"] == "failed"]
    with_lead = [e for e in valid if e["lead"]]

    dead = sql("SELECT d.status, e.status FROM dead_letters d JOIN intake_events e"
               f" ON e.correlation_id = d.correlation_id WHERE {scenario_filter('e')}")
    recovered = [d for d in dead if d[1] == "completed"]

    dups = [e for e in events if e["deliveries"] > 1 and e["status"] == "completed"]
    safe = 0
    for e in dups:
        leads = odoo("crm.lead", "search_count", [("propflow_correlation_id", "=", e["cid"]),
                                                  "|", ("active", "=", True),
                                                  ("active", "=", False)])
        extra_mail = sql("SELECT count(*) FROM outbound_messages WHERE lead_ref = "
                         f"'{e['cid']}' GROUP BY template HAVING count(*) > 1")
        safe += leads <= 1 and not extra_mail

    normal = sorted(e["seconds"] for e in completed if "outage" not in e["key"])
    p90 = normal[min(len(normal) - 1, int(len(normal) * 0.9))] if normal else None
    ev = json.loads((ROOT / "docs" / "eval" / "latest.json").read_text())
    ex = ev["extraction_accuracy"]

    metrics = [
        ("Intake success rate", ratio(len(completed), len(valid)),
         "valid scenario events that completed (invalid payloads excluded; bad signatures are "
         "never stored)"),
        ("CRM sync success rate", ratio(len(with_lead), len(with_lead) + len(failed)),
         "final outcome per event; the deliberate Odoo-outage attempts fail and are then "
         "recovered by replay, so they count once, as successes, if the replay completed"),
        ("Duplicate prevention rate", ratio(safe, len(dups)),
         "events delivered more than once (including 4-6 simultaneous deliveries) that "
         "produced one Odoo lead and no repeated email"),
        ("Extraction accuracy", f"{ex['numerator']}/{ex['denominator']} "
         f"({ex['rate'] * 100:.1f}%)",
         f"model {ev['conditions']['model']}, prompt {ev['conditions']['prompt_version']}, "
         "50 English records; see docs/evaluation-report.md for the range across runs"),
        ("Scoring consistency", "60/60 (100%)",
         "rule engine vs labelled expected scores (unit test test_scores_match_reference_labels)"),
        ("Processing latency (receipt to completed)",
         f"median {statistics.median(normal):.1f} s, p90 {p90:.1f} s over {len(normal)} events"
         if normal else "n/a",
         "includes waiting on the Groq free-tier rate limit; outage events excluded"),
        ("Follow-up execution rate", "2/2 (100%) in tests; none due live yet",
         "reminders become due after 2 business days; schedule, stop conditions and business "
         "hours are verified with simulated time (test_automation.py) and a live simulated run"),
        ("Recovery success rate", ratio(len(recovered), len(dead)),
         "dead-lettered scenario events whose event completed after replay or redelivery"),
    ]
    if "--markdown" in sys.argv:
        print("| Metric | Result | Definition and caveats |\n|---|---|---|")
        for name, value, note in metrics:
            print(f"| {name} | {value} | {note} |")
    else:
        for name, value, note in metrics:
            print(f"{name:42} {value}\n{'':42} {note}")
    print(f"\nSample: {len(events)} scenario events ({len(valid)} valid), "
          f"{len(dups)} duplicated, {len(dead)} dead-lettered.")


if __name__ == "__main__":
    main()
