-- PropFlow AI application schema. Odoo remains the source of truth for CRM entities;
-- these tables hold the ledger, AI traces, scores, catalog, consent and recovery data.

CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Idempotency ledger + audit copy of every inbound event (including rejected ones).
CREATE TABLE intake_events (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key  text NOT NULL UNIQUE,
    correlation_id   uuid NOT NULL DEFAULT gen_random_uuid(),
    source           text NOT NULL CHECK (source IN ('form', 'email', 'whatsapp', 'manual')),
    received_at      timestamptz NOT NULL DEFAULT now(),
    raw_payload      jsonb NOT NULL,
    status           text NOT NULL DEFAULT 'received'
                     CHECK (status IN ('received', 'processing', 'completed', 'rejected', 'failed')),
    delivery_count   integer NOT NULL DEFAULT 1 CHECK (delivery_count >= 1),
    error            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX intake_events_correlation_idx ON intake_events (correlation_id);
CREATE INDEX intake_events_status_idx ON intake_events (status, received_at);
CREATE TRIGGER intake_events_updated BEFORE UPDATE ON intake_events
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- AI trace: what the model returned, whether it validated, and under which prompt/model.
CREATE TABLE qualifications (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id          uuid NOT NULL REFERENCES intake_events (id),
    model             text NOT NULL,
    prompt_version    text NOT NULL,
    raw_output        text,
    validated_output  jsonb,
    validation_status text NOT NULL
                      CHECK (validation_status IN ('valid', 'repaired', 'invalid', 'fallback')),
    confidence        numeric(3, 2) CHECK (confidence BETWEEN 0 AND 1),
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX qualifications_event_idx ON qualifications (event_id);

-- Deterministic scoring result with explainable components.
CREATE TABLE score_results (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id       uuid NOT NULL REFERENCES intake_events (id),
    rules_version  text NOT NULL,
    total          integer NOT NULL CHECK (total BETWEEN 0 AND 100),
    components     jsonb NOT NULL,  -- [{rule, points, reason}]
    priority       text NOT NULL CHECK (priority IN ('high', 'standard', 'nurture')),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX score_results_event_idx ON score_results (event_id);

-- Property catalog (synthetic seed data in dev).
CREATE TABLE properties (
    listing_id       text PRIMARY KEY,
    property_type    text NOT NULL,
    location         text NOT NULL,
    price            numeric(14, 2) NOT NULL CHECK (price >= 0),
    currency         char(3) NOT NULL DEFAULT 'EGP',
    bedrooms         smallint CHECK (bedrooms >= 0),
    bathrooms        smallint CHECK (bathrooms >= 0),
    delivery_status  text NOT NULL CHECK (delivery_status IN ('ready', 'under_construction', 'off_plan')),
    amenities        text[] NOT NULL DEFAULT '{}',
    description      text,
    availability     text NOT NULL DEFAULT 'available'
                     CHECK (availability IN ('available', 'reserved', 'sold', 'withdrawn')),
    last_verified_at timestamptz NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX properties_match_idx ON properties (location, property_type, availability);
CREATE TRIGGER properties_updated BEFORE UPDATE ON properties
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Outbound message ledger. A row is inserted BEFORE sending; the unique key prevents
-- duplicate sends when a workflow retries. lead_ref is the lead's correlation id
-- (the same value stored in Odoo's x_correlation_id).
CREATE TABLE outbound_messages (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_ref         text NOT NULL,
    channel          text NOT NULL CHECK (channel IN ('email', 'whatsapp')),
    template         text NOT NULL,
    sequence_no      integer NOT NULL DEFAULT 1 CHECK (sequence_no >= 1),
    status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'sent', 'delivered', 'failed', 'cancelled')),
    provider_msg_id  text,
    error            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (lead_ref, template, sequence_no)
);
CREATE TRIGGER outbound_messages_updated BEFORE UPDATE ON outbound_messages
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Consent / opt-out. contact_key is a normalized E.164 phone or lowercased email.
CREATE TABLE consents (
    contact_key  text NOT NULL,
    channel      text NOT NULL CHECK (channel IN ('email', 'whatsapp')),
    status       text NOT NULL CHECK (status IN ('opted_in', 'opted_out')),
    source       text NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (contact_key, channel)
);

-- Handoffs to a salesperson. Automation stops for the lead; the rep contacts the customer.
CREATE TABLE escalations (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id             uuid NOT NULL REFERENCES intake_events (id),
    reason               text NOT NULL,
    status               text NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open', 'resolved', 'cancelled')),
    assigned_to          text NOT NULL,          -- Odoo login of the owning salesperson
    due_at               timestamptz NOT NULL,   -- contact deadline (SLA by priority)
    reminder_count       integer NOT NULL DEFAULT 0 CHECK (reminder_count >= 0),
    manager_notified_at  timestamptz,
    outcome              text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    resolved_at          timestamptz
);
CREATE INDEX escalations_open_idx ON escalations (status, due_at);

-- Dead-letter queue for permanently failed workflow runs (replayed manually by id).
CREATE TABLE dead_letters (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow        text NOT NULL,
    correlation_id  uuid,
    payload         jsonb NOT NULL,
    error           text NOT NULL,
    attempts        integer NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'replayed', 'discarded')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX dead_letters_open_idx ON dead_letters (status, created_at);
CREATE TRIGGER dead_letters_updated BEFORE UPDATE ON dead_letters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
