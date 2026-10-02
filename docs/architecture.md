# Architecture and decisions

See `PropFlow_AI_Project_Description.md` for scope and `IMPLEMENTATION_PLAN.md` for phasing.
This file records decisions so they are not re-litigated. Status is **Accepted** (agreed with
the project owner) or **Proposed** (a default awaiting confirmation).

## Ownership rules

- **Odoo** owns leads, contacts, stages, activities and assignment.
- **PropFlow Postgres** owns the event ledger, AI traces, score components, outbound-message
  ledger, consents, escalations, dead letters and the property catalog.
- **n8n** owns flow, not state. Anything that must survive a retry lives in Postgres or Odoo.
- **AI output never writes to Odoo or sends messages.** The LLM code path returns validated
  JSON and n8n decides what to do. CRM writes go through the service's deterministic `/v1/crm`
  endpoints (no LLM involved), which n8n calls with normalized data and a rules-based score.

## Decisions

| # | Decision | Status | Notes |
|---|---|---|---|
| 1 | LLM: **Groq, `openai/gpt-oss-120b`** (`openai/gpt-oss-20b` as fallback), behind a provider-agnostic `LLMClient` with a `fake` provider | Accepted | Both support Groq's strict JSON-schema mode. Prompts leave the machine, so synthetic data only. Confirm free-tier limits before eval runs. |
| 2 | Odoo **Community 17.0**, pinned (`ODOO_VERSION`), PostgreSQL 16 for its database | Accepted | Odoo supports only its three latest major versions, so 17 is leaving official support. Acceptable for synthetic data; reassess before any real deployment. |
| 3 | Odoo API: **JSON-RPC `/jsonrpc` `execute_kw`**, API key in place of the password | Accepted | JSON-2 does not exist in 17. Unverified against a running instance (task 0.3). All Odoo calls go through one client. |
| 4 | Scoring and property matching live in the Python service, not in n8n Code nodes | Proposed | Testable and versionable. |
| 5 | Email via SMTP, **Mailpit** in dev | Proposed | Nothing leaves the machine in dev. |
| 6 | **WhatsApp deferred**; intake is web form and email | Accepted | DB enums keep a `whatsapp` value so it can be added later without a migration. |
| 7 | Plain SQL migrations with a small runner (`app/migrate.py`) | Accepted | Immutable files, checksummed, transactional, advisory-locked. No ORM dependency. |
| 8 | Docker named volumes, ports bound to 127.0.0.1 | Accepted | The repo may live on an NTFS drive; avoid database bind mounts there. |
| 9 | Synthetic data only until security and consent requirements are met | Accepted | From the project description's non-goals. |
| 10 | **English only**; other languages go to human review | Accepted | Arabic labels stay in the dataset for later. |
| 11 | **Round-robin** assignment over active salespeople, pointer in Postgres | Accepted | Atomic pointer update, so concurrent intakes can't take the same slot. |
| 12 | Escalation is a **handoff to a salesperson**, not an approval queue | Accepted | See below. |
| 13 | The Odoo client lives in the Python service (`/v1/crm`), not in n8n nodes | Accepted | JSON-RPC errors arrive as HTTP 200 with an error body, and the search-before-create logic needs unit tests. n8n still orchestrates every step. |
| 14 | A repeat inquiry from a known contact is added to the open lead as a note and only fills its missing fields | Accepted | Never overwrites rep-edited values or downgrades the score. |

## Stack topology (docker-compose.yml)

`propflow-db` and `odoo-db` are separate Postgres instances. `migrate` is a one-shot job that
runs before `ai-service`. `n8n` waits for `ai-service` and `odoo` to be healthy.
Mailpit catches all dev mail (UI on 8025).

## Escalation: handoff to a salesperson

**Decision.** When a case needs a person, the automation does not propose an action for
someone to approve. It **hands the lead to its salesperson and stops**. The rep contacts the
customer directly, using their own judgement and Odoo's normal tools.

**Triggers** (description, Workflow G): high-priority lead, AI output that fails validation or
has low confidence, conflicting requirements, no suitable property, repeated integration
failures, the customer asks for a person, an unsupported language, a suspected prompt
injection, or an out-of-scope request (such as a rental).

**What happens:**

1. Automation for the lead stops: pending follow-ups are cancelled and nothing else is sent
   automatically. (The "salesperson takes ownership" stop condition from Workflow F.)
2. The owner (assigned round-robin) gets an Odoo activity, "Contact customer", with a deadline
   set by priority (configurable; for example 2 business hours for high priority and 1 business
   day otherwise). The lead's chatter gets the context: original inquiry, extracted fields, score
   and reasons, matched properties, recent interactions, and the handoff reason.
3. The rep gets a notification email with a link to the lead. The email has no action buttons,
   so forwarding it can't trigger anything.
4. The customer gets **one** fixed-template acknowledgement naming their salesperson, their
   business contact details, and when to expect contact. It never mentions property
   availability or prices. No acknowledgement is sent for opt-outs.
5. A scheduled n8n check finds overdue handoffs: it reminds the rep once, then notifies the sales
   manager. A handoff is never silently dropped.
6. When the rep marks the activity done, n8n records the outcome and closes the `escalations` row.

**What is still sent automatically**, and only for leads that were *not* handed off: the intake
acknowledgement, clarification questions, verified property shortlists, and follow-up reminders.
All of them are fixed, versioned templates, so the human approval happens once, when the
template is written. Anything that isn't a template is written by the salesperson.

**Why not an approval queue?** It needs a review interface (email buttons or Odoo screens), plus
handling for expiry and double clicks, just to let the system send messages that a salesperson
would write better. A handoff is less to build, more natural for the customer, and keeps
high-impact communication with people.

**Watch:** reps must actually act on handoffs. The deadline, reminder and manager escalation in
step 5 exist for that, and the reports (Phase 3) show handoff volume, reasons and time to contact.

## Open questions

See section 6 of `IMPLEMENTATION_PLAN.md`.
