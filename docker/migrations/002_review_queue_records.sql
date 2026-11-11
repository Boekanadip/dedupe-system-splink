-- Active manual-review queue, keyed by record pair.
-- Complements splink_data.review_queue (legacy, customer_id based).

CREATE TABLE IF NOT EXISTS splink_data.review_queue_records (
    review_id BIGSERIAL PRIMARY KEY,
    record_id_l VARCHAR(255) NOT NULL,
    record_id_r VARCHAR(255) NOT NULL,
    stratum VARCHAR(100) NOT NULL DEFAULT 'manual_review',
    match_probability DOUBLE PRECISION,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    label VARCHAR(20),
    review_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'in_review', 'reviewed')),
    reviewer VARCHAR(255),
    reviewer_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMPTZ,
    UNIQUE(record_id_l, record_id_r)
);

CREATE INDEX IF NOT EXISTS idx_review_records_status
    ON splink_data.review_queue_records(review_status);
CREATE INDEX IF NOT EXISTS idx_review_records_probability
    ON splink_data.review_queue_records(match_probability);

COMMENT ON TABLE splink_data.review_queue_records IS
    'Active manual review queue: one row per candidate record pair.';
