# API specification

The AI qualification service runs at `http://ai-service:8000` inside the stack and
`http://localhost:8000` from the host. The interactive OpenAPI docs are at `/docs`.

## Conventions

- Every `/v1` call needs `X-API-Key: $AI_SERVICE_API_KEY`. A missing or wrong key returns `401`.
  If the service has no key configured, it rejects everything.
- Send `X-Correlation-ID` (minted by the n8n webhook). It is echoed on the response. If it is
  absent or malformed, the service generates a UUID.
- Request bodies are JSON. Unknown fields are ignored. Wrong types return `422`.

## Intake payload (web form)

This is what the n8n webhook receives and passes to `/v1/normalize`. Only a contact (phone or
email) and some content (a message or any structured field) are required.

| Field | Type | Notes |
|---|---|---|
| `source` | `form` \| `email` \| `manual` | Default `form` |
| `name` | string | |
| `phone` | string | Any common format; Egyptian numbers without a country code are assumed |
| `email` | string | |
| `message` | string | Free text, kept verbatim for audit (truncated at 5,000 characters) |
| `property_type` | string | `apartment`, `villa`, `townhouse`, `duplex`, `penthouse`, `studio`, `chalet`, `land`, `commercial`, `office`, or a known alias |
| `location` | string | Canonicalized (e.g. "Fifth Settlement" becomes `New Cairo`) |
| `bedrooms` | int \| string | `"studio"` becomes 0 |
| `budget` | string \| number | Free text such as `"6-8 million"`, `"up to 15M"`, `"USD 150,000"` |
| `budget_min`, `budget_max`, `currency` | number/string, string | Use instead of `budget` when the form has separate fields |
| `timeline` | string \| int | `immediately`, `within_3_months`, `3_6_months`, `6_12_months`, `over_12_months`, or months as a number |
| `purchase_stage` | string | `ready_to_buy` (high intent), `comparing_options` (medium), `just_browsing` (low) |

## `POST /v1/normalize`

Always returns `200`. An unusable lead comes back with `valid: false`, so the workflow can
record the rejection instead of dropping it.

Response fields: the normalized values above plus `contact_key` (E.164 phone, else email),
`location_raw`, `purchase_timeline_months`, `purchase_intent`, and three code lists:

| List | Meaning | Codes |
|---|---|---|
| `errors` | Lead is invalid (`valid: false`) | `contact_missing`, `content_missing` |
| `warnings` | A field was unusable and left empty; the lead continues | `name_missing`, `phone_invalid`, `email_invalid`, `message_truncated`, `property_type_unrecognized`, `location_unrecognized`, `bedrooms_invalid`, `budget_unparseable`, `budget_ambiguous_unit`, `timeline_invalid`, `purchase_stage_invalid` |
| `conflicts` | Contradictory input: hand off to a salesperson | `studio_with_bedrooms`, `budget_min_gt_max` |

## `POST /v1/score`

Input: `budget_min`, `budget_max`, `purchase_timeline_months`, `property_type`, `location`,
`bedrooms`, `purchase_intent` (`high`/`medium`/`low`/`unknown`), `responded_to_followup`.

Output: `total` (0–100), `priority` (`high` ≥ 80, `standard` ≥ 50, otherwise `nurture`),
`rules_version`, and `components`: one entry per rule with `rule`, `points` and a
human-readable `reason`. Rules live in `app/data/scoring_rules.json`. Changing points or
thresholds requires a new `version`.

## Webhook signing

Senders sign every request to the n8n webhook:

```
X-PropFlow-Timestamp: <unix seconds>
X-PropFlow-Signature: sha256=<hex HMAC-SHA256(WEBHOOK_HMAC_SECRET, "<timestamp>.<raw body>")>
X-Idempotency-Key: <optional sender event id>
```

The timestamp must be within 5 minutes of the service clock. `scripts/send_lead.py` is a
reference implementation.

## `POST /v1/intake/receive`

Used by the n8n webhook. Body: `raw_body` (the exact bytes received, as text), `timestamp`,
`signature`, optional `idempotency_key`, `source`. Verifies the signature, parses the body and
claims the event (as `/claim` below), returning the claim fields plus `payload`.
`401`: missing or invalid signature (not stored). `422`: signed but not a JSON object (stored
as `rejected` with error `malformed_json`). `503`: no webhook secret configured.

## `POST /v1/qualify`

AI qualification of the free-text message (LangGraph: sanitize, extract, validate, one repair,
read-only lookups, review gate). Body: `correlation_id`, optional `event_id` (enables the trace
row in `qualifications`), `lead` (a `/v1/normalize` response). Always `200`; returns data only.

