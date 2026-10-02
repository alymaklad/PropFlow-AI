# PropFlow AI: Implementation Plan

Companion to `PropFlow_AI_Project_Description.md`. The description says *what* to build. This plan says *in what order, with which decisions, and how to know each step is done*.

Effort sizes assume one developer working part-time: **S** ≈ ½–1 day, **M** ≈ 2–3 days, **L** ≈ 4–6 days. They are planning guesses, not measurements.

---

## 1. Guiding decisions

These resolve the "to be selected" items in the description so work can start. Each is cheap to change early and expensive later, so confirm them in Phase 0.

| Decision | Choice | Why |
|---|---|---|
| Odoo edition/version | **Odoo Community 17.0, pinned in Compose** (decided) | Free, self-hostable, has a custom-module story. Caveat: Odoo supports only its three latest major versions, so 17 stops receiving official security fixes as newer versions ship. Fine for a synthetic-data portfolio project; reassess before any real deployment. |
| Odoo API | **External API over JSON-RPC (`/jsonrpc`, `execute_kw`)**, authenticated with the integration user's API key in place of a password | JSON-2 does not exist in 17. XML-RPC is equivalent; JSON-RPC is easier to call from n8n's HTTP node. |
| Where scoring lives | **Python module in the FastAPI service**, called by n8n | Deterministic rules need unit tests and versioning. Code nodes in n8n are hard to test. |
| Where property matching lives | **SQL in Postgres, exposed as a service endpoint** | Same reason. n8n stays an orchestrator, not a logic host. |
| LLM access | **Groq, model `openai/gpt-oss-120b`** (decided; `openai/gpt-oss-20b` as the faster fallback), behind a provider-agnostic `LLMClient` with a `fake` implementation | Both models support Groq's strict JSON-schema mode. The free tier costs nothing. Tests and CI run against `fake`, so they need no network, keys, or quota. |
| Email | **SMTP, Mailpit in dev**, real provider only at the end | Safe by default: nothing leaves the machine in dev. |
| WhatsApp | **Deferred** (decided). Not part of Phases 0–4. | Revisit after Phase 3. The DB enums already allow a `whatsapp` channel, so adding it later needs no schema change. |
| Language | **English only** for now (decided) | Non-English inquiries are routed to human review instead of being extracted. Arabic labels stay in the dataset for later. |
| Assignment | **Round-robin** across active salespeople (decided) | Simple and fair. The pointer is stored in Postgres so it survives restarts and retries. |
| Data | **Synthetic only** until the Security section of the description is satisfied | Per the description's non-goals. |

### Source-of-truth rules (prevents most integration bugs)

- **Odoo** owns leads, contacts, stages, activities, and ownership.
- **Postgres (PropFlow schema)** owns the event ledger, idempotency keys, score components, AI traces, outbound-message ledger, consent/opt-outs, and the property catalog.
- **n8n** owns *flow*, not state. Anything that must survive a retry is in Postgres or Odoo, never in n8n variables.
- **The AI service never writes to Odoo.** It returns validated JSON, and n8n decides what to do with it. This is the main control behind "AI fields can't authorize sensitive actions."

---

## 2. Target architecture and contracts

```
Form/Email ─────────► n8n webhook ─► [claim event in Postgres] ─► FastAPI /v1/normalize
                                                                    /v1/qualify  (LangGraph)
                                                                    /v1/score    (rules)
                                                                    /v1/match    (SQL)
                                       ◄──────────────────────────────┘
                       n8n ─► Odoo (upsert lead, activity, assignment)
                       n8n ─► handoff to salesperson / follow-up scheduler ─► email
                       n8n ─► error workflow ─► alert + dead-letter row
                       Postgres reporting views ─► daily/weekly report workflow
```

### 2.1 Service API (FastAPI, all under `/v1`, `X-API-Key` required)

| Endpoint | Input | Output |
|---|---|---|
| `POST /normalize` | raw payload | normalized fields (E.164 phone, lowercased email, canonical location, budget as `min/max/currency`) plus a `validation_errors[]` list |
| `POST /qualify` | normalized inquiry text + context | `Qualification` JSON (schema in section 2.3), `confidence`, `model`, `prompt_version`, `trace_id` |
| `POST /score` | qualification + intake facts | `{total, components:[{rule, points, reason}], priority, rules_version}` |
| `POST /match` | qualification | `{matches:[…], match_status: "matched" \| "none" \| "conflict"}` (only listings verified within the freshness window) |
| `GET /healthz`, `GET /readyz` | none | liveness, and readiness (DB + LLM provider reachable) |

