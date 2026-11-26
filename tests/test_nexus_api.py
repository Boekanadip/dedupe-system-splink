"""Direct contract tests for the Nexus FastAPI integration."""

import os
import json
import asyncio
import io
from contextlib import contextmanager

import pandas as pd
import pytest
from fastapi import HTTPException
from starlette.requests import Request

os.environ["DEDUP_API_KEY"] = "nexus-test-key"

import api.app as nexus_api


def authorized_request():
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-api-key", b"nexus-test-key")],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
    })


def test_nexus_health_contract():
    health = nexus_api.health()
    assert health["status"] == "healthy"


def test_nexus_pair_detail_contract(monkeypatch):
    import pandas as pd

    monkeypatch.setattr(nexus_api, "get_predictions", lambda: pd.DataFrame([{
        "record_id_l": "rec_053171", "record_id_r": "rec_069559",
        "match_probability": 0.92, "match_weight": 8.5, "decision": "MATCH",
        "gamma_name": 2, "gamma_contact": 1, "gamma_location": 0, "gamma_dob": 1,
    }]))
    monkeypatch.setattr(nexus_api, "get_customers", lambda: pd.DataFrame([
        {"record_id": "rec_053171", "first_name_std": "Ari", "last_name_std": "W",
         "dob_std": "1990-01-01", "address_std": "Jl. A", "email_std": "a@b.c",
         "phone_std": "08123"},
        {"record_id": "rec_069559", "first_name_std": "Ari", "last_name_std": "W",
         "dob_std": "1990-01-01", "address_std": "Jl. A", "email_std": "a@b.c",
         "phone_std": "08123"},
    ]))
    pair = nexus_api.pair_detail(
        "rec_053171",
        "rec_069559",
        authorized_request(),
    )
    body = json.loads(pair.body)
    assert body["record_a"]
    assert body["record_b"]
    assert "match_probability" in body


def test_nexus_reload_contract():
    reload = nexus_api.reload(authorized_request(), scope="full")
    assert reload.status_code == 200
    body = json.loads(reload.body)
    assert body["scope"] == "full"
    assert body["predictions_count"] >= 0


def test_nexus_review_decision_validation():
    with pytest.raises(HTTPException) as error:
        nexus_api.pair_decision(
            "rec_053171",
            "rec_069559",
            {"decision": "INVALID"},
            authorized_request(),
            scope="full",
        )
    assert error.value.status_code == 422


def test_nexus_pair_requires_api_key():
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
    })
    with pytest.raises(HTTPException) as error:
        nexus_api.pair_detail("rec_053171", "rec_069559", request)
    assert error.value.status_code == 401


def test_nexus_pairs_and_search_require_api_key_and_search_literal_ids(monkeypatch):
    unauthorized = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
    })
    monkeypatch.setattr(
        nexus_api,
        "get_predictions",
        lambda: pytest.fail("prediction data must not be read before authorization"),
    )
    with pytest.raises(HTTPException) as pairs_error:
        nexus_api.pairs(unauthorized)
    with pytest.raises(HTTPException) as search_error:
        nexus_api.search(unauthorized, q="rec")
    assert pairs_error.value.status_code == 401
    assert search_error.value.status_code == 401

    import pandas as pd

    monkeypatch.setattr(
        nexus_api,
        "get_predictions",
        lambda: pd.DataFrame([
            {
                "record_id_l": "rec.1",
                "record_id_r": "other",
                "match_probability": 0.9,
                "decision": "MATCH",
            },
            {
                "record_id_l": "recX1",
                "record_id_r": "other-2",
                "match_probability": 0.8,
                "decision": "REVIEW",
            },
        ]),
    )
    search = json.loads(nexus_api.search(authorized_request(), q="rec.1").body)
    assert len(search["results"]) == 1
    assert search["results"][0]["record_id_l"] == "rec.1"


