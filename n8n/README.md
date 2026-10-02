# n8n workflows

The files in this folder are the source of truth. The n8n UI is at http://localhost:5678.

| File | Workflow | Trigger |
|---|---|---|
| `workflows/lead-intake-a.json` | **PropFlow - Lead intake (A)** | `POST /webhook/propflow/intake` |
| `workflows/error-handler.json` | **PropFlow - Error handler** | Any failed run of the intake workflow |
| `credentials/mailpit-smtp.json` | Mailpit SMTP (dev) | No secret: Mailpit needs no login |

```bash
make n8n-import   # load credentials + workflows, publish them, restart n8n
make n8n-export   # after editing in the UI: write PropFlow workflows back to workflows/
```

Re-importing overwrites workflows with the same id. n8n 2.x only runs a workflow (including
an error workflow) once it is **published**; the import script publishes every file with
`"active": true`.

## Sending a lead

Requests must be signed (see `docs/api-specification.md`). For testing:

```bash
python3 scripts/send_lead.py '{"name": "Test", "email": "t@example.com", "property_type": "villa", "location": "Sheikh Zayed", "bedrooms": 4, "budget": "up to 15M", "timeline": "within_3_months", "purchase_stage": "ready_to_buy"}'
python3 scripts/send_lead.py --file lead.json --event-id evt-123
```

## Lead intake (A)

The workflow orchestrates; validation, scoring and CRM logic live in the AI service, where
they are unit-tested.

1. **Prepare receive request**: passes the exact raw body and the signature headers on.
2. **Receive & claim** (`/v1/intake/receive`): verifies the signature, parses the body,
   records the event once. Responses: bad signature `401` (not stored); signed but not a JSON
   object `422` (stored as rejected); already completed `200 duplicate`.
3. **Normalize**: an invalid lead (no contact or no content) is marked rejected and gets `422`.
   A valid lead gets `202 accepted` straight away; the rest runs after the response.
4. **Score**, then **Upsert lead in Odoo** (retried 3 times). Conflicting input sets the
   lead's exception status to `handoff`. If the upsert still fails, the event is marked
   `failed` and the run fails on purpose so the error handler records it.
5. **Schedule follow-up** for the owner.
6. **Notify?**: high priority with an owner: the rep email is claimed in the outbound ledger
   first, so it is sent at most once even when the event is delivered several times. No
   owner: ops gets an alert.
7. **Mark completed**.

A redelivery of a failed or still-running event is processed again; every step is idempotent
(one lead, one follow-up activity, one rep email; verified with 6 simultaneous deliveries).

Note: n8n's webhook rejects bodies that are not valid JSON (`422 Failed to parse request body`)
before the workflow runs, so those are refused but not stored in the ledger.

## Error handler

Error Trigger, then a dead-letter record (`/v1/dead-letters`, with the correlation id recovered
from the error message), then an alert email to `ALERT_EMAIL`. After fixing the cause,
redeliver the event: a failed event is processed again.

## Environment

The workflows read these via `$env` (set in `docker-compose.yml`): `AI_SERVICE_URL`,
`AI_SERVICE_API_KEY`, `NOTIFY_FROM_EMAIL`, `ALERT_EMAIL`. `N8N_BLOCK_ENV_ACCESS_IN_NODE` is
relaxed for dev only; use n8n credentials for staging/production.

Successful executions are saved (with lead data) to help debugging in dev. Turn
`saveDataSuccessExecution` off before handling real data.