Every response carries the `correlation_id` it was given.

### 2.2 Postgres schema (`database/migrations/`)

Core tables (names indicative):

- `intake_events(id, idempotency_key UNIQUE, correlation_id, source, received_at, raw_payload, status, error)`: the idempotency ledger and audit copy of the original inquiry.
- `qualifications(id, event_id, model, prompt_version, raw_output, validated_output, validation_status, confidence)`: the AI trace.
- `score_results(id, event_id, rules_version, total, components JSONB, priority)`
- `properties(listing_id, type, location, price, currency, bedrooms, bathrooms, delivery_status, availability, last_verified_at, …)`
- `outbound_messages(id, lead_ref, channel, template, sequence_no, status, provider_msg_id, UNIQUE(lead_ref, template, sequence_no))`: a row is written **before** sending, which is what prevents duplicate sends on retry.
- `consents(contact_key, channel, status, updated_at, source)`: opt-in and opt-out, checked before every send.
- `escalations(id, event_id, reason, status, assigned_to, due_at, reminder_count, manager_notified_at, outcome, resolved_at)`: handoffs to a salesperson
- `dead_letters(id, workflow, correlation_id, payload, error, attempts, status)`
- Reporting views (Phase 3).

### 2.3 Qualification schema

Use the JSON in description §6B as a Pydantic model: strict types, enums for `property_type`, `delivery_preference`, `purchase_intent`, `budget_min <= budget_max`, a closed list for `missing_information`, plus `confidence` (0–1). Validation failure → one bounded repair attempt → otherwise `needs_human_review = true`. No silent coercion.

### 2.4 Odoo side

- **Custom module `propflow_crm`** adding fields to `crm.lead`: `x_correlation_id` (**unique constraint**), `x_source`, `x_original_message`, `x_property_type`, `x_location`, `x_bedrooms`, `x_budget_min/max`, `x_delivery_pref`, `x_score`, `x_score_explanation`, `x_priority`, `x_exception_status`, `x_last_contact`, `x_next_followup`.
- **Integration user** with a dedicated security group: create/read/write on `crm.lead`, `res.partner`, `mail.activity` only. API key, not a password.
- **Upsert rule:** search by `x_correlation_id` first (handles "request succeeded, response lost"), then by normalized email/phone, then create. Never create before searching.

### 2.5 Cross-cutting

- **Correlation ID** is minted at the webhook and carried in every service call, Odoo field, DB row, and log line.
- **Webhook auth:** HMAC signature header on the n8n webhook (verified in the first node), plus a timestamp to limit replay.
- **Logs:** structured JSON, with PII masked (phone and email redacted in logs; full values only in the DB).
- **Config:** everything via env vars and `.env.example`. No credentials in n8n exports (use n8n credentials by name only).

---

## 3. Phased plan

Each phase ends with a demo and exit criteria. Don't start the next phase until the exit criteria hold, because later phases assume the earlier guarantees.

### Phase 0: Foundation (≈ 1 week)

| # | Task | Size | Done when |
|---|---|---|---|
| 0.1 | Init git repo with the suggested structure from description §14, `.gitignore` (`.env`, n8n data, DB volumes), `.env.example` | S | Repo layout matches; no secrets tracked |
| 0.2 | `docker-compose.yml`: Postgres, Odoo (+ its DB), n8n, Mailpit, AI service stub. Health checks and named volumes. | M | `docker compose up` brings everything healthy from a clean checkout |
| 0.3 | Odoo bootstrap: create database, install CRM, create the integration user and API key, record the steps in a script or doc | M | A `curl` with the key can create and read a `crm.lead` |
| 0.4 | Migration tooling (Alembic or plain SQL + a runner) and the initial schema from §2.2 | M | Migrations apply on an empty DB and are re-runnable |
| 0.5 | Synthetic dataset `sample-data/synthetic-leads.json`: ~60 inquiries (English, plus Arabic/Arabizi kept for later and labeled as unsupported for now), typos, missing fields, duplicates, opt-out phrases, and a few prompt-injection attempts, each with **expected** extraction and expected score | M | Every record has ground-truth labels. This doubles as the evaluation set. |
| 0.6 | CI (GitHub Actions): lint, unit tests, migration check, `docker compose config` | S | Green pipeline on an empty-but-wired service |
| 0.7 | Confirm the decisions in §1 and write the ADR notes in `docs/architecture.md` | S | Decisions recorded |

**Phase 0 status (2026-10-02):**

