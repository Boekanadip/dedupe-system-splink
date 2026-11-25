"""FastAPI application for CRM entity resolution predictions."""
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import tempfile
import io
import hmac
import threading
import uuid
from datetime import datetime, timezone

from src.export import csv_bytes, save_to_database
from src.splink_model import (build_dynamic_settings_from_columns,
                             infer_selected_columns_from_df,
                             add_decision_dynamic,
                             add_decision,
                             apply_business_rules,
                             DETERMINISTIC_RULES)
from src.config import (
    MATCH_THRESHOLD,
    REVIEW_THRESHOLD,
    LAMBDA_RECALL_ASSUMPTION,
    PROCESSED_DATA_PATH,
    OUTPUT_DIR,
    pipeline_locked,
    )

app = FastAPI(title="CRM Entity Resolution API")

API_KEY = os.environ.get("DEDUP_API_KEY", "").strip()
API_KEY_REQUIRED = bool(API_KEY)


def require_api_key(request):
    if not API_KEY_REQUIRED:
        raise HTTPException(
            status_code=503,
            detail="DEDUP_API_KEY is not configured",
        )
    supplied = request.headers.get("x-api-key", "")
    if not hmac.compare_digest(supplied, API_KEY):
        raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")

# CORS — batasi ke origin UI yang dikenal (bukan wildcard)
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5174,http://127.0.0.1:5174,http://localhost:8501,http://localhost:8050,http://127.0.0.1:8501,http://127.0.0.1:8050",
    ).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)

PREDICTIONS_PATH = PROJECT_ROOT / "outputs" / "splink_predictions.parquet"
MODEL_PATH = PROJECT_ROOT / "models" / "latest.json"
REVIEW_AUDIT_PATH = PROJECT_ROOT / "data" / "labels" / "nexus_review_decisions.csv"
REVIEW_AUDIT_LOCK = threading.RLock()
DATASET_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
DATASET_REGISTRY_PATH = PROJECT_ROOT / "data" / "dataset_registry.json"
DATASET_REGISTRY_LOCK = threading.RLock()
JOB_REGISTRY_PATH = PROJECT_ROOT / "data" / "job_registry.json"
WORKSPACE_SETTINGS_PATH = PROJECT_ROOT / "data" / "workspace_settings.json"
WORKSPACE_SETTINGS_LOCK = threading.RLock()
DEFAULT_WORKSPACE_SETTINGS = {
    "workspace_name": "HyperData Intelligence",
    "timezone": "Asia/Jakarta",
    "default_landing_page": "dashboard",
    "date_format": "DD MMM YYYY",
    "theme": "light",
    "preserve_source_data": True,
    "require_output_confirmation": True,
    "keep_processing_audit_trail": True,
}
WORKSPACE_SETTINGS_FIELDS = set(DEFAULT_WORKSPACE_SETTINGS)

# Load predictions and customer records once
_predictions_df = None
_customers_df = None


def read_model_version():
    if not MODEL_PATH.exists():
        return None
    try:
        import json
        return json.loads(MODEL_PATH.read_text()).get("version")
    except Exception:
        return None


def clean_pair_probability(value):
    try:
        probability = float(value)
        if np.isfinite(probability):
            return probability
    except (TypeError, ValueError):
        pass
    return None


def append_review_audit(record):
    REVIEW_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if REVIEW_AUDIT_PATH.exists():
        import csv
        with REVIEW_AUDIT_PATH.open("r", encoding="utf-8", newline="") as fh:
            existing = list(csv.DictReader(fh))
        for row in existing:
            if row.get("request_id") == record["request_id"]:
                return {"created": False, "record": row}

    import csv
    fieldnames = [
        "request_id", "record_id_l", "record_id_r", "decision", "reviewer",
        "reason", "scope", "match_probability", "model_version", "created_at",
    ]
    write_header = not REVIEW_AUDIT_PATH.exists()
    with REVIEW_AUDIT_PATH.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(record)
    return {"created": True, "record": record}


def sync_review_decision_to_supabase(record_id_l: str, record_id_r: str, decision: str, reviewer: str, reason: str):
    """Sync manual review decision to Supabase review_queue_records and dedup_outputs."""
    try:
        from api.db import get_supabase_connection
        # Map decision UI/Splink ke check constraint status review_queue_records:
        # CHECK ((status = ANY (ARRAY['PENDING', 'APPROVED_MATCH', 'REJECTED_MATCH', 'DEFERRED'])))
        status_map = {
            "MATCH": "APPROVED_MATCH",
            "NON_MATCH": "REJECTED_MATCH",
            "REVIEW": "DEFERRED",
        }
        queue_status = status_map.get(decision, "DEFERRED")

        with get_supabase_connection() as conn:
            with conn.cursor() as cur:
                # 1. Cari pair_id di dedup_outputs
                cur.execute(
                    """
                    SELECT pair_id FROM public.dedup_outputs
                    WHERE (record_id_l = %s AND record_id_r = %s)
                       OR (record_id_l = %s AND record_id_r = %s)
                    LIMIT 1
                    """,
                    (record_id_l, record_id_r, record_id_r, record_id_l),
                )
                row = cur.fetchone()
                if not row:
                    return {"synced": False, "reason": "pair_not_in_supabase"}
                pair_id = row[0]

                # 2. Update decision di dedup_outputs (MATCH, REVIEW, NON_MATCH)
                cur.execute(
                    """
                    UPDATE public.dedup_outputs
                    SET decision = %s
                    WHERE pair_id = %s
                    """,
                    (decision, pair_id),
                )

                # 3. Update atau insert di review_queue_records
                cur.execute(
                    """
                    UPDATE public.review_queue_records
                    SET status = %s,
                        reviewer = %s,
                        review_reason = %s,
                        reviewed_at = NOW()
                    WHERE pair_id = %s
                    """,
                    (queue_status, reviewer, reason, pair_id),
                )
                if cur.rowcount == 0:
                    cur.execute(
                        """
                        INSERT INTO public.review_queue_records
                        (review_id, pair_id, status, reviewer, review_reason, reviewed_at, created_at)
                        VALUES (gen_random_uuid(), %s, %s, %s, %s, NOW(), NOW())
                        """,
                        (pair_id, queue_status, reviewer, reason),
                    )
                conn.commit()
                return {"synced": True, "pair_id": str(pair_id), "status": queue_status}
    except Exception as exc:
        return {"synced": False, "error": str(exc)}


def read_job_registry():
    if not JOB_REGISTRY_PATH.exists():
        return {"jobs": []}
    try:
        import json
        registry = json.loads(JOB_REGISTRY_PATH.read_text(encoding="utf-8"))
        return registry if isinstance(registry, dict) else {"jobs": []}
    except (json.JSONDecodeError, OSError):
        return {"jobs": []}


def read_dataset_registry():
    if not DATASET_REGISTRY_PATH.exists():
        return {"datasets": []}
    try:
        import json
        registry = json.loads(DATASET_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail="Dataset registry is unreadable") from exc
    if not isinstance(registry, dict) or not isinstance(registry.get("datasets"), list):
        raise HTTPException(status_code=500, detail="Dataset registry has an invalid format")
    return registry


