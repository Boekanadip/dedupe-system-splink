from __future__ import annotations

import asyncio
import hmac
import os
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily

from .config import MASTER_PATH, PROJECT_ROOT
from .health import ALERTS, build_health

API_KEY = os.getenv("DEDUP_API_KEY", "dev-api-key-ganti-ini")
DEV_MODE = API_KEY.startswith("dev-api-key")
if DEV_MODE:
    print("[WARNING] DEDUP_API_KEY belum diset — API berjalan mode dev (tanpa auth).")

QUEUE_PATH = PROJECT_ROOT / "data" / "labels" / "review_queue.csv"


# ---------------------------------------------------------------- auth
def _authed(request: Request) -> bool:
    if DEV_MODE:
        return True
    return hmac.compare_digest(request.headers.get("X-API-Key", ""), API_KEY)


def _unauth() -> JSONResponse:
    return JSONResponse({"detail": "missing or invalid X-API-Key"}, status_code=401)


# ------------------------------------------------------- duckdb helper
def _query_master(column: str, value: str) -> pd.DataFrame:
    
    allowed = {"record_id", "entity_id"}
    if column not in allowed:
        return pd.DataFrame()
    if not MASTER_PATH.exists():
        return pd.DataFrame()
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT * FROM read_parquet('{MASTER_PATH}') WHERE {column} = ?",
            [value],
        ).fetchdf()
    finally:
        con.close()


def _row_dict(df: pd.DataFrame) -> dict:
    return {k: (None if pd.isna(v) else v) for k, v in df.iloc[0].items()}


def _prometheus_text() -> str:
    h = build_health()
    registry = CollectorRegistry()

    def gauge(name: str, value, help_: str, labels: dict | None = None) -> None:
        if value is None:
            return
        m = GaugeMetricFamily(name, help_, labels=labels or {})
        m.add_metric(labels or [], value)
        registry.register(m)

    model = h["model_output"]
    gauge("dedup_review_queue_pending", model.get("review_queue_pending"),
          "pasangan menunggu review")
    gauge("dedup_model_input_rows", model.get("input_rows"), "record diproses")
    gauge("dedup_pairs_scored", model.get("pairs_scored"), "pasangan discoring")
    gauge("dedup_match_threshold", model.get("match_threshold"), "ambang auto-merge")
    gauge("dedup_review_threshold", model.get("review_threshold"), "ambang review")

    ent = h["entity"]
    gauge("dedup_records", ent.get("records"), "jumlah record")
    gauge("dedup_entities", ent.get("entities"), "jumlah entitas")
    gauge("dedup_largest_entity", ent.get("largest_entity"), "entitas terbesar")
    gauge("dedup_match_edges", ent.get("match_edges"), "match edges")
    gauge("dedup_review_pairs", ent.get("review_pairs"), "pasangan review")

    rates = (h.get("decision_distribution") or {}).get("rates") or {}
    for k, v in rates.items():
        if k == "auto_match_rate":
            gauge("dedup_auto_match_rate", v, "share keputusan auto-match")
        gauge(f"dedup_decision_{k}", v, f"decision rate {k}")

    ceiling = (h.get("decision_distribution") or {}).get("blocking_recall_ceiling")
    gauge("dedup_blocking_recall_ceiling", ceiling, "blocking recall ceiling")

    ev = (h.get("evaluation") or {}).get("at_match_threshold") or {}
    gauge("dedup_precision", ev.get("precision"), "precision")
    gauge("dedup_recall", ev.get("recall"), "recall")
    gauge("dedup_f1", ev.get("f1"), "f1")
    gauge("dedup_tp", ev.get("tp"), "true positives")
    gauge("dedup_fp", ev.get("fp"), "false positives")
    gauge("dedup_fn", ev.get("fn"), "false negatives")

    counts = h.get("alert_counts") or {}
    gauge("dedup_alerts_critical", counts.get("critical", 0), "alert kritis")
    gauge("dedup_alerts_warning", counts.get("warning", 0), "alert peringatan")

    for source, info in (h.get("db_ingestion") or {}).get("watermarks", {}).items():
        gauge("dedup_watermark_age_hours", info.get("age_hours"),
              "umur watermark sumber DB (jam)", {"source": str(source)})

    gauge("dedup_health_status", 1, "kesehatan sistem",
          {"status": h.get("status") or "unknown"})
    return generate_latest(registry).decode("utf-8")