| Task | Status |
|---|---|
| 0.1 Repo structure | Done |
| 0.2 Compose stack | Done: all seven services start healthy from a clean checkout |
| 0.3 Odoo bootstrap | Done: `make odoo-init` and `make odoo-bootstrap`; JSON-RPC create and read verified with the API key |
| 0.4 Migrations | Done and tested against a real Postgres 18 |
| 0.5 Synthetic dataset | Done: 60 labeled records, consistency tests passing |
| 0.6 CI | Written, has not run on GitHub yet |
| 0.7 Decisions | Done in `docs/architecture.md`; open questions remain |

### Phase 1: Deterministic MVP, no AI yet (≈ 2 weeks)

Goal: a **structured** web-form lead goes from webhook to Odoo, scored and assigned, with duplicate safety and failure visibility.

| # | Task | Size | Done when |
|---|---|---|---|
| 1.1 | `propflow_crm` Odoo module: fields, unique constraint, views, security group, tests | M | Module installs. Duplicate `x_correlation_id` is rejected by Odoo itself. |
| 1.2 | Service: `/normalize` (phone, email, location aliases, budget parsing incl. "6–8 million") with unit tests | M | Table-driven tests pass over the synthetic set |
| 1.3 | Service: `/score` with the rule set from description §6C, config-driven thresholds, `rules_version`, stored components and reasons | M | Output matches the expected scores in the dataset (this is the "scoring consistency" metric) |
| 1.4 | Odoo client in the service or n8n (pick one place) with timeout, bounded retry with backoff, error classification (transient vs permanent) | M | Fault-injection tests: timeout is retried, 4xx validation error is not |
| 1.5 | n8n **Workflow A**: webhook → HMAC check → claim `idempotency_key` → normalize → score → Odoo upsert → record status | L | Same webhook sent twice yields one lead and one ledger row |
| 1.6 | Assignment: **round-robin** over active salespeople in a configured Odoo sales team, with the pointer stored in Postgres (one atomic `UPDATE … RETURNING`, so concurrent intakes never pick the same slot twice), plus an Odoo activity "Follow up by …" | S | Leads get an owner and an activity |
| 1.7 | Notification email to the owner for high-priority leads (Mailpit) | S | Email visible in Mailpit, sent exactly once |
| 1.8 | n8n **global error workflow**: write `dead_letters`, alert email, include correlation ID | M | Forced failure produces a dead-letter row and an alert |
| 1.9 | Invalid payload path: reject with 4xx **and** ledger the attempt (nothing is silently dropped) | S | Malformed payload is visible in `intake_events` with `status=rejected` |
| 1.10 | Export workflows to `n8n/workflows/` with a script that strips credential IDs | S | Re-import works on a fresh n8n |

**Exit criteria:** Phase 1 scenarios from §4 pass (valid lead, existing lead, missing fields, duplicate webhook, CRM timeout, partial-success retry). Demo is a form post leading to an Odoo lead with a score explanation.

### Phase 2: AI qualification, matching, escalation (≈ 3 weeks)

| # | Task | Size | Done when |
|---|---|---|---|
| 2.1 | `LLMClient` interface with a **Groq provider** (via the `groq` SDK or its OpenAI-compatible endpoint), the `fake` provider, and a rate-limit/429 handler with bounded backoff. Model name and key come from env vars. Prompt files are versioned in the repo. | M | Swapping provider or model is a config change. A 429 is retried, then falls back per task 2.4. |
| 2.2 | `/qualify` as a **LangGraph** graph: `sanitize → extract → validate → (repair once) → confidence_gate → output`. Tools allowlisted and read-only (e.g. location lookup). | L | Malformed output never reaches n8n as "valid" |
| 2.3 | Prompt-injection handling: inquiry text goes in as delimited data, outputs are schema-only, no tool can write or send. Add adversarial cases to the dataset. | M | Injection cases produce a normal extraction or a human-review flag, never an action |
| 2.4 | Deterministic fallback: if the AI service is down or times out, use form fields only, set `needs_human_review`, continue the intake | M | Kill the service mid-run: the lead still lands in Odoo, flagged |
| 2.5 | Persist the AI trace (`qualifications`) and link it to the lead | S | Every lead has prompt version, raw output, and validation status |
| 2.6 | Extraction evaluation harness: run the dataset, compute per-field accuracy, write a JSON report | M | One command prints accuracy plus sample size |
| 2.7 | Property catalog: schema, seed data (synthetic), freshness rule (`last_verified_at` within N days), `/match` with filters on location, budget, bedrooms, delivery | M | Stale or unavailable listings are never returned |
| 2.8 | Match outcomes: `matched` → shortlist, `none` → ask for revised criteria or hand off to the rep, `conflict` → hand off | S | Each outcome has a scenario test |
| 2.9 | **Handoff to a salesperson** (Workflow G). When a trigger fires: (1) stop all automation for the lead and cancel pending follow-ups; (2) create an Odoo activity "Contact customer" for the owner with a deadline by priority, and put the context packet (inquiry, extraction, score reasons, matches, history, handoff reason) in the lead's chatter; (3) email the rep a notification with a link to the lead (no action buttons); (4) send the customer **one** fixed-template acknowledgement naming the rep and their business contact details; (5) a scheduled n8n check finds overdue activities: remind the rep once, then notify the sales manager; (6) when the rep marks the activity done, record the outcome. | L | Each trigger produces exactly one activity, one rep email and one customer acknowledgement (none for opt-outs). No automated message goes out after a handoff. Overdue handoffs reach the manager. |
| 2.10 | Follow-up scheduling: configurable business hours, max follow-up count, stop conditions (reply, opt-out, owner takes over). Implemented as n8n wait/schedule backed by `outbound_messages`. | L | Sequence stops correctly in each stop condition |