def read_workspace_settings():
    import json

    with WORKSPACE_SETTINGS_LOCK:
        if not WORKSPACE_SETTINGS_PATH.exists():
            return dict(DEFAULT_WORKSPACE_SETTINGS)
        try:
            data = json.loads(WORKSPACE_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=500, detail="Workspace settings could not be read") from exc
        if not isinstance(data, dict):
            raise HTTPException(status_code=500, detail="Workspace settings have an invalid format")
        return {
            **DEFAULT_WORKSPACE_SETTINGS,
            **{key: value for key, value in data.items() if key in WORKSPACE_SETTINGS_FIELDS},
        }


def write_workspace_settings(settings):
    import json

    with WORKSPACE_SETTINGS_LOCK:
        temporary_path = WORKSPACE_SETTINGS_PATH.with_name(
            f".{WORKSPACE_SETTINGS_PATH.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            WORKSPACE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
            temporary_path.replace(WORKSPACE_SETTINGS_PATH)
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Workspace settings could not be saved") from exc


def register_dataset(dataset):
    with DATASET_REGISTRY_LOCK:
        registry = read_dataset_registry()
        registry["datasets"].insert(0, dataset)
        DATASET_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATASET_REGISTRY_PATH.with_suffix(".tmp.json")
        import json
        try:
            tmp.write_text(json.dumps(registry, indent=2), encoding="utf-8")
            os.replace(tmp, DATASET_REGISTRY_PATH)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Could not persist dataset registry") from exc


def validate_dataset_frame(frame):
    if frame.empty:
        raise HTTPException(status_code=422, detail="Dataset contains no rows")
    required_columns = {"record_id", "first_name", "last_name"}
    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise HTTPException(
            status_code=422,
            detail=f"Dataset is missing required columns: {', '.join(missing_columns)}",
        )
    record_ids = frame["record_id"].astype("string").str.strip()
    if record_ids.isna().any() or record_ids.eq("").any():
        raise HTTPException(status_code=422, detail="Dataset contains missing record_id values")
    if record_ids.duplicated().any():
        raise HTTPException(status_code=422, detail="Dataset contains duplicate record_id values")


def get_predictions():
    global _predictions_df

    if _predictions_df is None and PREDICTIONS_PATH.exists():
        _predictions_df = pd.read_parquet(PREDICTIONS_PATH)

    return _predictions_df


def get_customers():
    global _customers_df

    if _customers_df is None and PROCESSED_DATA_PATH.exists():
        _customers_df = pd.read_parquet(PROCESSED_DATA_PATH)

    return _customers_df



@app.get("/api/pair/{id1}/{id2}")
def pair_detail(id1: str, id2: str, request: Request):
    """Get prediction evidence and original customer records."""
    require_api_key(request)

    predictions = get_predictions()
    customers = get_customers()

    if predictions is None:
        raise HTTPException(
            status_code=404,
            detail="Prediction data not found"
        )

    if customers is None:
        raise HTTPException(
            status_code=404,
            detail="Processed customer data not found"
        )

    # Find the exact pair, regardless of pair orientation.
    mask = (
        (
            (predictions["record_id_l"] == id1) &
            (predictions["record_id_r"] == id2)
        ) |
        (
            (predictions["record_id_l"] == id2) &
            (predictions["record_id_r"] == id1)
        )
    )

    pair_rows = predictions[mask]

    if pair_rows.empty:
        raise HTTPException(
            status_code=404,
            detail="Pair not found"
        )

    if len(pair_rows) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple prediction rows found for this pair"
        )

    pair = pair_rows.iloc[0]

    # Lookup both customer records.
    customer_index = customers.set_index("record_id", drop=False)

    if id1 not in customer_index.index or id2 not in customer_index.index:
        raise HTTPException(
            status_code=404,
            detail="One or both customer records were not found"
        )

    record_a = customer_index.loc[id1]
    record_b = customer_index.loc[id2]

    # Convert pandas/numpy values into JSON-safe Python values.
    def clean_value(value):
        if pd.isna(value):
            return None

        if isinstance(value, np.generic):
            return value.item()

        if isinstance(value, pd.Timestamp):
            return value.isoformat()

        return value

    customer_fields = [
        "record_id",
        "customer_id",
        "first_name",
        "last_name",
        "email",
        "phone_number",
        "gender",
        "dob",
        "address",
        "city",
        "state",
        "country",
    ]

    evidence_fields = [
        "match_weight",
        "match_probability",
        "gamma_name",
        "gamma_contact",
        "gamma_location",
        "gamma_dob",
        "match_key",
        "business_rule",
        "first_name_std_l",
        "first_name_std_r",
        "last_name_std_l",
        "last_name_std_r",
        "email_std_l",
        "email_std_r",
        "phone_std_l",
        "phone_std_r",
        "city_std_l",
        "city_std_r",
        "address_std_l",
        "address_std_r",
        "state_std_l",
        "state_std_r",
        "dob_std_l",
        "dob_std_r",
    ]

    def serialize_record(row):
        return {
            field: clean_value(row[field])
            for field in customer_fields
            if field in row.index
        }

    evidence = {
        field: clean_value(pair[field])
        for field in evidence_fields
        if field in pair.index
    }

    return JSONResponse({
        "record_id_l": str(pair["record_id_l"]),
        "record_id_r": str(pair["record_id_r"]),
        "match_probability": clean_value(pair["match_probability"]),
        "decision": str(pair["decision"]),
        "record_a": serialize_record(record_a),
        "record_b": serialize_record(record_b),
        "evidence": evidence,
    })