# ------------------------------------------------------- publik: /health
def health(_request: Request) -> Response:
    """Lengkap (bukan cuma 'ok') agar monitor bisa scrape satu endpoint."""
    return JSONResponse(build_health())


# ------------------------------------------- publik: /metrics (teks)
def metrics(_request: Request) -> Response:
    return Response(_prometheus_text(), media_type=CONTENT_TYPE_LATEST)


# ----------------------------------------------------------- /status
def status(request: Request) -> Response:
    if not _authed(request):
        return _unauth()
    h = build_health()
    return JSONResponse({
        "status": h["status"],
        "generated_at": h["generated_at"],
        "thresholds": h["thresholds"],
        "alert_counts": h["alert_counts"],
        "pipeline": {
            "last_run": h["pipeline"]["last_run"],
            "last_job": h["pipeline"]["last_job"],
            "pipeline_locked": h["pipeline"]["pipeline_locked"],
        },
        "model_output": {
            "model_version": h["model_output"]["model_version"],
            "review_queue_pending": h["model_output"]["review_queue_pending"],
            "scope": h["model_output"]["scope"],
        },
        "entity": h["entity"],
        "decision_distribution": h["decision_distribution"],
        "alerts": h["alerts"],
    })


# ----------------------------------------------------- /review-queue
def review_queue(request: Request) -> Response:
    if not _authed(request):
        return _unauth()
    if not QUEUE_PATH.exists():
        return JSONResponse({"items": [], "total": 0})
    q = pd.read_csv(QUEUE_PATH, dtype=str, low_memory=False)
    cols = ["record_id_l", "record_id_r", "stratum", "match_probability",
            "label", "review_status", "reviewer"]
    keep = [c for c in cols if c in q.columns]
    items = q[keep].astype(object).where(pd.notna(q[keep]), None).to_dict("records")
    return JSONResponse({"items": items, "total": len(q)})


# ------------------------------------- POST /review/{pair_id}/label
def review_label(request: Request, pair_id: str) -> Response:
    if not _authed(request):
        return _unauth()
    left, _, right = pair_id.partition("__")
    if not right:
        return JSONResponse({"detail": "pair_id format: record_l__record_r"},
                            status_code=400)

    body = {}
    try:
        body = __import__("json").loads(__import__("asyncio").run(_body(request)))  # noqa
    except Exception:
        body = {}
    
    return _review_label_write(request, left, right)


async def _review_label_async(request: Request, left: str, right: str) -> Response:
    body = await request.json()
    return _review_label_write_body(request, left, right, body)


