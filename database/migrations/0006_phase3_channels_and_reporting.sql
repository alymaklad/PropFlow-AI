-- Phase 3: email intake (inquiry vs reply), contact limits, replay, reporting fields.
ALTER TABLE intake_events
    ADD COLUMN kind text NOT NULL DEFAULT 'inquiry' CHECK (kind IN ('inquiry', 'reply')),
    ADD COLUMN crm_action text CHECK (crm_action IN ('created', 'updated', 'matched_contact'));

ALTER TABLE outbound_messages
    ADD COLUMN to_address text,
    ADD COLUMN sent_at timestamptz;
CREATE INDEX outbound_messages_recipient_idx ON outbound_messages (lower(to_address), created_at);
CREATE INDEX outbound_messages_provider_idx ON outbound_messages (provider_msg_id);

ALTER TABLE dead_letters
    ADD COLUMN replayed_at timestamptz,
    ADD COLUMN resolution text;
CREATE INDEX dead_letters_correlation_idx ON dead_letters (correlation_id);