@app.post("/api/pair/{id1}/{id2}/decision")
def pair_decision(
    id1: str,
    id2: str,
    data: dict,
    request: Request,
    scope: str = Query("full", pattern="^(sample|full)$"),
):
    """Persist a human review decision for a prediction pair."""
    require_api_key(request)

    decision = str(data.get("decision", "")).upper()
    if decision not in {"MATCH", "NON_MATCH", "REVIEW"}:
        raise HTTPException(status_code=422, detail="decision must be MATCH, NON_MATCH, or REVIEW")
    reviewer = str(data.get("reviewer", "")).strip()
    reason = str(data.get("reason", "")).strip()
    if not reviewer:
        raise HTTPException(status_code=422, detail="reviewer is required")
    if decision != "REVIEW" and not reason:
        raise HTTPException(status_code=422, detail="reason is required for MATCH or NON_MATCH")
    request_id = str(data.get("request_id") or uuid.uuid4())

    df = get_predictions()
    if df is None:
        raise HTTPException(status_code=404, detail="Prediction data not found")

    mask = (
        (
            (df["record_id_l"].astype(str) == id1)
            & (df["record_id_r"].astype(str) == id2)
        )
        | (
            (df["record_id_l"].astype(str) == id2)
            & (df["record_id_r"].astype(str) == id1)
        )
    )
    if not mask.any():
        raise HTTPException(status_code=404, detail="Pair not found")
    if int(mask.sum()) > 1:
        raise HTTPException(status_code=409, detail="Multiple prediction rows found for this pair")

    record = df.loc[mask].iloc[0]
    pair_probability = clean_pair_probability(record["match_probability"])
    audit = {
        "request_id": request_id,
        "record_id_l": str(record["record_id_l"]),
        "record_id_r": str(record["record_id_r"]),
        "decision": decision,
        "reviewer": reviewer,
        "reason": reason,
        "scope": scope,
        "match_probability": pair_probability,
        "model_version": read_model_version(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with REVIEW_AUDIT_LOCK:
        audit_result = append_review_audit(audit)

    supabase_sync = sync_review_decision_to_supabase(
        audit["record_id_l"],
        audit["record_id_r"],
        decision,
        reviewer,
        reason,
    )

    return JSONResponse({
        "status": "saved" if audit_result["created"] else "duplicate",
        "record_id_l": audit["record_id_l"],
        "record_id_r": audit["record_id_r"],
        "decision": decision,
        "scope": scope,
        "request_id": request_id,
        "supabase_sync": supabase_sync,
        "audit": audit_result["record"] if not audit_result["created"] else audit,
    })


@app.post("/api/reviews/bulk")
def bulk_pair_decisions(data: dict, request: Request):
    require_api_key(request)
    pair_ids = data.get("pair_ids") or []
    decision = str(data.get("decision", "")).upper()
    reviewer = str(data.get("reviewer", "")).strip()
    reason = str(data.get("reason", "")).strip()
    if not isinstance(pair_ids, list) or not pair_ids:
        raise HTTPException(status_code=422, detail="pair_ids must be a non-empty list")
    if len(pair_ids) > 100:
        raise HTTPException(status_code=422, detail="pair_ids cannot exceed 100")
    if decision not in {"MATCH", "NON_MATCH", "REVIEW"}:
        raise HTTPException(status_code=422, detail="decision must be MATCH, NON_MATCH, or REVIEW")
    if not reviewer:
        raise HTTPException(status_code=422, detail="reviewer is required")
    if decision != "REVIEW" and not reason:
        raise HTTPException(status_code=422, detail="reason is required for MATCH or NON_MATCH")

    results = []
    base_request_id = str(data.get("request_id") or uuid.uuid4())
    with REVIEW_AUDIT_LOCK:
        for pair_id in pair_ids:
            left, separator, right = str(pair_id).partition("__")
            if not separator:
                results.append({"pair_id": pair_id, "status": "invalid"})
                continue
            try:
                pair_request_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{base_request_id}:{pair_id}",
                ))
                result = pair_decision(left, right, {
                    "decision": decision,
                    "reviewer": reviewer,
                    "reason": reason,
                    "request_id": pair_request_id,
                }, request, scope="full")
                payload = __import__("json").loads(result.body)
                results.append({"pair_id": pair_id, "status": payload["status"]})
            except HTTPException as exc:
                results.append({"pair_id": pair_id, "status": "error", "detail": exc.detail})
    return JSONResponse({"status": "completed", "total": len(results), "results": results})


@app.get("/api/reviews/history")
def review_history(request: Request, page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=100)):
    require_api_key(request)
    if not REVIEW_AUDIT_PATH.exists():
        return JSONResponse({"items": [], "total": 0, "page": page, "per_page": per_page})
    import csv
    with REVIEW_AUDIT_PATH.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    rows.reverse()
    start = (page - 1) * per_page
    return JSONResponse({
        "items": rows[start:start + per_page],
        "total": len(rows),
        "page": page,
        "per_page": per_page,
    })


@app.get("/api/reviews/summary")
def review_summary(request: Request):
    require_api_key(request)
    if not REVIEW_AUDIT_PATH.exists():
        return JSONResponse({
            "reviewed_today": 0,
            "agreement_rate": None,
            "total_decisions": 0,
            "last_reviewed_at": None,
        })
    import csv
    with REVIEW_AUDIT_PATH.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    today = datetime.now(timezone.utc).date().isoformat()
    reviewed_today = sum(
        1 for row in rows
        if str(row.get("created_at", "")).startswith(today)
    )
    substantive = [row for row in rows if row.get("decision") in {"MATCH", "NON_MATCH"}]
    matches = sum(1 for row in substantive if row.get("decision") == "MATCH")
    agreement_rate = (matches / len(substantive)) if substantive else None
    timestamps = [row.get("created_at") for row in rows if row.get("created_at")]
    return JSONResponse({
        "reviewed_today": reviewed_today,
        "agreement_rate": agreement_rate,
        "total_decisions": len(rows),
        "last_reviewed_at": max(timestamps) if timestamps else None,
    })


@app.get("/api/settings/workspace")
def get_workspace_settings(request: Request):
    require_api_key(request)
    return JSONResponse({"settings": read_workspace_settings()})


@app.put("/api/settings/workspace")
def update_workspace_settings(data: dict, request: Request):
    require_api_key(request)
    unknown_fields = set(data) - WORKSPACE_SETTINGS_FIELDS
    if unknown_fields:
        raise HTTPException(status_code=422, detail="Unsupported workspace settings field")

    settings = {**read_workspace_settings(), **data}
    for field in ("workspace_name", "timezone"):
        value = settings[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 100:
            raise HTTPException(status_code=422, detail=f"{field} must be a non-empty string of at most 100 characters")
        settings[field] = value.strip()
    if not isinstance(settings["default_landing_page"], str) or settings["default_landing_page"] not in {"dashboard", "processing", "review"}:
        raise HTTPException(status_code=422, detail="default_landing_page is invalid")
    if not isinstance(settings["date_format"], str) or settings["date_format"] not in {"DD MMM YYYY", "YYYY-MM-DD", "MM/DD/YYYY"}:
        raise HTTPException(status_code=422, detail="date_format is invalid")
    if not isinstance(settings["theme"], str) or settings["theme"] not in {"light", "dark"}:
        raise HTTPException(status_code=422, detail="theme is invalid")
    for field in (
        "preserve_source_data",
        "require_output_confirmation",
        "keep_processing_audit_trail",
    ):
        if type(settings[field]) is not bool:
            raise HTTPException(status_code=422, detail=f"{field} must be a boolean")

    write_workspace_settings(settings)
    return JSONResponse({"settings": settings})


@app.get("/api/datasets")
def list_datasets(request: Request):
    require_api_key(request)
    if not DATASET_REGISTRY_PATH.exists():
        return JSONResponse({"datasets": [], "total": 0})
    import json
    registry = json.loads(DATASET_REGISTRY_PATH.read_text(encoding="utf-8"))
    return JSONResponse({"datasets": registry.get("datasets", []), "total": len(registry.get("datasets", []))})


SUPABASE_TABLES = [
    "customers",
    "dedup_outputs",
    "review_queue_records",
    "entity_map",
    "entity_membership",
    "entity_conflict",
    "master_customer_current",
    "processed_customers",
]


@app.get("/api/supabase/status")
def supabase_status(request: Request):
    require_api_key(request)

    try:
        from api.db import get_supabase_connection

        with get_supabase_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT current_database(), current_schema()
                """)
                database, schema = cursor.fetchone()

                cursor.execute("""
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                """)
                table_count = cursor.fetchone()[0]

        return JSONResponse({
            "status": "connected",
            "database": database,
            "schema": schema,
            "table_count": table_count,
        })

    except Exception as exc:
        return JSONResponse({
            "status": "unavailable",
            "schema": "public",
            "error": type(exc).__name__,
        }, status_code=503)


@app.get("/api/supabase/tables")
def supabase_tables(request: Request):
    require_api_key(request)

    try:
        from api.db import get_supabase_connection

        with get_supabase_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """)

                tables = [row[0] for row in cursor.fetchall()]

        return JSONResponse({
            "tables": tables,
            "total": len(tables),
        })

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Supabase unavailable: {type(exc).__name__}"
        )


