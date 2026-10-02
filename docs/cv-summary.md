# CV summary (what was actually built)

Replaces the planned bullets in the project description, as its accuracy note asks. Every
claim below is implemented, tested and documented in this repository; measured figures come
from `docs/evaluation-report.md` (synthetic data, small samples).

**PropFlow AI | Real-estate lead automation (n8n, Odoo, FastAPI, LangGraph, PostgreSQL)**

- Built an n8n-orchestrated lead pipeline (web form and email) that qualifies inquiries with a
  LangGraph workflow on Groq, scores them with versioned rules, assigns owners round-robin in
  Odoo 17 through a least-privilege custom module, and matches verified property listings.
- Engineered reliability end to end: HMAC-signed webhooks, an idempotent event ledger,
  duplicate-safe CRM upserts, at-most-once email delivery, bounded retries, dead letters with
  replay, and 12 automated end-to-end scenarios including concurrent duplicates and a CRM
  outage (100% duplicate prevention and recovery in those runs).
- Kept humans in control: schema-validated AI output that never triggers actions, prompt-
  injection controls, handoffs to salespeople with business-hours deadlines and escalation,
  consent and opt-out handling, contact limits, and data-erasure and retention operations.
- Evaluated the AI on a labelled synthetic set (98.2-99.3% field accuracy across runs, 100%
  recall on cases needing a person), and documented the method, label changes and limits.
- Delivered daily and weekly operational reports with explicit denominators, a React buyer site
  and staff dashboard, runbooks, and CI with tests, secret scanning and dependency audits.

Interview notes: the most interesting bugs were found by the scenario runner (a concurrent
delivery treating its own new lead as a known contact) and by real data (emails sent before a
schema change breaking a report). Be ready to explain the handoff-instead-of-approval decision
and why the evaluation reports a range instead of the best run.