def test_nexus_review_requires_reviewer_and_reason():
    with pytest.raises(HTTPException) as error:
        nexus_api.pair_decision(
            "rec_053171",
            "rec_069559",
            {"decision": "MATCH", "reviewer": ""},
            authorized_request(),
            scope="full",
        )
    assert error.value.status_code == 422


def test_nexus_workspace_settings_are_validated_and_persisted(monkeypatch, tmp_path):
    settings_path = tmp_path / "workspace_settings.json"
    monkeypatch.setattr(nexus_api, "WORKSPACE_SETTINGS_PATH", settings_path)

    defaults = json.loads(nexus_api.get_workspace_settings(authorized_request()).body)
    assert defaults["settings"]["default_landing_page"] == "dashboard"
    assert not settings_path.exists()

    response = nexus_api.update_workspace_settings(
        {"workspace_name": "QA Workspace", "theme": "dark"},
        authorized_request(),
    )
    saved = json.loads(response.body)["settings"]

    assert saved["workspace_name"] == "QA Workspace"
    assert saved["theme"] == "dark"
    assert saved["timezone"] == "Asia/Jakarta"
    assert json.loads(settings_path.read_text(encoding="utf-8")) == saved


@pytest.mark.parametrize("payload", [
    {"theme": "system"},
    {"preserve_source_data": "false"},
    {"database_password": "must-not-be-persisted"},
])
def test_nexus_workspace_settings_reject_invalid_or_secret_fields(payload):
    with pytest.raises(HTTPException) as error:
        nexus_api.update_workspace_settings(payload, authorized_request())
    assert error.value.status_code == 422


def test_nexus_bulk_review_uses_distinct_idempotency_keys_per_pair(monkeypatch, tmp_path):
    import pandas as pd

    pairs = pd.DataFrame([
        {
            "record_id_l": "left-1",
            "record_id_r": "right-1",
            "match_probability": 0.91,
            "decision": "REVIEW",
        },
        {
            "record_id_l": "left-2",
            "record_id_r": "right-2",
            "match_probability": 0.82,
            "decision": "REVIEW",
        },
    ])
    audit_path = tmp_path / "reviews.csv"
    monkeypatch.setattr(nexus_api, "get_predictions", lambda: pairs)
    monkeypatch.setattr(nexus_api, "REVIEW_AUDIT_PATH", audit_path)
    payload = {
        "pair_ids": ["left-1__right-1", "left-2__right-2"],
        "decision": "MATCH",
        "reviewer": "qa-reviewer",
        "reason": "Bulk QA decision",
        "request_id": "bulk-request-1",
    }

    first = json.loads(
        nexus_api.bulk_pair_decisions(payload, authorized_request()).body
    )
    second = json.loads(
        nexus_api.bulk_pair_decisions(payload, authorized_request()).body
    )
    audit_rows = audit_path.read_text(encoding="utf-8").splitlines()

    assert [item["status"] for item in first["results"]] == ["saved", "saved"]
    assert [item["status"] for item in second["results"]] == ["duplicate", "duplicate"]
    assert len(audit_rows) == 3


def test_nexus_run_requires_dataset_id():
    with pytest.raises(HTTPException) as error:
        nexus_api.run_dedup(
            selected_columns=[],
            scope="sample",
            request=authorized_request(),
            dataset_id=None,
        )
    assert error.value.status_code == 422


def test_nexus_review_summary_contract():
    summary = nexus_api.review_summary(authorized_request())
    body = json.loads(summary.body)
    assert "reviewed_today" in body
    assert "agreement_rate" in body
    assert "total_decisions" in body
    assert "last_reviewed_at" in body


def test_nexus_review_history_contract():
    history = nexus_api.review_history(
        authorized_request(),
        page=1,
        per_page=50,
    )
    body = json.loads(history.body)
    assert "items" in body
    assert "total" in body
    assert body["page"] == 1
    assert body["per_page"] == 50