@app.get("/api/supabase/datasets")
def supabase_datasets(request: Request):
    require_api_key(request)

    try:
        from api.db import get_supabase_connection
        from psycopg2 import sql

        datasets = []

        with get_supabase_connection() as conn:
            with conn.cursor() as cursor:
                for table in SUPABASE_TABLES:
                    cursor.execute(
                        sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                            sql.Identifier("public"),
                            sql.Identifier(table),
                        )
                    )

                    datasets.append({
                        "name": table,
                        "source": "Supabase",
                        "rows": cursor.fetchone()[0],
                        "status": "Available",
                    })

        return JSONResponse({
            "datasets": datasets,
            "total": len(datasets),
        })

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Supabase unavailable: {type(exc).__name__}"
        )

@app.get("/api/supabase/tables/{table}/columns")
def supabase_table_columns(table: str, request: Request):
    require_api_key(request)
    if table not in SUPABASE_TABLES:
        raise HTTPException(status_code=404, detail="Table not found in Supabase allowlist")

    try:
        from api.db import get_supabase_connection
        with get_supabase_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (table,),
                )
                rows = cursor.fetchall()

        if not rows:
            raise HTTPException(status_code=404, detail="Table not found in schema public")

        columns = [
            {"name": r[0], "type": r[1], "nullable": r[2] == "YES"}
            for r in rows
        ]
        return JSONResponse({
            "schema": "public",
            "table": table,
            "columns": columns,
            "total": len(columns),
        })

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Supabase unavailable: {type(exc).__name__}"
        )


@app.get("/api/supabase/tables/{table}/preview")
def supabase_table_preview(
    table: str,
    request: Request,
    limit: int = Query(25, ge=1, le=100),
):
    require_api_key(request)
    if table not in SUPABASE_TABLES:
        raise HTTPException(status_code=404, detail="Table not found in Supabase allowlist")

    try:
        from api.db import get_supabase_connection
        from psycopg2 import sql
        import decimal

        with get_supabase_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                query = sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
                    sql.Identifier("public"),
                    sql.Identifier(table),
                )
                cursor.execute(query, (limit,))
                col_names = [desc[0] for desc in cursor.description] if cursor.description else []
                raw_rows = cursor.fetchall()

        # Konversi tipe data agar JSON-safe
        def serialize_val(val):
            if val is None:
                return None
            if isinstance(val, (datetime, pd.Timestamp)):
                return val.isoformat()
            if hasattr(val, "isoformat"):
                return val.isoformat()
            if isinstance(val, decimal.Decimal):
                return float(val) if (val % 1) else int(val)
            if isinstance(val, (np.generic,)):
                return val.item()
            if isinstance(val, bytes):
                return val.decode("utf-8", errors="replace")
            return val

        records = [
            {col: serialize_val(val) for col, val in zip(col_names, row)}
            for row in raw_rows
        ]

        return JSONResponse({
            "schema": "public",
            "table": table,
            "columns": col_names,
            "rows": records,
            "total_previewed": len(records),
            "limit": limit,
        })

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Supabase preview failed: {type(exc).__name__}"
        )


