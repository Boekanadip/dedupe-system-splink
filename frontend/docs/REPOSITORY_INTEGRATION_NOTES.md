# Existing deduplication repository — integration notes

Repository: https://github.com/Boekanadip/dedupe-system-splink

## What is grounded in the public README

The public README describes a CRM entity-resolution application built with Python, Splink 4, DuckDB, Pandas, PyArrow, and Streamlit. It documents the following processing concepts:

- Data validation and upload validation.
- Internal `record_id` distinct from source `customer_id` and generated `entity_id`.
- Standardization and blocking.
- Probabilistic record linkage and scoring.
- Decision bands `MATCH`, `REVIEW`, and `NON_MATCH`.
- Human review, gold labels, and feedback.
- Clustering, entity maps, and master records.
- Model versioning, threshold configuration/evaluation, and incremental processing.
- CSV and PostgreSQL/DuckDB source paths are described in the README.

## What this frontend assumes

- The first platform adapter will target this Splink-based system.
- The current Streamlit UI is not the new platform UI.
- The frontend will consume normalized FastAPI resources and will not import Python modules.
- Splink-specific settings should be generated from backend model metadata when that integration is implemented.

## What has not been verified in this build environment

A shallow Git clone was attempted during prototype creation, but network DNS resolution for `github.com` failed in the build environment. Therefore, this delivery has not audited the actual source files, executed the repository smoke test, or verified importability of individual Python modules.

Before implementing the adapter, clone the repository locally and inspect at least:

- `README.md`, `PRD.md`, `PANDUAN.md`, and any backend handoff notes.
- `src/config.py`, `src/validate_upload.py`, `src/standardize.py`, `src/db_source.py`, `src/db_export.py`, `src/job_run.py`.
- `src/splink_model.py`, `src/clustering.py`, `src/master_record.py`, `src/labels.py`, `src/feedback.py`, `src/evaluate.py`, `src/incremental.py`, `src/model_lifecycle.py`.
- `app.py`, `pages/`, `requirements.txt`, and `tests/test_smoke.py`.

The file list above is based on the repository's README tree and must be checked against the current checkout.

## Integration rule

Do not copy the whole Streamlit application into FastAPI. First identify reusable functions, side effects, file paths, module-level state, and database boundaries. Extract or wrap only the services needed by the platform. Preserve the repository's decision semantics and add characterization tests before refactoring behavior.