| Field | Meaning |
|---|---|
| `status` | `valid`, `repaired` (second attempt), `invalid` (still invalid after repair), `fallback` (provider unavailable or AI off), `skipped` (no message), `unsupported_language` (Arabic script: no model call) |
| `needs_human_review` / `reasons` | Hand the lead to a salesperson when any reason is present: `injection_suspected`, `conflicting_requirements`, `customer_requested_human`, `unsupported_language`, `out_of_scope_rental`, `low_confidence`, `ai_unavailable`, `ai_output_invalid` |
| `opt_out` | The customer asked to stop contact (keyword detection backs up the model) |
| `extraction` | Validated model output, or `null` |
| `lead` | The input lead with gaps filled from the extraction. Form values always win; an extraction from an unsupported language is not used. Feed this to `/v1/score` |

With `LLM_PROVIDER=none` (no Groq key) every message gets `fallback` and goes to a salesperson.

## `POST /v1/match`

Body: `correlation_id`, optional `event_id`, `lead`. Returns `status` (`matched`, `none`,
`insufficient_criteria` with `missing`, `conflict`) and up to 5 `matches`. Only listings that
are `available` and verified within 14 days are returned; price may be up to 5% above the
stated maximum; currency must match. Each call is recorded in `match_results`.

## `POST /v1/actions/next`

The intake workflow's single post-upsert call. Body: `event_id`, `correlation_id`, `lead`
(merged), `qualification`, `score`, `upsert`, `match`, optional `now`. Returns `route`,
`reasons`, `messages` and `due_at` (handoffs only).

| Route | When | What happens |
|---|---|---|
| `handoff` | Any qualification reason, conflicting requirements, or no matching property | `/v1/handoffs` (below) |
| `shortlist` | Listings matched and the customer has an email | Shortlist email, rep follow-up activity, reminders |
| `clarify` | No location or budget | Clarification email, rep follow-up activity, reminders |
| `rep_only` | No customer email | Rep follow-up activity only |

If the AI failed but the form already has a location and a budget, the lead continues
automatically instead of being handed off. High-priority leads also email the owner.

`messages` items: `kind` (`rep`, `customer`, `manager`), `send`, `message_id`, `to`, `subject`,
`text`, `reason` when not sendable (`opted_out`, `rate_limited`, `already_sent`, `pending`,
`no_email`, `no_owner`, `no_manager`). Customer emails are limited to
`MAX_CUSTOMER_EMAILS_PER_DAY` (default 3) per address per 24 hours; retries of an already
claimed message are not counted. Send only `send: true` items, then report on
`/v1/outbound/{message_id}/status`.

## Handoffs and follow-ups