@app.post("/api/supabase/ingest")
def supabase_ingest(data: dict, request: Request):
    require_api_key(request)
    table = str(data.get("table", "")).strip()
    limit = data.get("limit", 5000)
    if not table:
        raise HTTPException(status_code=422, detail="table is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 50000:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 50000")

    allowed_ingest_tables = {
        "customers",
        "processed_customers",
    }
    if table not in allowed_ingest_tables:
        raise HTTPException(
            status_code=422,
            detail=f"Table is not allowlisted for ingest. Allowed: {sorted(allowed_ingest_tables)}"
        )

    try:
        from api.db import get_supabase_connection
        from psycopg2 import sql

        with get_supabase_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                query = sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
                    sql.Identifier("public"),
                    sql.Identifier(table),
                )
                cursor.execute(query, (limit,))
                columns = [
                    description.name if hasattr(description, "name") else description[0]
                    for description in cursor.description
                ]
                rows = cursor.fetchall()
        frame = pd.DataFrame(rows, columns=columns)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Supabase ingest failed: {type(exc).__name__}")

    if frame.empty:
        return JSONResponse({"status": "empty", "table": table, "rows": 0})

    validate_dataset_frame(frame)

    DATASET_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dataset_id = f"SB-{uuid.uuid4().hex[:8].upper()}"
    target = DATASET_UPLOAD_DIR / f"{dataset_id}.csv"
    tmp_target = target.with_suffix(".tmp")
    dataset = {
        "id": dataset_id,
        "name": f"{table} (Supabase)",
        "filename": target.name,
        "rows": len(frame),
        "columns": len(frame.columns),
        "status": "Validated",
        "source": "Supabase",
        "table": table,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    try:
        frame.to_csv(tmp_target, index=False)
        os.replace(tmp_target, target)
        register_dataset(dataset)
    except Exception as exc:
        tmp_target.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Could not persist ingested dataset") from exc

    return JSONResponse({"status": "ingested", "dataset": dataset})


@app.get("/api/activity")
def get_activity_feed(request: Request, limit: int = Query(15, ge=1, le=50)):
    """Unified audit activity feed for workspace dashboard."""
    require_api_key(request)
    feed = []

    # 1. Review decisions audit
    if REVIEW_AUDIT_PATH.exists():
        import csv
        with REVIEW_AUDIT_PATH.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        for row in rows[-limit:]:
            feed.append({
                "type": "review",
                "title": f"Review: {row.get('decision')} on {row.get('record_id_l')} ↔ {row.get('record_id_r')}",
                "detail": f"By {row.get('reviewer', 'unknown')} · {row.get('reason', 'No reason')[:60]}",
                "time": row.get("created_at"),
                "tone": "amber" if row.get("decision") == "REVIEW" else ("mint" if row.get("decision") == "MATCH" else "blue"),
            })

    # 2. Ingested datasets
    if DATASET_REGISTRY_PATH.exists():
        try:
            import json
            registry = json.loads(DATASET_REGISTRY_PATH.read_text(encoding="utf-8"))
            for ds in registry.get("datasets", [])[:limit]:
                feed.append({
                    "type": "dataset",
                    "title": f"Dataset {ds.get('name')}",
                    "detail": f"Source: {ds.get('source', 'Upload')} · {ds.get('rows', 0)} records",
                    "time": ds.get("updated"),
                    "tone": "blue",
                })
        except Exception:
            pass

    # 3. Processing runs
    if JOB_REGISTRY_PATH.exists():
        try:
            import json
            job_reg = json.loads(JOB_REGISTRY_PATH.read_text(encoding="utf-8"))
            for j in job_reg.get("jobs", [])[:limit]:
                feed.append({
                    "type": "run",
                    "title": f"Run {j.get('id')}",
                    "detail": f"Dataset: {j.get('dataset_name', j.get('dataset_id'))} · Status: {j.get('status')}",
                    "time": j.get("created_at"),
                    "tone": "violet",
                })
        except Exception:
            pass

    # Sort descending by time
    def parse_time(item):
        t = item.get("time")
        if not t:
            return ""
        return str(t)

    feed.sort(key=parse_time, reverse=True)
    return JSONResponse({"activities": feed[:limit], "total": len(feed)})


@app.get("/api/supabase/entities")
def supabase_entities(request: Request, limit: int = Query(50, ge=1, le=200)):
    """List resolved entities and their master customer representation."""
    require_api_key(request)
    try:
        from api.db import get_supabase_connection
        with get_supabase_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(
                    """
                    SELECT
                        em.entity_id,
                        em.master_record_id,
                        em.entity_status,
                        em.created_at,
                        em.updated_at,
                        mc.first_name,
                        mc.last_name,
                        mc.email,
                        mc.phone_number,
                        mc.city,
                        (SELECT COUNT(*) FROM public.entity_membership mem WHERE mem.entity_id = em.entity_id) as member_count
                    FROM public.entity_map em
                    LEFT JOIN public.master_customer_current mc ON em.master_record_id = mc.source_record_id
                    ORDER BY em.entity_id
                    LIMIT %s
                    """,
                    (limit,),
                )
                columns = [
                    "entity_id", "master_record_id", "entity_status", "created_at", "updated_at",
                    "first_name", "last_name", "email", "phone_number", "city", "member_count"
                ]
                rows = cur.fetchall()

        records = []
        for r in rows:
            d = dict(zip(columns, r))
            d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
            d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
            records.append(d)

        return JSONResponse({"entities": records, "total": len(records)})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to fetch entities: {type(exc).__name__}: {exc}")


@app.get("/api/supabase/entities/{entity_id}/members")
def supabase_entity_members(entity_id: str, request: Request):
    """List records associated with a specific resolved entity cluster."""
    require_api_key(request)
    try:
        from api.db import get_supabase_connection
        with get_supabase_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(
                    """
                    SELECT
                        mem.entity_id,
                        mem.record_id,
                        mem.membership_source,
                        mem.created_at,
                        c.first_name,
                        c.last_name,
                        c.email,
                        c.phone_number,
                        c.dob,
                        c.address,
                        c.city,
                        c.state,
                        c.country
                    FROM public.entity_membership mem
                    LEFT JOIN public.customers c ON mem.record_id = c.record_id
                    WHERE mem.entity_id = %s
                    ORDER BY mem.record_id
                    """,
                    (entity_id,),
                )
                columns = [
                    "entity_id", "record_id", "membership_source", "created_at",
                    "first_name", "last_name", "email", "phone_number", "dob",
                    "address", "city", "state", "country"
                ]
                rows = cur.fetchall()

        records = []
        for r in rows:
            d = dict(zip(columns, r))
            d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
            d["dob"] = d["dob"].isoformat() if d["dob"] else None
            records.append(d)

        return JSONResponse({"entity_id": entity_id, "members": records, "total": len(records)})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to fetch entity members: {type(exc).__name__}: {exc}")


@app.get("/api/supabase/conflicts")
def supabase_conflicts(request: Request):
    """List unresolved or documented entity conflicts."""
    require_api_key(request)
    try:
        from api.db import get_supabase_connection
        with get_supabase_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(
                    """
                    SELECT conflict_id, entity_id, record_id_l, record_id_r, conflict_type, description, status, created_at
                    FROM public.entity_conflict
                    ORDER BY created_at DESC
                    """
                )
                columns = ["conflict_id", "entity_id", "record_id_l", "record_id_r", "conflict_type", "description", "status", "created_at"]
                rows = cur.fetchall()

        records = []
        for r in rows:
            d = dict(zip(columns, r))
            d["conflict_id"] = str(d["conflict_id"])
            d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
            records.append(d)

        return JSONResponse({"conflicts": records, "total": len(records)})
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to fetch conflicts: {type(exc).__name__}: {exc}")


@app.get("/api/database/status")
def database_status(request: Request):
    """Read-only health check for the local PostgreSQL source."""
    require_api_key(request)
    try:
        from src.db import get_connection
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_schema()")
                db, schema = cursor.fetchone()
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
                )
                table_count = cursor.fetchone()[0]
        return JSONResponse({"status": "connected", "database": db, "schema": schema, "table_count": table_count})
    except Exception as exc:
        return JSONResponse({"status": "unavailable", "error": type(exc).__name__}, status_code=503)


@app.get("/api/database/tables")
def database_tables(request: Request):
    """List all ingestible tables exposed to the Nexus workspace."""
    require_api_key(request)
    allowed = [
        "customers", "processed_customers", "customers_synthetic_test", "master_customers",
    ]
    try:
        from src.db import get_connection
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name",
                    ("splink_data",),
                )
                available = {row[0] for row in cursor.fetchall()}
        exposed = [t for t in allowed if t in available]
        return JSONResponse({"tables": exposed, "total": len(exposed)})
    except Exception as exc:
        return JSONResponse({"tables": [], "total": 0, "error": type(exc).__name__}, status_code=503)


@app.get("/api/database/tables/{table}/columns")
def database_table_columns(table: str, request: Request):
    require_api_key(request)
    try:
        from src.db import get_connection
        with get_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s "
                    "ORDER BY ordinal_position",
                    ("splink_data", table),
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {type(exc).__name__}",
        ) from exc
    if not rows:
        raise HTTPException(status_code=404, detail="Table not found")
    columns = [
        {"name": row[0], "type": row[1], "nullable": row[2] == "YES"}
        for row in rows
    ]
    return JSONResponse({
        "schema": "splink_data",
        "table": table,
        "columns": columns,
        "total": len(columns),
    })


