-- PostgreSQL initialization script for CRM Entity Resolution
-- Run this script to create the required schema and tables

-- Create schema
CREATE SCHEMA IF NOT EXISTS splink_data;

-- Customer source table
CREATE TABLE IF NOT EXISTS splink_data.customers (
    customer_id VARCHAR(255) PRIMARY KEY,
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    address VARCHAR(500),
    city VARCHAR(100),
    state VARCHAR(100),
    country VARCHAR(100),
    dob DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Processed customers (staging)
CREATE TABLE IF NOT EXISTS splink_data.processed_customers (
    record_id VARCHAR(255) PRIMARY KEY,
    customer_id VARCHAR(255),
    first_name_std VARCHAR(255),
    last_name_std VARCHAR(255),
    email_std VARCHAR(255),
    phone_std VARCHAR(50),
    address_std VARCHAR(500),
    city_std VARCHAR(100),
    state_std VARCHAR(100),
    country_std VARCHAR(100),
    dob_std DATE,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Match predictions from Splink
CREATE TABLE IF NOT EXISTS splink_data.customer_matches (
    id SERIAL PRIMARY KEY,
    customer_id_1 VARCHAR(255) NOT NULL,
    customer_id_2 VARCHAR(255) NOT NULL,
    match_probability DECIMAL(5,4),
    match_status VARCHAR(20) CHECK (match_status IN ('MATCH', 'NON_MATCH', 'REVIEW')),
    blocking_rule VARCHAR(100),
    gamma_name INTEGER,
    gamma_contact INTEGER,
    gamma_location INTEGER,
    gamma_dob INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id_1, customer_id_2)
);

-- Review queue for manual review
CREATE TABLE IF NOT EXISTS splink_data.review_queue (
    id SERIAL PRIMARY KEY,
    customer_id_1 VARCHAR(255) NOT NULL,
    customer_id_2 VARCHAR(255) NOT NULL,
    match_probability DECIMAL(5,4),
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'in_review', 'completed')),
    reviewer VARCHAR(255),
    review_decision VARCHAR(20),
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id_1, customer_id_2)
);

-- Gold labels (ground truth)
CREATE TABLE IF NOT EXISTS splink_data.gold_labels (
    id SERIAL PRIMARY KEY,
    customer_id_1 VARCHAR(255) NOT NULL,
    customer_id_2 VARCHAR(255) NOT NULL,
    label VARCHAR(20) NOT NULL CHECK (label IN ('match', 'non_match')),
    source VARCHAR(50),
    reviewer VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(customer_id_1, customer_id_2)
);

-- Model metadata
CREATE TABLE IF NOT EXISTS splink_data.model_metadata (
    id SERIAL PRIMARY KEY,
    model_version VARCHAR(50) UNIQUE NOT NULL,
    model_path VARCHAR(500),
    m_probabilities JSONB,
    u_probabilities JSONB,
    recall_score DECIMAL(5,4),
    precision_score DECIMAL(5,4),
    f1_score DECIMAL(5,4),
    threshold_match DECIMAL(5,4),
    threshold_non_match DECIMAL(5,4),
    trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    training_data_size INTEGER,
    notes TEXT
);

-- Entity mapping (record_id -> entity_id)
CREATE TABLE IF NOT EXISTS splink_data.entity_map (
    record_id VARCHAR(255) PRIMARY KEY,
    entity_id VARCHAR(255) NOT NULL,
    cluster_status VARCHAR(20) DEFAULT 'SINGLETON',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Master customers (one per entity)
CREATE TABLE IF NOT EXISTS splink_data.master_customers (
    entity_id VARCHAR(255) PRIMARY KEY,
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    address VARCHAR(500),
    city VARCHAR(100),
    state VARCHAR(100),
    country VARCHAR(100),
    dob DATE,
    source_records TEXT[],
    source_record_id VARCHAR(255),
    source_completeness INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_matches_status ON splink_data.customer_matches(match_status);
CREATE INDEX IF NOT EXISTS idx_matches_probability ON splink_data.customer_matches(match_probability);
CREATE INDEX IF NOT EXISTS idx_review_queue_status ON splink_data.review_queue(status);
CREATE INDEX IF NOT EXISTS idx_entity_map_entity ON splink_data.entity_map(entity_id);

-- Normalized resolution outputs. These tables complement the legacy tables above.
CREATE TABLE IF NOT EXISTS splink_data.master_customer_current (
    entity_id VARCHAR(255) PRIMARY KEY,
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    address VARCHAR(500),
    city VARCHAR(100),
    state VARCHAR(100),
    country VARCHAR(100),
    dob DATE,
    resolution_status VARCHAR(30) NOT NULL DEFAULT 'UNRESOLVED'
        CHECK (resolution_status IN ('CONFIRMED', 'CONFLICTED', 'REVIEW_REQUIRED', 'UNRESOLVED')),
    model_version VARCHAR(100),
    pipeline_run_id VARCHAR(100),
    source_scope VARCHAR(20),
    exported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS splink_data.entity_membership (
    entity_id VARCHAR(255) NOT NULL,
    record_id VARCHAR(255) PRIMARY KEY,
    customer_id VARCHAR(255),
    source VARCHAR(255),
    model_version VARCHAR(100),
    pipeline_run_id VARCHAR(100),
    assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_entity_membership_entity ON splink_data.entity_membership(entity_id);

CREATE TABLE IF NOT EXISTS splink_data.entity_conflict (
    conflict_id BIGSERIAL PRIMARY KEY,
    entity_id VARCHAR(255) NOT NULL,
    field_name VARCHAR(100) NOT NULL,
    value TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'RESOLVED', 'IGNORED')),
    reviewer VARCHAR(255),
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_entity_conflict_entity ON splink_data.entity_conflict(entity_id);

CREATE TABLE IF NOT EXISTS splink_data.master_customer_snapshot (
    snapshot_id UUID NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    model_version VARCHAR(100),
    pipeline_run_id VARCHAR(100),
    source_scope VARCHAR(20),
    exported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    address VARCHAR(500),
    city VARCHAR(100),
    state VARCHAR(100),
    country VARCHAR(100),
    dob DATE,
    resolution_status VARCHAR(30) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_master_snapshot_id ON splink_data.master_customer_snapshot(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_master_snapshot_entity ON splink_data.master_customer_snapshot(entity_id);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA splink_data TO crm_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA splink_data TO crm_user;

COMMENT ON TABLE splink_data.customers IS 'Source customer data from CRM';
COMMENT ON TABLE splink_data.customer_matches IS 'Match predictions from Splink model';
COMMENT ON TABLE splink_data.review_queue IS 'Pairs pending manual review';
COMMENT ON TABLE splink_data.gold_labels IS 'Human-labeled ground truth for training/evaluation';