**Exit criteria:** every escalation trigger in description §6G is exercised by a scenario. A free-text inquiry like the New Cairo example produces the expected JSON and a verified shortlist or a safe alternative. Extraction accuracy is measured on the dataset and reported honestly.

### Phase 3: Channels, compliance, reporting, resilience (≈ 2–3 weeks)

| # | Task | Size | Done when |
|---|---|---|---|
| 3.1 | Email intake (IMAP or provider webhook) feeding the same Workflow A | M | Email inquiry yields the same lead as a form inquiry |
| 3.3 | Opt-out handling: keyword detection, plus AI flag as a *hint only*, writes `consents`, and **every send path checks consent in one shared function** | M | After opt-out, no workflow can send (tested by trying every path) |
| 3.4 | Contact limits: per-contact rate limit, max follow-ups, quiet hours | S | Limit scenarios pass |
| 3.5 | Idempotent send: insert `outbound_messages` row → send → update status. Retry after a crash does not double-send. | M | Kill-between-steps test sends exactly once |
| 3.6 | Retry policy: bounded exponential backoff, dead-letter after N, **manual replay** workflow that re-drives a dead letter by ID | M | Recoverable failures complete after replay |
| 3.7 | Reporting views and the daily/weekly n8n report: every metric from description §6H with explicit window and denominator, raw counts shown next to rates | L | Report totals reconcile with a direct Odoo and DB query (automated reconciliation test) |
| 3.8 | Workflow scenario test runner: posts synthetic events to the stack and asserts on Odoo, Postgres, and Mailpit | L | `make scenarios` runs the full §4 list |

**Exit criteria:** every success criterion in description §12 has an automated test or a documented manual check.

### Phase 4: Hardening and portfolio readiness (≈ 1–2 weeks)

| # | Task | Size |
|---|---|---|
| 4.1 | Security pass: secret scan (e.g. gitleaks) in CI, dependency audit, webhook auth review, PII-in-logs review, retention/deletion script for test data, separate dev/staging/prod env files | M |
| 4.2 | Runbooks in `docs/security-and-operations.md`: restart, replay a dead letter, rotate keys, handle an opt-out request, Odoo upgrade notes | M |
| 4.3 | Docs: `architecture.md`, `api-specification.md` (export the OpenAPI), `workflow-catalog.md`, README quick start verified on a clean machine | M |
| 4.4 | Evaluation report: run all metrics from description §9 on the synthetic set, with sample sizes and conditions | M |
| 4.5 | Demo script and recording (intake → qualify → CRM → follow-up → escalation → report) on synthetic data; workflow screenshots | M |
| 4.6 | Final repo sweep: no secrets, no personal data, CV bullets rewritten to match what shipped (per the CV accuracy note) | S |

---

## 4. Test strategy

**Layers**

1. **Unit** (pytest): normalization, scoring, matching, schema validation, consent logic, LLM-output repair. Fast and offline, using the `fake` provider.
2. **Service/API** (pytest + httpx + a test Postgres): endpoint contracts, auth, error shapes.
3. **Odoo module tests** (Odoo test framework): constraints, security group boundaries.
4. **Scenario tests** (against the Compose stack): the list below.
5. **AI evaluation:** the labeled dataset, run against the real provider on demand, never required for CI to pass.

**Scenario matrix** (maps to description §9)