- `POST /v1/route`: the routing decision alone (no side effects).
- `POST /v1/handoffs`: pause automation on the lead, set a contact deadline (high priority: 2
  business hours, otherwise next business day), create the owner's "PropFlow handoff" activity
  (or the team manager's if there is no owner), post a context note, stop reminders. Returns
  the rep notification and one customer acknowledgement. Idempotent per event.
- `POST /v1/handoffs/check`: resolve handoffs whose activity is done; after the deadline remind
  the owner once, then notify the team manager (or return `no_manager`).
- `POST /v1/followups/start` / `POST /v1/followups/due`: customer reminders (first after 2
  business days, then 3, at most 2), stopped by opt-out, paused automation, handoff, conversion
  to an opportunity, a won or closed lead.

All accept an optional `now` (ISO datetime) for tests and replays. Messages are only produced
during business hours (`BUSINESS_TZ`, `BUSINESS_HOURS`, `BUSINESS_DAYS`).

## `POST /v1/reports/summary`

Body: `period` (`day` or `week`), optional `end` (defaults to now). Returns `subject`, plain
`text` and the structured `report`: inquiries by source and outcome, intake success rate
(completed / valid), CRM actions and sync success rate, priority distribution and qualified
rate, AI outcomes, first-response time (median and average over leads whose first customer
email was sent), match outcomes, reminder sequences by outcome, reminders sent, customer
replies, overdue PropFlow activities in Odoo, handoffs by reason and escalation, dead letters,
and workload per salesperson. Every rate carries its numerator and denominator. If Odoo is
unreachable, the Odoo sections are marked unavailable and the rest is still returned.

## `POST /v1/messages/prepare` and `POST /v1/consents`

`prepare` is the single path for customer messages: consent check (email address or phone),
render a fixed template (`customer_shortlist`, `customer_clarification`, `customer_handoff_ack`,
`customer_reminder`), claim it in the outbound ledger. `consents` records `opted_in` /
`opted_out` for every key of a contact; an opt-out also stops active reminders.

## `POST /v1/intake/claim`

Records an inbound event in the ledger exactly once. Body: `source`, `raw_payload` (the
webhook body) and optionally `idempotency_key` (the sender's event id). Without a key, one is
derived from a hash of `source` and the canonical payload.

Returns `event_id`, `correlation_id` (carry it through every later call), `duplicate`,
`delivery_count`, `status`, `odoo_lead_id` and **`proceed`**. `proceed` is false when an
earlier delivery already completed or was rejected: acknowledge and stop. A redelivery of an
event that failed or is still processing returns `proceed: true`, and every later step is
idempotent.

## `POST /v1/intake/{event_id}/status`

Body: `status` (`completed`, `rejected` or `failed`), optional `error`, optional
`odoo_lead_id`. Returns `404` for an unknown event.

## `POST /v1/crm/leads/upsert`

Body: `correlation_id`, `event_id`, `lead` (a `/v1/normalize` response with `valid: true`),
`score` (a `/v1/score` response), optional `exception_status` (`none`, `handoff`,
`sync_error`). Returns `lead_id`, `action`, `user_id`, `team_id` and `warnings`.

| `action` | When | Effect |
|---|---|---|
| `created` | No lead with this correlation id or contact | New lead, owner assigned round-robin from the configured team |
| `updated` | A lead with this correlation id exists (a retry) | Lead fields and score replaced with this request's values |
| `matched_contact` | An open lead has the same phone or email | New inquiry posted as a note. Only *missing* requirement fields are filled; existing values, score and owner are kept |

Warning `no_salespeople`: the team has no active members, so the lead was created unassigned.
Errors: `422` if the lead is invalid, `503` if Odoo is unavailable (safe to retry; has
`Retry-After`), `502` if Odoo rejected the request (do not retry; alert).

## `POST /v1/crm/leads/{lead_id}/followup`

Body: `user_id` (the owner; `null` returns `scheduled: false` with warning `no_owner`) and
`priority`. Schedules one "PropFlow follow-up" To-Do for the owner (repeat calls return the
same activity) and sets the lead's next follow-up date. Due date by priority, in business
days (Sunday to Thursday): high is the same day, standard +1, nurture +3.

## `POST /v1/outbound/claim` and `POST /v1/outbound/{message_id}/status`

The "record before send" ledger. Claim with `lead_ref`, `channel`, `template` and
`sequence_no`; send only if the response says `send: true`, then report `sent` (with
`provider_msg_id`), `failed` or `cancelled`. A failed message may be claimed again; a message
left `pending` by a crash mid-send is never resent automatically (it may have gone out), so
delivery is at most once.

## Dead letters

- `POST /v1/dead-letters`: record a failed run (`workflow`, `error`, optional `correlation_id`,
  `payload`). Returns `201` with the id.
- `GET /v1/dead-letters?status_filter=open`: list (open, replayed or discarded).
- `POST /v1/dead-letters/{id}/replay`: re-drive the original event through the intake webhook,
  signed, with its original idempotency key (a partly processed event resumes instead of
  duplicating). `409` when there is no event (scheduled jobs rerun by themselves) or it was
  rejected; `502` when the webhook fails (the dead letter stays open).
- `POST /v1/dead-letters/{id}/discard` with a `reason`.

A dead letter also closes automatically when its event later completes (redelivery or replay).

## `POST /v1/email/receive`

Body (from n8n's IMAP trigger): `message_id`, `in_reply_to`, `references`, `from_email`,
`from_name`, `subject`, `text`. Returns `kind`: `reply` (with `action` `reply_recorded` or
`opted_out`, the score change and the rep notification), `inquiry` (forwarded to the intake
webhook; `forwarded_status`), `duplicate` or `ignored`. Message ids are compared with or
without angle brackets.

## Browser APIs (`/public`, `/staff`)

Served to the frontend through nginx (`/api/public/...`, `/api/staff/...`); no `X-API-Key`.

- `GET /public/listings?location=&property_type=&bedrooms=&budget_max=`: available listings
  verified within 14 days, cheapest first, plus the locations and types on offer.
- `POST /public/inquiries`: `submission_id` (UUID generated by the browser, the idempotency
  key), `name`, `email` and/or `phone`, optional search fields, `timeline`, `purchase_stage`,
  `message`, and the honeypot `website` (must be empty). Validates with the same normalizer
  (`422` with field-level messages), limits each client to 5 inquiries per 10 minutes (`429`),
  then signs the payload and forwards it to the intake webhook. Returns `202` with a short
  reference.
- `/staff/*` requires `Authorization: Bearer <STAFF_TOKEN>` (fails closed when unset):
  `GET /staff/session`, `GET /staff/overview?period=day|week` (the report), `GET
  /staff/handoffs` (open, by deadline), `GET /staff/leads`, `GET /staff/dead-letters`, `POST
  /staff/dead-letters/{id}/replay`, `POST /staff/dead-letters/{id}/discard`.

## Health

- `GET /healthz`: liveness (no dependencies checked).
- `GET /readyz`: `200` when the database is reachable, otherwise `503`.