def test_nexus_jobs_list_contract():
    jobs = nexus_api.list_jobs(authorized_request(), page=1, per_page=50)
    body = json.loads(jobs.body)
    assert "jobs" in body
    assert "total" in body


def test_nexus_create_job_requires_dataset_id():
    with pytest.raises(HTTPException) as error:
        nexus_api.create_job(
            authorized_request(),
            {"dataset_id": "", "table": ""},
        )
    assert error.value.status_code == 422


def test_nexus_create_job_does_not_run_repository_data_for_uploaded_dataset(monkeypatch, tmp_path):
    registry_path = tmp_path / "dataset_registry.json"
    registry_path.write_text(
        json.dumps({"datasets": [{"id": "DS-TEST", "name": "customer upload"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(nexus_api, "DATASET_REGISTRY_PATH", registry_path)
    job_registry_path = tmp_path / "job_registry.json"
    monkeypatch.setattr(nexus_api, "JOB_REGISTRY_PATH", job_registry_path)

    with pytest.raises(HTTPException) as error:
        nexus_api.create_job(
            authorized_request(),
            {"dataset_id": "DS-TEST", "table": "crm_customers"},
        )

    assert error.value.status_code == 404
    assert "Dataset file not found on disk" in error.value.detail
    assert not job_registry_path.exists()


def test_nexus_database_ingest_registers_only_valid_read_only_dataset(monkeypatch, tmp_path):
    import api.db

    class FakeCursor:
        description = [("record_id",), ("first_name",), ("last_name",)]

        def __init__(self):
            self.commands = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            self.commands.append((query, params))

        def fetchall(self):
            return [("r1", "Ari", "Wijaya"), ("r2", "Dewi", "Putri")]

        def close(self):
            pass

    cursor = FakeCursor()

    class FakeConnection:
        def cursor(self):
            return cursor

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    upload_dir = tmp_path / "uploads"
    registry_path = tmp_path / "dataset_registry.json"
    monkeypatch.setattr(api.db, "get_supabase_connection", fake_connection)
    monkeypatch.setattr(nexus_api, "DATASET_UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(nexus_api, "DATASET_REGISTRY_PATH", registry_path)

    response = nexus_api.database_ingest(
        {"table": "customers", "limit": 2},
        authorized_request(),
    )
    body = json.loads(response.body)
    saved = json.loads(registry_path.read_text(encoding="utf-8"))

    assert body["status"] == "ingested"
    assert body["dataset"]["status"] == "Validated"
    assert body["dataset"]["rows"] == 2
    assert saved["datasets"][0]["id"] == body["dataset"]["id"]
    assert len(list(upload_dir.glob("*.csv"))) == 1
    assert cursor.commands[0][0] == "SET TRANSACTION READ ONLY"
    assert "LIMIT %s" in str(cursor.commands[1][0])
    assert cursor.commands[1][1] == (2,)


def test_nexus_database_ingest_rejects_missing_or_duplicate_record_ids(monkeypatch, tmp_path):
    import api.db

    class FakeCursor:
        def __init__(self, columns, rows):
            self.description = [(column,) for column in columns]
            self.rows = rows

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            pass

        def fetchall(self):
            return self.rows

        def close(self):
            pass

    class FakeConnection:
        def __init__(self, cursor):
            self._cursor = cursor

        def cursor(self):
            return self._cursor

    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(nexus_api, "DATASET_UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(
        nexus_api,
        "DATASET_REGISTRY_PATH",
        tmp_path / "dataset_registry.json",
    )

    @contextmanager
    def connection_with(columns, rows):
        yield FakeConnection(FakeCursor(columns, rows))

    monkeypatch.setattr(
        api.db,
        "get_supabase_connection",
        lambda: connection_with(
            ["record_id", "first_name", "last_name"],
            [("r1", "Ari", "Wijaya"), ("r1", "Dewi", "Putri")],
        ),
    )
    with pytest.raises(HTTPException) as duplicate_error:
        nexus_api.database_ingest(
            {"table": "customers"},
            authorized_request(),
        )
    assert duplicate_error.value.status_code == 422
    assert "duplicate record_id" in duplicate_error.value.detail
    assert not upload_dir.exists()

    monkeypatch.setattr(
        api.db,
        "get_supabase_connection",
        lambda: connection_with(
            ["first_name", "last_name"],
            [("Ari", "Wijaya")],
        ),
    )
    with pytest.raises(HTTPException) as schema_error:
        nexus_api.database_ingest(
            {"table": "customers"},
            authorized_request(),
        )
    assert schema_error.value.status_code == 422
    assert "missing required columns: record_id" in schema_error.value.detail


@pytest.mark.parametrize("limit", [0, 50001, "10", True])
def test_nexus_database_ingest_validates_limit_without_database_access(
    monkeypatch,
    limit,
):
    import api.db

    def unexpected_connection():
        pytest.fail("database must not be accessed for invalid limits")

    monkeypatch.setattr(api.db, "get_supabase_connection", unexpected_connection)
    with pytest.raises(HTTPException) as error:
        nexus_api.database_ingest(
            {"table": "customers", "limit": limit},
            authorized_request(),
        )
    assert error.value.status_code == 422


def test_nexus_database_ingest_returns_empty_without_registering_dataset(monkeypatch, tmp_path):
    import api.db

    class FakeCursor:
        description = [("record_id",), ("first_name",), ("last_name",)]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            pass

        def fetchall(self):
            return []

        def close(self):
            pass

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    from contextlib import contextmanager

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    upload_dir = tmp_path / "uploads"
    registry_path = tmp_path / "dataset_registry.json"
    monkeypatch.setattr(api.db, "get_supabase_connection", fake_connection)
    monkeypatch.setattr(nexus_api, "DATASET_UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(nexus_api, "DATASET_REGISTRY_PATH", registry_path)

    response = nexus_api.database_ingest(
        {"table": "customers"},
        authorized_request(),
    )

    assert json.loads(response.body) == {
        "status": "empty",
        "table": "customers",
        "rows": 0,
    }
    assert not upload_dir.exists()
    assert not registry_path.exists()


def test_nexus_database_tables_identifies_ingestible_allowlisted_tables(monkeypatch):
    from fastapi.responses import JSONResponse

    monkeypatch.setattr(
        nexus_api,
        "supabase_tables",
        lambda request: JSONResponse({"tables": ["customers", "external_table"], "total": 2}),
    )

    response = nexus_api.database_tables(authorized_request())
    body = json.loads(response.body)

    # Only allowlisted tables that also exist in DB are returned
    assert body["tables"] == ["customers"]
    assert body["total"] == 1


def test_nexus_database_column_preview_returns_metadata_only(monkeypatch):
    import api.db

    class FakeCursor:
        def __init__(self):
            self.commands = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            self.commands.append((query, params))

        def fetchall(self):
            return [
                ("record_id", "text", "NO"),
                ("email", "text", "YES"),
            ]

        def close(self):
            pass

    cursor = FakeCursor()

    class FakeConnection:
        def cursor(self):
            return cursor

    @contextmanager
    def fake_connection():
        yield FakeConnection()

    monkeypatch.setattr(api.db, "get_supabase_connection", fake_connection)

    response = nexus_api.database_table_columns("customers", authorized_request())
    body = json.loads(response.body)

    assert body["table"] == "customers"
    assert body["total"] == 2
    assert body["columns"] == [
        {"name": "record_id", "type": "text", "nullable": False},
        {"name": "email", "type": "text", "nullable": True},
    ]
    assert cursor.commands[0][0] == "SET TRANSACTION READ ONLY"
    assert cursor.commands[1][1] == ("customers",)


def test_nexus_csv_upload_rejects_dataset_missing_active_model_columns(monkeypatch, tmp_path):
    upload_dir = tmp_path / "uploads"
    registry_path = tmp_path / "dataset_registry.json"
    monkeypatch.setattr(nexus_api, "DATASET_UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(nexus_api, "DATASET_REGISTRY_PATH", registry_path)
    upload = nexus_api.UploadFile(
        io.BytesIO(b"record_id,first_name,last_name\nr1,Ari,Wijaya\n"),
        filename="customers.csv",
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(nexus_api.upload_dataset(authorized_request(), upload))

    assert error.value.status_code == 422
    assert "active model" in error.value.detail
    assert not registry_path.exists()
    assert not list(upload_dir.glob("*"))


def test_nexus_csv_upload_rejects_duplicate_record_ids(monkeypatch, tmp_path):
    upload_dir = tmp_path / "uploads"
    registry_path = tmp_path / "dataset_registry.json"
    monkeypatch.setattr(nexus_api, "DATASET_UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(nexus_api, "DATASET_REGISTRY_PATH", registry_path)

    upload = nexus_api.UploadFile(
        io.BytesIO(
            b"record_id,first_name,last_name\n"
            b"r1,Ari,Wijaya\n"
            b"r1,Dewi,Putri\n"
        ),
        filename="customers.csv",
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(nexus_api.upload_dataset(authorized_request(), upload))

    assert error.value.status_code == 422
    assert "duplicate record_id" in error.value.detail
    assert not list(upload_dir.glob("*.csv"))
    assert not registry_path.exists()


def test_nexus_stats_empty_predictions_are_json_serializable(monkeypatch):
    monkeypatch.setattr(
        nexus_api, "_predictions_df",
        pd.DataFrame({"decision": [], "match_probability": []}),
    )
    payload = json.loads(nexus_api.stats().body)
    assert payload["total_pairs"] == 0
    assert payload["avg_probability"] == 0.0


def test_nexus_retrain_uses_supported_run_all_flags(monkeypatch, tmp_path):
    captured = {}

    class FakeProcess:
        pid = 4242

    def fake_popen(args, **kwargs):
        captured["args"] = args
        return FakeProcess()

    monkeypatch.setattr(nexus_api.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(nexus_api, "pipeline_locked", lambda: False)
    monkeypatch.setattr(nexus_api, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(nexus_api, "_start_tailer", lambda *args, **kwargs: None)

    response = nexus_api.model_retrain(
        authorized_request(), {"skip_blocking_benchmark": True}
    )
    assert response.status_code == 200
    assert "--full" not in captured["args"]
    assert "--skip-blocking-benchmark" in captured["args"]


def test_nexus_retrain_log_returns_bytes_since_offset(monkeypatch, tmp_path):
    log_path = tmp_path / "retrain.log"
    log_path.write_bytes(b"baris satu\nbaris dua\n")
    monkeypatch.setattr(nexus_api, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(nexus_api, "pipeline_locked", lambda: True)

    first = json.loads(nexus_api.retrain_log(authorized_request(), offset=0).body)
    second = json.loads(nexus_api.retrain_log(authorized_request(), offset=11).body)

    assert first["text"] == "baris satu\nbaris dua\n"
    assert second["text"] == "baris dua\n"
    assert first["size"] == len(b"baris satu\nbaris dua\n")
    assert first["running"] is True


def test_nexus_rollback_invalidates_prediction_cache(monkeypatch, tmp_path):
    model_path = tmp_path / "latest.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(nexus_api, "MODEL_PATH", model_path)
    monkeypatch.setattr(nexus_api, "_predictions_df", pd.DataFrame({"a": [1]}))

    version = next(p.name for p in (nexus_api.PROJECT_ROOT / "models").iterdir()
                   if (p / "metadata.json").exists())
    response = nexus_api.model_rollback({"version": version}, authorized_request())

    assert response.status_code == 200
    assert nexus_api._predictions_df is None
