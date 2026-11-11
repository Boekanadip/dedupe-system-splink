-- Tables used by the manual "Save to database" buttons on the Ringkasan page.
-- Created here so the buttons always have an existing target table.

-- Pairs export: one row per scored candidate pair.
CREATE TABLE IF NOT EXISTS splink_data.dedup_outputs (
    record_id_l VARCHAR(255) NOT NULL,
    record_id_r VARCHAR(255) NOT NULL,
    match_probability DOUBLE PRECISION,
    match_weight DOUBLE PRECISION,
    decision VARCHAR(20),
    business_rule VARCHAR(255),
    blocking_rule VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (record_id_l, record_id_r)
);

-- Clean master export: one row per resolved entity.
CREATE TABLE IF NOT EXISTS splink_data.master_customer_bersih (
    entity_id VARCHAR(255) PRIMARY KEY,
    first_name_std VARCHAR(255),
    last_name_std VARCHAR(255),
    email_std VARCHAR(255),
    phone_std VARCHAR(50),
    address_std VARCHAR(500),
    city_std VARCHAR(100),
    state_std VARCHAR(100),
    country_std VARCHAR(100),
    dob_std DATE,
    record_count INTEGER,
    record_ids TEXT[],
    customer_ids TEXT[],
    sources TEXT[],
    conflicted_fields TEXT[],
    resolution_status VARCHAR(30) NOT NULL DEFAULT 'CONFIRMED'
        CHECK (resolution_status IN ('CONFIRMED', 'CONFLICTED')),
    model_version VARCHAR(100),
    pipeline_run_id VARCHAR(100),
    source_scope VARCHAR(20),
    exported_at TIMESTAMPTZ
);

COMMENT ON TABLE splink_data.dedup_outputs IS
    'Export of scored candidate pairs from the Ringkasan page.';
COMMENT ON TABLE splink_data.master_customer_bersih IS
    'Export of clean master customers (one row per entity) from the Ringkasan page.';
