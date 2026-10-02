-- Handoff tracking (Workflow G) and customer follow-up sequences (Workflow F).
ALTER TABLE escalations
    ADD COLUMN correlation_id    uuid,
    ADD COLUMN odoo_lead_id      integer,
    ADD COLUMN odoo_activity_id  integer,
    ADD COLUMN assigned_user_id  integer,
    ADD COLUMN priority          text,
    ADD COLUMN reminded_at       timestamptz;
ALTER TABLE escalations ALTER COLUMN assigned_to DROP NOT NULL;  -- may be unassigned
CREATE UNIQUE INDEX escalations_event_uniq ON escalations (event_id);

CREATE TABLE followup_sequences (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    odoo_lead_id    integer NOT NULL UNIQUE,
    correlation_id  uuid NOT NULL,
    to_email        text NOT NULL,
    contact_keys    text[] NOT NULL DEFAULT '{}',
    customer_name   text,
    requirements    jsonb NOT NULL DEFAULT '{}',
    status          text NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'stopped', 'completed')),
    stop_reason     text,
    reminders_sent  integer NOT NULL DEFAULT 0 CHECK (reminders_sent >= 0),
    max_reminders   integer NOT NULL DEFAULT 2 CHECK (max_reminders >= 0),
    next_due_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX followup_sequences_due_idx ON followup_sequences (status, next_due_at);
CREATE TRIGGER followup_sequences_updated BEFORE UPDATE ON followup_sequences
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
