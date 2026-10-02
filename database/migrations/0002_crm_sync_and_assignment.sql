-- Link ledger events to the Odoo lead they created or updated.
ALTER TABLE intake_events ADD COLUMN odoo_lead_id integer;
CREATE INDEX intake_events_odoo_lead_idx ON intake_events (odoo_lead_id);

-- Round-robin pointer per Odoo sales team. Updated under a row lock, so concurrent intakes
-- never take the same slot.
CREATE TABLE round_robin_state (
    team_id       integer PRIMARY KEY,
    last_user_id  integer,
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- One assignment per lead (by correlation id), so retrying an intake never advances the
-- pointer twice or gives the same lead a different owner.
CREATE TABLE lead_assignments (
    correlation_id  uuid PRIMARY KEY,
    team_id         integer NOT NULL,
    user_id         integer NOT NULL,
    assigned_at     timestamptz NOT NULL DEFAULT now()
);

-- One score per event and rules version, so a retried intake updates instead of duplicating.
CREATE UNIQUE INDEX score_results_event_rules_uniq ON score_results (event_id, rules_version);