| Scenario | Phase |
|---|---|
| Valid new lead | 1 |
| Existing lead by phone or email | 1 |
| Missing budget or location | 1 |
| Duplicate webhook delivery | 1 |
| CRM API timeout | 1 |
| Retry after partial success (Odoo succeeded, response lost) | 1 |
| Malformed AI output | 2 |
| AI service down (fallback) | 2 |
| Prompt-injection inquiry | 2 |
| No matching property | 2 |
| Handoff: rep notified, customer acknowledged once, automation stopped | 2 |
| Handoff not actioned by the deadline: reminder, then manager notified | 2 |
| Customer opts out | 3 |
| Messaging provider rejection | 3 |
| Crash between "record send" and "send" | 3 |

**Metrics:** compute the eight metrics from description §9 with the definitions given there. Report numerator, denominator, and sample size. Don't report anything about conversion or revenue.

---

## 5. Key risks and mitigations

| Risk | Mitigation |
|---|---|
| Odoo API drift between versions | Pin the version. Isolate all Odoo calls behind one client module/n8n sub-workflow. |
| n8n workflows become untestable spaghetti | Logic in the service, n8n only orchestrates. Small sub-workflows. Exported JSON in git. Scenario tests at the edges. |
| Duplicate leads or messages under retry | Idempotency key + unique constraints at **both** Odoo and Postgres, and "ledger before send" |
| LLM nondeterminism makes tests flaky | Fake provider in CI. Real-provider eval is a separate, report-only job. |
| Prompt injection via inquiry text | Schema-only outputs, read-only allowlisted tools, AI never writes or sends, adversarial test cases |
| Scope creep (semantic search, extra channels) | Keep semantic retrieval explicitly **out** until the deterministic baseline's metrics are reported |
| Odoo 17 leaves official support | Synthetic data only. Keep Odoo calls in one client so a later upgrade (17 → 18/19) touches one place. |
| Non-English inquiries arrive anyway | Detect language at intake and route to human review. Arabic labels are already in the dataset for when support is added. |

---

## 6. Decisions and open questions

Decided on 2026-10-02: Odoo Community 17.0; Groq with `openai/gpt-oss-120b`; English only; intake via web form and email (WhatsApp deferred); round-robin assignment; escalations are a **handoff to a salesperson** (no approval queue).

Still open:

1. **Groq free-tier limits:** confirm the current per-minute and per-day limits for `openai/gpt-oss-120b` before running the evaluation harness.

## 7. Running it for free

Every component has a free option. Free-tier limits change often, so check each provider's current terms before relying on them.

| Component | Free option | Caveat |
|---|---|---|
| n8n | Self-hosted Community Edition in Docker | Some features (e.g. SSO, advanced permissions) are paid, and none are needed here. Check the license for anything beyond internal or portfolio use. |
| Odoo | Community Edition (open source), self-hosted | No Enterprise features. The CRM and custom modules work fine. |
| FastAPI, LangGraph, Postgres, Docker, Mailpit | Open source | None |
| LLM | **Local model via Ollama** (e.g. a small Qwen or Llama instruct model), or a free API tier. **Chosen default: Groq.** | Local models need a decent CPU/GPU and extract less accurately, so measure and report accuracy honestly. Groq's free tier is rate-limited (requests and tokens per minute/day, per model), so the eval harness must throttle and the service must handle 429s. Treat all prompts as leaving your machine, which is fine for synthetic data only. Keep the key in `.env`, never in the repo or n8n exports. |
| Email | Mailpit in dev. Gmail or another SMTP account with an app password for a real-send demo. | Low daily send caps. Use synthetic recipients you own. |
| WhatsApp | Deferred. When revisited: Meta Cloud API test number or Twilio sandbox | Limited to pre-registered recipient numbers. Trial credit can run out. |
| CI | GitHub Actions on a public repo | Private repos get a limited free quota. |
| Hosting | **Run locally with Docker Compose** and record the demo. | A 24/7 public deployment is not free in general. A free cloud VM tier may fit the stack but availability varies, so don't depend on it. |

Because the `LLMClient` interface has a `fake` provider, development, CI, and every deterministic test cost nothing. Real-model evaluation is the only step that needs a model, so a local model or a free tier is enough.

## 8. Suggested first steps

1. Do tasks 0.1 → 0.2 → 0.3, so the stack runs and a manual `curl` creates an Odoo lead.
2. Do 0.5 (the synthetic dataset with expected labels) next. Everything afterward is measured against it.
3. Then begin Phase 1 with 1.2 and 1.3 (normalize and score). They are pure logic with no integrations, so you get tested code quickly.
