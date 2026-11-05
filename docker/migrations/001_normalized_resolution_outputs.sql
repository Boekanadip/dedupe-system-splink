-- Prepared migration; do not run automatically.
-- Apply manually after reviewing existing production data.

BEGIN;

CREATE SCHEMA IF NOT EXISTS splink_data;

CREATE TABLE IF NOT EXISTS splink_data.master_customer_current (
    entity_id VARCHAR(255) PRIMARY KEY,
    first_name VARCHAR(255), last_name VARCHAR(255), email VARCHAR(255),
    phone VARCHAR(50), address VARCHAR(500), city VARCHAR(100),
    state VARCHAR(100), country VARCHAR(100), dob DATE,
    resolution_status VARCHAR(30) NOT NULL DEFAULT 'UNRESOLVED',
    model_version VARCHAR(100), pipeline_run_id VARCHAR(100),
    source_scope VARCHAR(20), exported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (resolution_status IN ('CONFIRMED', 'CONFLICTED', 'REVIEW_REQUIRED', 'UNRESOLVED'))
);

CREATE TABLE IF NOT EXISTS splink_data.entity_membership (
    entity_id VARCHAR(255) NOT NULL, record_id VARCHAR(255) PRIMARY KEY,
    customer_id VARCHAR(255), source VARCHAR(255), model_version VARCHAR(100),
    pipeline_run_id VARCHAR(100), assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_entity_membership_entity ON splink_data.entity_membership(entity_id);

CREATE TABLE IF NOT EXISTS splink_data.entity_conflict (
    conflict_id BIGSERIAL PRIMARY KEY, entity_id VARCHAR(255) NOT NULL,
    field_name VARCHAR(100) NOT NULL, value TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'OPEN', reviewer VARCHAR(255),
    reviewed_at TIMESTAMP, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('OPEN', 'RESOLVED', 'IGNORED'))
);
CREATE INDEX IF NOT EXISTS idx_entity_conflict_entity ON splink_data.entity_conflict(entity_id);

CREATE TABLE IF NOT EXISTS splink_data.master_customer_snapshot (
    snapshot_id UUID NOT NULL, entity_id VARCHAR(255) NOT NULL,
    model_version VARCHAR(100), pipeline_run_id VARCHAR(100), source_scope VARCHAR(20),
    exported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    first_name VARCHAR(255), last_name VARCHAR(255), email VARCHAR(255), phone VARCHAR(50),
    address VARCHAR(500), city VARCHAR(100), state VARCHAR(100), country VARCHAR(100), dob DATE,
    resolution_status VARCHAR(30) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_master_snapshot_id ON splink_data.master_customer_snapshot(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_master_snapshot_entity ON splink_data.master_customer_snapshot(entity_id);

COMMIT;

-- Intentionally no INSERT/UPDATE. This file only prepares the schema.