@app.post("/api/database/ingest")
def database_ingest(data: dict, request: Request):
    require_api_key(request)
    table = str(data.get("table", "")).strip()
    limit = data.get("limit", 5000)
    if not table:
        raise HTTPException(status_code=422, detail="table is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 50000:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 50000")
    allowed_tables = {
        "customers",
        "processed_customers",
        "customers_synthetic_test",
        "master_customers",
    }
    if table not in allowed_tables:
        raise HTTPException(status_code=422, detail="Table is not allowlisted for ingest")

    try:
        from src.db import get_connection
        with get_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute(
                    f'SELECT * FROM "splink_data"."{table}" LIMIT %s',
                    (limit,),
                )
                columns = [
                    description.name if hasattr(description, "name") else description[0]
                    for description in cursor.description
                ]
                rows = cursor.fetchall()
            finally:
                cursor.close()
        frame = pd.DataFrame(rows, columns=columns)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database ingest failed: {type(exc).__name__}")

    if frame.empty:
        return JSONResponse({"status": "empty", "table": table, "rows": 0})

    validate_dataset_frame(frame)

    DATASET_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dataset_id = f"DB-{uuid.uuid4().hex[:8].upper()}"
    target = DATASET_UPLOAD_DIR / f"{dataset_id}.csv"
    tmp_target = target.with_suffix(".tmp")
    dataset = {
        "id": dataset_id,
        "name": f"{table} (database)",
        "filename": target.name,
        "rows": len(frame),
        "columns": len(frame.columns),
        "status": "Validated",
        "source": "PostgreSQL",
        "table": table,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    try:
        frame.to_csv(tmp_target, index=False)
        os.replace(tmp_target, target)
        register_dataset(dataset)
    except Exception as exc:
        tmp_target.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Could not persist ingested dataset") from exc
    return JSONResponse({"status": "ingested", "dataset": dataset})


@app.post("/api/datasets/upload")
async def upload_dataset(request: Request, file: UploadFile = File(...)):
    require_api_key(request)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".csv", ".parquet"}:
        raise HTTPException(status_code=400, detail="Only CSV or Parquet files are supported")

    DATASET_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dataset_id = f"DS-{uuid.uuid4().hex[:8].upper()}"
    target = DATASET_UPLOAD_DIR / f"{dataset_id}{suffix}"
    target.write_bytes(content)
    try:
        frame = pd.read_parquet(target) if suffix == ".parquet" else pd.read_csv(target)

        validate_dataset_frame(frame)

        # Check active model columns for uploaded datasets only.
        # DB ingest datasets bypass this endpoint entirely.
        from src.standardize import standardize
        model_file = None
        if MODEL_PATH.exists():
            try:
                pointer = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
                model_file = Path(pointer.get("path", "")) / "model.json"
            except (OSError, ValueError):
                model_file = None
        if model_file and model_file.exists():
            model = json.loads(model_file.read_text(encoding="utf-8"))
            model_text = json.dumps(model.get("comparisons", []) + model.get("blocking_rules_to_generate_predictions", []))
            required = set(__import__("re").findall(r"\b[a-z_]+_std\b", model_text))
            unavailable = required - set(standardize(frame).columns)
            if unavailable:
                raise HTTPException(
                    status_code=422,
                    detail=f"Dataset cannot run active model; missing standardized columns: {', '.join(sorted(unavailable))}",
                )

        dataset = {
            "id": dataset_id,
            "name": file.filename,
            "filename": target.name,
            "rows": len(frame),
            "columns": len(frame.columns),
            "status": "Validated",
            "updated": datetime.now(timezone.utc).isoformat(),
        }
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Invalid dataset file: {exc}")

    try:
        register_dataset(dataset)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    return JSONResponse({"status": "uploaded", "dataset": dataset})


@app.post("/api/jobs")
def create_job(request: Request, data: dict):
    require_api_key(request)
    global _predictions_df, _customers_df
    dataset_id = str(data.get("dataset_id", "")).strip()
    if not dataset_id:
        raise HTTPException(status_code=422, detail="dataset_id is required")
    registry = read_dataset_registry()
    datasets = {item["id"]: item for item in registry["datasets"] if "id" in item}
    if dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="Dataset not found")

    dataset = datasets[dataset_id]
    file_path = DATASET_UPLOAD_DIR / dataset.get("filename", f"{dataset_id}.csv")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Dataset file not found on disk")

    import time
    started = time.perf_counter()
    job_id = f"RUN-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    try:
        suffix = file_path.suffix.lower()
        if suffix == ".parquet":
            df_raw = pd.read_parquet(file_path)
        else:
            df_raw = pd.read_csv(file_path)

        validate_dataset_frame(df_raw)

        from src.standardize import standardize
        from src.splink_model import add_decision, apply_business_rules
        from splink import DuckDBAPI, Linker

        std_df = standardize(df_raw)

        from splink import SettingsCreator
        valid_cols = infer_selected_columns_from_df(std_df)
        config = build_dynamic_settings_from_columns(valid_cols)
        model_settings = SettingsCreator(
            link_type="dedupe_only",
            unique_id_column_name="record_id",
            comparisons=config["comparisons"],
            blocking_rules_to_generate_predictions=config["blocking_rules"],
        )

        db_api = DuckDBAPI()
        sdf = db_api.register(std_df, table_name="input_data")
        linker = Linker(sdf, model_settings)

        pred_df = add_decision(linker.inference.predict().as_pandas_dataframe())
        pred_df = apply_business_rules(pred_df, verbose=False)

        # Results and metadata must describe the same run. Write both together.
        duration = round(time.perf_counter() - started, 2)
        run_meta = {
            "artifact": "splink_predictions",
            "scope": "job",
            "source": dataset_id,
            "job_id": job_id,
            "input_rows": len(df_raw),
            "pairs_scored": len(pred_df),
            "selected_columns": valid_cols,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "runtime_seconds": duration,
        }

        PREDICTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        pred_df.to_parquet(PREDICTIONS_PATH, index=False)
        from src.config import write_meta
        write_meta(PREDICTIONS_PATH, **run_meta)
        _predictions_df = pred_df

        PROCESSED_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        std_df.to_parquet(PROCESSED_DATA_PATH, index=False)
        write_meta(PROCESSED_DATA_PATH, **run_meta)
        _customers_df = std_df

        job_record = {
            "id": job_id,
            "dataset_id": dataset_id,
            "dataset_name": dataset.get("name", dataset_id),
            "status": "Completed",
            "records_count": len(df_raw),
            "pairs_scored": len(pred_df),
            "selected_columns": valid_cols,
            "duration": f"{duration}s",
            "created_at": run_meta["created_at"],
        }

        # Update job registry
        reg = read_job_registry()
        reg["jobs"].insert(0, job_record)
        JOB_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        JOB_REGISTRY_PATH.write_text(__import__("json").dumps(reg, indent=2), encoding="utf-8")

        return JSONResponse({"status": "success", "job": job_record})

    except Exception as exc:
        duration = round(time.perf_counter() - started, 2)
        failed_job = {
            "id": job_id,
            "dataset_id": dataset_id,
            "dataset_name": dataset.get("name", dataset_id),
            "status": "Failed",
            "error": str(exc),
            "duration": f"{duration}s",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        reg = read_job_registry()
        reg["jobs"].insert(0, failed_job)
        JOB_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        JOB_REGISTRY_PATH.write_text(__import__("json").dumps(reg, indent=2), encoding="utf-8")
        raise HTTPException(status_code=500, detail=f"Deduplication pipeline failed: {type(exc).__name__}: {exc}")


@app.get("/api/jobs")
def list_jobs(request: Request, page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=100)):
    require_api_key(request)
    registry = read_job_registry()
    jobs = registry["jobs"]
    start = (page - 1) * per_page
    return JSONResponse({"jobs": jobs[start:start + per_page], "total": len(jobs), "page": page, "per_page": per_page})


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, request: Request):
    require_api_key(request)
    registry = read_job_registry()
    job = next((item for item in registry["jobs"] if item["id"] == job_id), None)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(job)


