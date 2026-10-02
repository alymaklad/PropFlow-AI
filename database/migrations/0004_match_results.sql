-- Property-match outcome per event (for the reports: match outcomes by status).
CREATE TABLE match_results (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id        uuid REFERENCES intake_events (id),
    correlation_id  uuid NOT NULL,
    status          text NOT NULL
                    CHECK (status IN ('matched', 'none', 'insufficient_criteria', 'conflict')),
    listing_ids     text[] NOT NULL DEFAULT '{}',
    criteria        jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX match_results_event_idx ON match_results (event_id);