def _review_label_write(request: Request, left: str, right: str) -> Response:
    
    body = request.scope.get("api_body", {})
    label = str(body.get("label", "")).lower()
    if label not in ("match", "no_match"):
        return JSONResponse({"detail": "label harus 'match' atau 'no_match'"},
                            status_code=400)

    q = pd.read_csv(QUEUE_PATH, dtype=str, low_memory=False)
    mask = (q["record_id_l"] == left) & (q["record_id_r"] == right)
    if not mask.any():
        return JSONResponse({"detail": "pasangan tidak ada di antrean"},
                            status_code=404)

    q.loc[mask, "label"] = label
    q.loc[mask, "review_status"] = "labeled"
    q.loc[mask, "reviewer"] = body.get("reviewer", "api")
    tmp = QUEUE_PATH.with_suffix(".tmp.csv")
    q.to_csv(tmp, index=False)
    os.replace(tmp, QUEUE_PATH)

    import subprocess
    proc = subprocess.run(
        [sys.executable, "-m", "src.labels", "--promote"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=600,
    )
    if proc.returncode != 0:
        return JSONResponse(
            {"detail": "label ditulis tapi promote gagal",
             "stderr": proc.stderr[-300:]},
            status_code=500,
        )
    return JSONResponse({"ok": True, "labeled": int(mask.sum())})


# ------------------------------------------------ /entities, /records
def entity(request: Request, eid: str) -> Response:
    if not _authed(request):
        return _unauth()
    df = _query_master("entity_id", eid)
    if df.empty:
        return JSONResponse({"detail": "entity tidak ditemukan"}, status_code=404)
    return JSONResponse(_row_dict(df))


def record_detail(request: Request, rid: str) -> Response:
    if not _authed(request):
        return _unauth()
    df = _query_master("record_id", rid)
    if df.empty:
        return JSONResponse({"detail": "record tidak ditemukan"}, status_code=404)
    return JSONResponse(_row_dict(df))


# --------------------------------------------------------------- /ingest
async def ingest(request: Request) -> Response:
    if not _authed(request):
        return _unauth()
    body = await request.json() if request.headers.get(
        "content-type", "").startswith("application/json") else {}
    source = body.get("source") or os.getenv("DB_SOURCE")
    table = body.get("table") or os.getenv("DB_TABLE")
    if not source or not table:
        return JSONResponse({"detail": "source dan table wajib (body atau env DB_SOURCE/DB_TABLE)"},
                            status_code=400)
    config = body.get("config") or os.getenv("DEDUP_JOB_CONFIG")
    mode = body.get("mode") or os.getenv("JOB_MODE") or "stage"
    timeout = int(body.get("timeout", 3600))

    cmd = [sys.executable, "-u", "-m", "src.job_run"]
    if config:
        cmd += ["--config", config]
    cmd += ["--source", source, "--table", table, "--mode", mode]
    return await _run_subprocess(cmd, timeout)


async def ingest_apply(request: Request, batch: str) -> Response:
    if not _authed(request):
        return _unauth()
    body = await request.json() if request.headers.get(
        "content-type", "").startswith("application/json") else {}
    timeout = int(body.get("timeout", 600))
    cmd = [sys.executable, "-u", "-m", "src.incremental", "--batch", batch, "--apply"]
    return await _run_subprocess(cmd, timeout)


# ---------------------------------------------------------------- /runs
async def run_pipeline(request: Request) -> Response:
    if not _authed(request):
        return _unauth()
    body = await request.json() if request.headers.get(
        "content-type", "").startswith("application/json") else {}
    timeout = int(body.get("timeout", 3600))
    full = body.get("full", True)
    cmd = [sys.executable, "-u", "-m", "src.run_all", "--full" if full else "--sample"]
    return await _run_subprocess(cmd, timeout)


async def _run_subprocess(cmd: list[str], timeout: int) -> Response:
    started = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8:replace"},
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return JSONResponse({
                "returncode": -1,
                "success": False,
                "error": f"command timed out after {timeout}s",
                "command": " ".join(cmd),
            }, status_code=504)
        elapsed = round(time.perf_counter() - started, 2)
        text = stdout.decode("utf-8", errors="replace") if stdout else ""
        return JSONResponse({
            "returncode": proc.returncode,
            "success": proc.returncode == 0,
            "seconds": elapsed,
            "stdout_tail": text[-4000:] if text else "",
            "command": " ".join(cmd),
        })
    except OSError as exc:
        return JSONResponse({"detail": f"gagal menjalankan command: {exc}"},
                            status_code=500)


# --------------------------------------------------------------- body cache
async def _cache_body(request: Request, call_next):
    """Simpan body JSON ke scope agar handler sinkron (_review_label_write)
    masih bisa membacanya tanpa await."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    request.scope["api_body"] = body
    return await call_next(request)


# ------------------------------------------------------------- app
app = Starlette(routes=[
    Route("/health", health, methods=["GET"]),
    Route("/metrics", metrics, methods=["GET"]),
    Route("/status", status, methods=["GET"]),
    Route("/review-queue", review_queue, methods=["GET"]),
    Route("/review/queue", review_queue, methods=["GET"]),
    Route("/review/{pair_id}/label", review_label, methods=["POST"]),
    Route("/review/{pair_id}", review_label, methods=["POST"]),
    Route("/entities/{eid}", entity, methods=["GET"]),
    Route("/records/{rid}", record_detail, methods=["GET"]),
    Route("/ingest", ingest, methods=["POST"]),
    Route("/ingest/{batch}/apply", ingest_apply, methods=["POST"]),
    Route("/runs", run_pipeline, methods=["POST"]),
], middleware=[])

# Middleware body-cache dipasang manual di bawah agar tidak bergantung urutan import.
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware

app = Starlette(routes=app.routes,
                middleware=[Middleware(BaseHTTPMiddleware, dispatch=_cache_body)])


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.getenv("API_HOST", "0.0.0.0"),
                port=int(os.getenv("API_PORT", "8000")))


if __name__ == "__main__":
    main()