@app.post("/api/run-dedup")
def run_dedup(
    selected_columns: list[str] | None = None,
    scope: str = Query("sample", pattern="^(sample|full)$"),
    request: Request = None,
    dataset_id: str | None = None,
):

    require_api_key(request)
    if not dataset_id:
        raise HTTPException(
            status_code=422,
            detail="dataset_id is required; seed/demo datasets cannot be executed",
        )
    import json
    if DATASET_REGISTRY_PATH.exists():
        registry = json.loads(DATASET_REGISTRY_PATH.read_text(encoding="utf-8"))
        datasets = {item["id"]: item for item in registry.get("datasets", [])}
    else:
        datasets = {}
    if dataset_id not in datasets:
        raise HTTPException(status_code=404, detail="Dataset not found")
    raise HTTPException(
        status_code=501,
        detail="Uploaded dataset validation is available, but external dataset pipeline execution is not connected",
    )
    import pandas as pd
    from src.config import PROCESSED_DATA_PATH, OUTPUT_DIR, PREDICTIONS_PATH
    from src.load_data import load_data
    
    # --- Validasi dan persiapan kolom ---
    # Muat data untuk melihat kolom yang tersedia
    try:
        df_raw = load_data(full=(scope == "full"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memuat data: {e}")
    
    # Dapatkan daftar kolom standar yang valid
    valid_cols = infer_selected_columns_from_df(df_raw)
    
    selected_columns = list(selected_columns or [])

    # Validasi: jika selected_columns kosong, gunakan semua yang valid
    if not selected_columns:
        selected_columns = valid_cols
        info_msg = f"Tidak ada pemilihan kolom. Menggunakan semua {len(selected_columns)} kolom standar yang tersedia."
    else:
        # Filter selected_columns hanya yang valid
        selected_valid = [c for c in selected_columns if c in valid_cols]
        if not selected_valid:
            return JSONResponse({
                "status": "error",
                "message": f"Tidak ada kolom dari {selected_columns} valid untuk pencocokan. "
                           f"Kolom yang tersedia: {', '.join(valid_cols)}"
            }, status_code=400)
        selected_columns = selected_valid
        info_msg = f"Menggunakan {len(selected_columns)} kolom yang dipilih: {', '.join(selected_columns)}"
    
    # --- Build Splink configuration dari kolom yang dipilih ---
    try:
        config = build_dynamic_settings_from_columns(selected_columns)
    except ValueError as ve:
        return JSONResponse({
            "status": "error",
            "message": str(ve)
        }, status_code=400)
    
    # --- Train & Predict dengan konfigurasi dinamis ---
    from splink import DuckDBAPI, Linker, SettingsCreator
    import time
    
    started = time.perf_counter()
    
    # Register data ke DuckDB API
    db_api = DuckDBAPI()
    sdf = db_api.register_table(df_raw)
    
    # Buat Linker dengan konfigurasi dinamis (tanpa training EM ulang jika sudah ada model)
    # Kita gunakan konfigurasi yang baru dibangun, tapi linker akan estimate params-nya
    linker = Linker(sdf, config["comparisons"], blocking_rules=config["blocking_rules"])
    
    # Estimasi parameter (EM) — gagal → kembalikan error jelas, jangan pakai placeholder
    try:
        linker.training.estimate_u_using_random_sampling(max_pairs=100000, seed=42)
        linker.training.estimate_probability_two_random_records_match(
            DETERMINISTIC_RULES, recall=LAMBDA_RECALL_ASSUMPTION
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Gagal estimasi parameter Splink: {type(e).__name__}: {e}. "
                   "Coba kurangi jumlah kolom atau gunakan scope=sample.",
        )
    
    # Prediksi dan tambahkan decision
    pred_df = add_decision(linker.inference.predict().as_pandas_dataframe())
    pred_df = add_decision_dynamic(pred_df, MATCH_THRESHOLD, REVIEW_THRESHOLD)
    
    # Tambahkan business rules (opsional, tetap pakai kolom standar)
    from src.splink_model import apply_business_rules
    pred_df = apply_business_rules(pred_df, verbose=False)
    
    # Simpan hasil
    out_path = PREDICTIONS_PATH if scope == "full" else (OUTPUT_DIR / "splink_predictions_sample.parquet")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from src.config import atomic_write_parquet
    atomic_write_parquet(pred_df, out_path)
    
    runtime = round(time.perf_counter() - started, 2)
    
    # Hitung statistik
    decisions = pred_df["decision"].value_counts().to_dict()
    total = len(pred_df)
    
    return JSONResponse({
        "status": "success",
        "scope": scope,
        "selected_columns": selected_columns,
        "total_records": len(df_raw),
        "pairs_scored": total,
        "decisions": decisions,
        "match_rate": decisions.get("MATCH", 0) / total if total else 0,
        "review_rate": decisions.get("REVIEW", 0) / total if total else 0,
        "non_match_rate": decisions.get("NON_MATCH", 0) / total if total else 0,
        "runtime_seconds": runtime,
        "message": info_msg,
        "config_summary": {
            "comparisons_count": len(config["comparisons"]),
            "blocking_rules": [r.pattern for r in config["blocking_rules"]] if config["blocking_rules"] else "default"
        }
    })


@app.get("/health")
def health():
    """Health check endpoint."""
    model_version = None
    if MODEL_PATH.exists():
        try:
            import json
            model_version = json.loads(MODEL_PATH.read_text()).get("version")
        except Exception:
            pass
    return {
        "status": "healthy",
        "timestamp": pd.Timestamp.now("UTC").isoformat(),
        "predictions_loaded": _predictions_df is not None,
        "predictions_count": len(_predictions_df) if _predictions_df is not None else 0,
        "model_path_exists": MODEL_PATH.exists(),
        "model_version": model_version,
    }


@app.get("/api/stats")
def stats():
    """Get statistics."""
    df = get_predictions()
    if df is None:
        return JSONResponse({
            "total_pairs": 0,
            "matches": 0,
            "review": 0,
            "non_matches": 0,
            "avg_probability": 0.0,
            "timestamp": pd.Timestamp.now("UTC").isoformat()
        })
    
    return JSONResponse({
        "total_pairs": len(df),
        "matches": int(len(df[df["decision"] == "MATCH"])),
        "review": int(len(df[df["decision"] == "REVIEW"])),
        "non_matches": int(len(df[df["decision"] == "NON_MATCH"])),
        "avg_probability": float(df["match_probability"].mean()),
        "timestamp": pd.Timestamp.now("UTC").isoformat()
    })


@app.get("/api/pairs")
def pairs(
    request: Request,
    status: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    """Get pairs with optional status filter."""
    require_api_key(request)
    df = get_predictions()
    if df is None:
        raise HTTPException(status_code=404, detail="No predictions found")
    
    if status:
        df = df[df["decision"] == status.upper()]
    
    start = (page - 1) * per_page
    end = start + per_page
    
    df_page = df.iloc[start:end]
    return JSONResponse({
        "pairs": df_page[["record_id_l", "record_id_r", "match_probability", "decision"]].to_dict("records"),
        "total": len(df),
        "page": page,
        "per_page": per_page
    })


@app.get("/api/search")
def search(request: Request, q: str = Query("", min_length=1)):
    """Search record by ID."""
    require_api_key(request)
    df = get_predictions()
    if df is None:
        raise HTTPException(status_code=404, detail="No predictions found")
    
    if not q:
        return JSONResponse({"results": []})
    
    mask = (
        df["record_id_l"].astype(str).str.contains(q, na=False, regex=False)
        | df["record_id_r"].astype(str).str.contains(q, na=False, regex=False)
    )
    results = df[mask].head(20)
    
    return JSONResponse({
        "results": [
            {
                "record_id_l": row["record_id_l"],
                "record_id_r": row["record_id_r"],
                "match_probability": float(row["match_probability"]),
                "decision": row["decision"]
            }
            for _, row in results.iterrows()
        ]
    })


@app.post("/api/batch-predict")
async def batch_predict(request: Request, file: UploadFile = File(...)):
    """
    Batch predict from CSV/Parquet file.
    Returns match predictions for all pairs in the file.
    """
    require_api_key(request)
    # Batasi ukuran file (maks 10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File terlalu besar. Maksimal 10MB.")

    # Save uploaded file
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        # Load data
        if file.filename.endswith('.parquet'):
            df = pd.read_parquet(tmp_path)
        elif file.filename.endswith('.csv'):
            df = pd.read_csv(tmp_path)
        else:
            raise HTTPException(status_code=400, detail="Only CSV or Parquet files supported")
        
        # Validasi schema input
        required_cols = ['record_id', 'first_name', 'last_name']
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required columns: {missing}")
        if df.empty:
            raise HTTPException(status_code=400, detail="File tidak memiliki baris data")
        
        # Return summary (actual prediction would require model loading)
        return JSONResponse({
            "status": "received",
            "records_count": len(df),
            "filename": file.filename,
            "message": "Data received. Run scripts/batch_predict.py for full pipeline."
        })
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@app.post("/api/reload")
def reload(request: Request, scope: str = Query("full", pattern="^(sample|full)$")):
    """Reload predictions from disk."""
    require_api_key(request)
    global _predictions_df
    prediction_path = PREDICTIONS_PATH if scope == "full" else (PROJECT_ROOT / "outputs" / "splink_predictions_sample.parquet")
    _predictions_df = pd.read_parquet(prediction_path) if prediction_path.exists() else None
    df = _predictions_df
    return JSONResponse({
        "status": "reloaded",
        "scope": scope,
        "predictions_count": len(df) if df is not None else 0
    })


@app.get("/api/model/info")
def model_info():

    import json
    if not MODEL_PATH.exists():
        return JSONResponse({
            "model_version": None,
            "status": "no_model"
        })
    
    with open(MODEL_PATH) as f:
        model_data = json.load(f)
    
    # models/latest.json memakai key "version" & "created_at"; model run
    # menyimpan threshold di models/<version>/thresholds.json
    version = model_data.get("version") or model_data.get("model_version")
    thresholds_path = Path(model_data.get("path", "")) / "thresholds.json"
    thresholds = {}
    if thresholds_path.exists():
        try:
            thresholds = json.loads(thresholds_path.read_text())
        except Exception:
            pass

    return JSONResponse({
        "model_version": version,
        "created_at": model_data.get("created_at"),
        "trained_at": model_data.get("trained_at") or model_data.get("created_at"),
        "threshold_match": thresholds.get("match_threshold", model_data.get("threshold_match", 0.84)),
        "threshold_review": thresholds.get("review_threshold", model_data.get("threshold_review", 0.35)),
        "status": "loaded"
    })


@app.get("/api/model/versions")
def model_versions(request: Request):
    """Daftar semua versi model yang tersimpan di models/<version>/."""
    require_api_key(request)
    from src.model_lifecycle import list_versions
    return JSONResponse(list_versions())


@app.post("/api/model/retrain")
def model_retrain(request: Request, payload: dict = None):
    """Jalankan retraining pipeline (src.run_all) sebagai proses background."""
    require_api_key(request)
    payload = payload or {}
    reuse_model = payload.get("reuse_model")  # path model lama atau None
    skip_blocking_benchmark = payload.get("skip_blocking_benchmark", False)

    if pipeline_locked():
        return JSONResponse({
            "status": "locked",
            "detail": "Pipeline sedang berjalan, tunggu sampai selesai.",
        }, status_code=409)

    try:
        args = [sys.executable, "-u", "-m", "src.run_all", "--full"]
        if reuse_model:
            args += ["--reuse-model", str(reuse_model)]
        if skip_blocking_benchmark:
            args.append("--skip-blocking-benchmark")

        process = subprocess.Popen(
            args,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8:replace"},
        )

        log_path = OUTPUT_DIR / "retrain.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "wb") as log_fh:
            log_fh.write(b"Retrain dimulai pada " + datetime.now(timezone.utc).isoformat().encode() + b"\n\n")
        _start_tailer(log_path, process)

        return JSONResponse({
            "status": "started",
            "log": str(log_path),
            "pid": process.pid,
        })
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start retrain: {exc}")


@app.post("/api/model/rollback")
def model_rollback(payload: dict, request: Request):
    """Pindahkan pointer latest.json ke versi target."""
    require_api_key(request)
    version = payload.get("version")
    if not version or not isinstance(version, str):
        raise HTTPException(status_code=422, detail="Field 'version' wajib diisi.")
    from src.model_lifecycle import version_dir
    target = version_dir(version)
    meta_file = target / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail=f"Model version tidak ditemukan: {version}")
    previous_version = None
    if MODEL_PATH.exists():
        try:
            previous_version = json.loads(MODEL_PATH.read_text(encoding="utf-8")).get("version")
        except Exception:
            pass
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Gunakan created_at dari metadata versi asli, jangan overwriten dengan waktu sekarang
    new_created_at = datetime.now(timezone.utc).isoformat()
    if meta_file.exists():
        try:
            vmeta = json.loads(meta_file.read_text(encoding="utf-8"))
            if vmeta.get("created_at"):
                new_created_at = vmeta["created_at"]
        except Exception:
            pass
    MODEL_PATH.write_text(json.dumps({
        "version": version,
        "path": str(target),
        "created_at": new_created_at,
        "rolled_back_from": previous_version,
    }, indent=2), encoding="utf-8")
    return JSONResponse({
        "status": "ok",
        "version": version,
        "previous_version": previous_version,
    })


def _start_tailer(log_path: Path, process):
    def tail():
        with open(log_path, "ab") as log_fh:
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                log_fh.write(line)
                log_fh.flush()
        try:
            process.wait(timeout=600)
        except Exception:
            pass
    threading.Thread(target=tail, daemon=True).start()


@app.get("/api/download")
def download_csv(request: Request):
    """Download predictions as CSV file."""
    require_api_key(request)
    df = get_predictions()
    if df is None:
        raise HTTPException(status_code=404, detail="No predictions found")
    if "decision" not in df.columns and "match_probability" in df.columns:
        df = df.copy()
        df["decision"] = df["match_probability"].apply(
            lambda p: "MATCH" if p >= MATCH_THRESHOLD
            else ("REVIEW" if p >= REVIEW_THRESHOLD else "NON_MATCH")
        )
    def csv_stream():
        for index, start in enumerate(range(0, len(df), 5000)):
            chunk = df.iloc[start:start + 5000]
            yield chunk.to_csv(index=False, header=index == 0).encode("utf-8")

    return StreamingResponse(
        csv_stream(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=splink_predictions.csv"},
    )


@app.post("/api/save-outputs")
def save_outputs(data: dict, request: Request):
    """Persist posted records to a NEW table (never the source tables)."""
    require_api_key(request)
    records = data.get("records")
    if not records:
        raise HTTPException(status_code=400, detail="records is empty")
    table = data.get("table", "splink_data.dedup_outputs")
    if not table.replace("_", "").replace(".", "").isalnum():
        raise HTTPException(status_code=400, detail="invalid table name")
    try:
        n = save_to_database(pd.DataFrame(records), table)
    except Exception as e:
        status = 409 if type(e).__name__ == "UniqueViolation" else 500
        raise HTTPException(status_code=status, detail=f"{type(e).__name__}: {e}")
    return JSONResponse({"status": "success", "table": table, "rows": n})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)