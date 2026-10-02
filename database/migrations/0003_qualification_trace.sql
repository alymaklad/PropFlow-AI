-- Richer AI trace: record the review decision and why, and allow the non-LLM outcomes.
ALTER TABLE qualifications DROP CONSTRAINT qualifications_validation_status_check;
ALTER TABLE qualifications ADD CONSTRAINT qualifications_validation_status_check
    CHECK (validation_status IN ('valid', 'repaired', 'invalid', 'fallback', 'skipped',
                                 'unsupported_language'));
ALTER TABLE qualifications ALTER COLUMN model DROP NOT NULL;
ALTER TABLE qualifications
    ADD COLUMN needs_human_review boolean NOT NULL DEFAULT false,
    ADD COLUMN reasons text[] NOT NULL DEFAULT '{}',
    ADD COLUMN attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN correlation_id uuid;
CREATE INDEX qualifications_correlation_idx ON qualifications (correlation_id);
