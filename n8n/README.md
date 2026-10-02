# n8n workflows

The files in this folder are the source of truth. The n8n UI is at http://localhost:5678.

| File | Workflow | Trigger |
|---|---|---|
| `workflows/lead-intake-a.json` | **PropFlow - Lead intake (A)** | `POST /webhook/propflow/intake` |
| `workflows/email-intake-b.json` | **PropFlow - Email intake (B)** | New email in the leads inbox (IMAP) |
| `workflows/scheduler.json` | **PropFlow - Scheduler (handoffs, follow-ups)** | Every 15 minutes |
| `workflows/error-handler.json` | **PropFlow - Error handler** | Any failed run of the other workflows |
| `credentials/mailpit-smtp.json` | Mailpit SMTP (dev) | No secret: Mailpit needs no login |
| `credentials/greenmail-imap.json` | GreenMail IMAP (dev) | No secret: GreenMail runs with authentication disabled |

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

The workflow orchestrates; validation, AI, scoring, matching and CRM logic live in the AI
service, where they are unit-tested.

1. **Prepare receive request** / **Receive & claim** (`/v1/intake/receive`): signature check,
   parse, record the event once. Bad signature `401` (not stored); signed but not a JSON object
   `422` (stored as rejected); already completed `200 duplicate`.
2. **Normalize**: an invalid lead gets `422`; a valid one gets `202 accepted` straight away and
   the rest runs after the response.
3. **Qualify** (`/v1/qualify`): AI extraction merged under the form fields. An opt-out records
   consent and stops here (no lead, no messages).
4. **Score**, **Upsert lead in Odoo** (retried; on failure the event is marked `failed` and the
   run fails so the error handler records it), **Match properties**.
5. **Next action** (`/v1/actions/next`): hand off to the salesperson, or email a shortlist or a
   clarification question, schedule the rep's follow-up, start reminders, and notify the rep
   of high-priority leads. It returns the emails to send, already consent-checked and claimed.
6. **Send** each email, mark it sent or failed in the ledger. Entries without a recipient
   (no owner, no manager) become ops alerts. Then **Mark completed** (once).

A redelivery of a failed or still-running event is processed again; every step is idempotent.
n8n rejects bodies that are not valid JSON (`422`) before the workflow runs, so those are not
stored.

## Email intake (B)

Watches the leads inbox (`INBOUND_EMAIL`; GreenMail in dev) and passes each email to
`/v1/email/receive`:

- **Reply to something we sent** (its `In-Reply-To`/`References` match a message id in the
  outbound ledger, or a "Re:" subject from an address with active reminders): reminders stop,
  the reply is posted on the lead, the follow-up-response points are added to the score, the
  owner gets an activity and an email. A "STOP" reply records the opt-out instead.
- **New inquiry**: the service signs it and forwards it to the intake webhook with the email's
  Message-ID as idempotency key, so it goes through exactly the same steps as a web form.

Every outgoing email sets Reply-To to the leads inbox, so customer replies land there. To test:
`python3 scripts/send_email.py --from buyer@example.com --subject "..." --body "..."
[--in-reply-to "<message-id>"]`.

## Scheduler

**PropFlow - Scheduler** runs every 15 minutes: `/v1/handoffs/check` (resolve handoffs whose
activity is done, remind the rep after the deadline, then the manager) and `/v1/followups/due`
(customer reminders), then the same send-and-mark steps. Messages only go out during business
hours (Sunday to Thursday, 09:00-17:00 Cairo by default).

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
