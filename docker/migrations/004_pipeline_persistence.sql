-- Make the tables the pipeline writes to hold everything the UI needs.
-- Safe to re-run.

ALTER TABLE splink_data.processed_customers
    ADD COLUMN IF NOT EXISTS source VARCHAR(255);

ALTER TABLE splink_data.dedup_outputs
    ADD COLUMN IF NOT EXISTS gamma_name INTEGER,
    ADD COLUMN IF NOT EXISTS gamma_contact INTEGER,
    ADD COLUMN IF NOT EXISTS gamma_location INTEGER,
    ADD COLUMN IF NOT EXISTS gamma_dob INTEGER,
    ADD COLUMN IF NOT EXISTS pipeline_run_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS source_scope VARCHAR(20),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_dedup_outputs_decision
    ON splink_data.dedup_outputs(decision);
CREATE INDEX IF NOT EXISTS idx_dedup_outputs_probability
    ON splink_data.dedup_outputs(match_probability);
CREATE INDEX IF NOT EXISTS idx_processed_customers_customer
    ON splink_data.processed_customers(customer_id);

-- Gold labels used to be keyed by source customer_id, but the review flow
-- works on record_id. Keep both; record ids are the active keys.
ALTER TABLE splink_data.gold_labels
    ADD COLUMN IF NOT EXISTS record_id_l VARCHAR(255),
    ADD COLUMN IF NOT EXISTS record_id_r VARCHAR(255),
    ADD COLUMN IF NOT EXISTS stratum VARCHAR(100),
    ADD COLUMN IF NOT EXISTS match_probability DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS reviewer_note TEXT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

ALTER TABLE splink_data.gold_labels ALTER COLUMN customer_id_1 DROP NOT NULL;
ALTER TABLE splink_data.gold_labels ALTER COLUMN customer_id_2 DROP NOT NULL;

ALTER TABLE splink_data.gold_labels DROP CONSTRAINT IF EXISTS gold_labels_label_check;
ALTER TABLE splink_data.gold_labels
    ADD CONSTRAINT gold_labels_label_check CHECK (label IN ('match', 'no_match'));

UPDATE splink_data.gold_labels SET record_id_l = '' WHERE record_id_l IS NULL;
UPDATE splink_data.gold_labels SET record_id_r = '' WHERE record_id_r IS NULL;
ALTER TABLE splink_data.gold_labels ALTER COLUMN record_id_l SET NOT NULL;
ALTER TABLE splink_data.gold_labels ALTER COLUMN record_id_r SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_gold_labels_pairs
    ON splink_data.gold_labels(record_id_l, record_id_r);
