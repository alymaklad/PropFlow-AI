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

## Health

- `GET /healthz`: liveness (no dependencies checked).
- `GET /readyz`: `200` when the database is reachable, otherwise `503`.
