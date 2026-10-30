"""Run:
    .venv/Scripts/streamlit run app.py --server.address 0.0.0.0
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st

from src import registry, model_lifecycle, db_source
from src.config import OUTPUT_DIR, PROJECT_ROOT
from src.ui import monitoring_sidebar, page_guide, page_header
from src.validate_upload import validate_file, validate_payload

RAW_DIR = PROJECT_ROOT / "data" / "raw"
RUN_SUMMARY = OUTPUT_DIR / "run_summary.json"
BATCH_REPORT = OUTPUT_DIR / "batch_linkage_report.json"

st.set_page_config(page_title="Upload - Entity Resolution", page_icon="📤", layout="wide")
page_header(
    "Upload Data",
    "Tambahkan data customer baru. Data lama tidak akan hilang atau ditimpa.",
)

st.caption("Choose a source: a CSV file or a database table.")
tab_csv, tab_db = st.tabs(["📤 CSV", "📥 Database Connection"])

# Shared state
if "source_type" not in st.session_state:
    st.session_state.source_type = None
if "source_data" not in st.session_state:
    st.session_state.source_data = None
if "last_payload_info" not in st.session_state:
    st.session_state.last_payload_info = None


def run_pipeline(command: list[str]) -> dict:

    log_box = st.empty()
    status_box = st.empty()
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    lines: list[str] = []
    step = "memulai"
    started = time.perf_counter()
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        if line.startswith("== ") and not line.startswith("== src."):
            step = line[3:].strip()
        elapsed = time.perf_counter() - started
        status_box.markdown(f"**{step}** · {elapsed:.0f}s")
        log_box.code("".join(lines[-50:]), language="log")
    returncode = process.wait()
    return {
        "returncode": returncode,
        "seconds": round(time.perf_counter() - started, 1),
        "log": "".join(lines),
        "status_box": status_box,
        "log_box": log_box,
    }


def process_pipeline(date_order: str = "auto", batch_file: str | None = None):

    has_model = model_lifecycle.latest() is not None
    has_entities = (PROJECT_ROOT / "outputs" / "entity_map.parquet").exists()
    if has_model and has_entities:
        command = [sys.executable, "-m", "src.incremental", "--stage"]
        if batch_file:
            command += ["--batch", batch_file]
        st.caption(
            "Batch di-stage: sistem menganalisis dan menulis proposal. "
            "Buka halaman Data Batch Baru untuk verifikasi sebelum digabung."
        )
    else:
        command = [sys.executable, "-m", "src.run_all"]
        st.caption("Belum ada model — run pertama melatih model (full pipeline).")
    if date_order != "auto":
        command += ["--date-order", date_order]
    outcome = run_pipeline(command)
    outcome["status_box"].empty()
    outcome["log_box"].empty()
    if outcome["returncode"] == 0:
        st.success(
            "Analisis selesai. Buka halaman Data Batch Baru untuk melihat proposal "
            "dan menerapkannya."
        )
    else:
        st.error(
            "Analisis gagal — lihat log di atas untuk memperbaikinya, lalu tekan "
            "Analisis batch lagi. Registrasi batch dilewati otomatis."
        )

    summary = (
        json.loads(RUN_SUMMARY.read_text(encoding="utf-8"))
        if RUN_SUMMARY.exists()
        else {}
    )
    batch_result = (
        json.loads(BATCH_REPORT.read_text(encoding="utf-8"))
        if BATCH_REPORT.exists()
        else None
    )
    st.session_state["last_run"] = {
        "returncode": outcome["returncode"],
        "seconds": outcome["seconds"],
        "log": outcome["log"],
        "model_version": summary.get("model_version"),
        "steps": summary.get("steps", []),
        "batch_report": batch_result,
    }
    render_last_run()

def render_last_run():
    last = st.session_state.get("last_run")
    if not last:
        return
    with st.expander("Hasil terakhir", expanded=True):
        st.subheader("Ringkasan")
        if last["returncode"] == 0:
            st.success(f"Selesai dalam {last['seconds']:.1f} detik")
        else:
            st.error(f"Gagal (exit code {last['returncode']})")
        if last.get("model_version"):
            st.caption(f"Model: {last['model_version']}")
        steps = last.get("steps") or []
        if steps:
            st.json(
                {"langkah": [s["step"] for s in steps], "detik": [s["seconds"] for s in steps]}
            )
        with st.expander("Log"):
            st.code(last["log"][-6000:])

with tab_csv:
    st.subheader("1 · Pilih file")
    MAX_UPLOAD_MB = 200
    uploaded = st.file_uploader(
        f"CSV (delimiter ; atau ,), maks {MAX_UPLOAD_MB} MB",
        type="csv",
    )
    if uploaded:
        payload = uploaded.getvalue()
        size_mb = len(payload) / (1024 * 1024)
        if size_mb > MAX_UPLOAD_MB:
            st.error(
                f"File {size_mb:.1f} MB melebihi batas {MAX_UPLOAD_MB} MB. "
                "Tidak ada yang disimpan. Pecah jadi beberapa batch."
            )
            st.stop()
        digest = hashlib.sha256(payload).hexdigest()
        report = validate_payload(payload, name=uploaded.name)
        if report["blocking"]:
            st.caption("Tidak ada yang disimpan.")
            for reason in report["blocking"]:
                st.error(reason)
            st.stop()
        st.session_state.source_type = "csv"
        st.session_state.source_data = {
            "payload": payload,
            "report": report,
            "digest": digest,
            "uploaded_name": uploaded.name,
        }
        st.session_state.last_payload_info = {
            "source": "csv",
            "name": uploaded.name,
            "size_mb": size_mb,
            "digest": digest[:8],
        }

    # Show CSV validation info if we have a CSV source selected
    if st.session_state.source_type == "csv" and st.session_state.source_data:
        data = st.session_state.source_data
        report = data["report"]
        info = report["file"]
        st.subheader("2 · Validasi")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Baris", f"{report['rows']:,}")
        c2.metric("Kolom", report["columns"])
        c3.metric("Delimiter / encoding", f"{info['delimiter']!r} · {info['encoding']}")
        c4.metric("Status", report["status"].upper())
        for reason in report["warnings"]:
            st.warning(reason)

        suggestions = report.get("column_suggestions") or []
        if suggestions:
            st.subheader("2b · Saran nama kolom")
            st.caption(
                "Kolom berikut mirip dengan nama yang diharapkan pipeline. "
                "Pipeline TIDAK memetakan otomatis — peta manual di bawah hanya "
                "catatan konfirmasi, bukan rename."
            )
            confirmed = st.session_state.get("confirmed_column_mapping", {})
            for s in suggestions:
                c1, c2, c3 = st.columns([4, 1, 3])
                c1.write(
                    f"`{s['found_column']}` → `{s['expected_source']}`"
                    f"  ({s['canonical']}, kemiripan {s['similarity']:.2f})"
                )
                key = f"colmap_{s['found_column']}_{s['expected_source']}"
                if c2.button("Pakai", key=key):
                    confirmed[s["expected_source"]] = s["found_column"]
                if s["expected_source"] in confirmed:
                    c3.caption(f"✓ dikonfirmasi → '{confirmed[s['expected_source']]}'")
            if confirmed:
                st.session_state.confirmed_column_mapping = confirmed
                st.json(confirmed)
        nulls = {k: v for k, v in report["null_profile"].items() if v["null_pct"] > 0}
        if nulls:
            st.caption(
                "Null: " + ", ".join(f"{k} {v['null_pct']:.2f}%" for k, v in nulls.items())
            )
        if report["exact_duplicate_rows"]:
            st.info(
                f"{report['exact_duplicate_rows']:,} baris identik persis di dalam batch ini."
            )
        orphans = sorted(
            p.name
            for p in RAW_DIR.glob("batch_*.csv")
            if p.name not in {b["file"] for b in registry.load()["batches"]}
        )
        if orphans:
            st.caption(
                "File lama di data/raw yang tidak terdaftar (tidak dipakai pipeline, "
                "boleh dihapus manual): " + ", ".join(orphans)
            )
        # ---- 3 Tanggal
        st.subheader("3 · Format tanggal")
        dates = report["date_formats"]
        unresolved = {k: v for k, v in dates.items() if v["needs_answer"]}
        date_order = "auto"
        if unresolved:
            st.warning(
                "\n".join(v["question"] for v in unresolved.values())
            )
            date_order = st.radio(
                "Format tanggal yang dipakai file ini:",
                ["dmy", "mdy"],
                index=0,
                help="dmy = 11/04/1988 = 11 April. mdy = 04/11/1988 = 11 April.",
            )
        else:
            name, ev = next(iter(dates.items()))
            st.success(
                f"{name}: terdeteksi sendiri — hari>12 di {ev['day_gt_12']:,} baris, "
                f"bulan>12 di {ev['month_gt_12']:,} → {ev['detected_order']}."
            )
        # ---- 4 Daftar + jalankan
        st.subheader("4 · Daftarkan dan analisis")
        registered = next(
            (b for b in registry.load()["batches"] if b["sha256"] == data["digest"]), None
        )
        if registered:
            st.info(
                f"File ini sudah terdaftar sebagai `{registered['file']}` "
                f"({registered['rows']:,} baris). Registrasi dilewati."
            )
        if not st.button("Analisis batch", type="primary", key="csv_analyze"):
            st.stop()
        batch = registered
        if batch is None:
            number = max(
                (b["batch_id"] for b in registry.load()["batches"]), default=0
            ) + 1
            while (RAW_DIR / f"batch_{number:04d}.csv").exists():
                number += 1
            dest = RAW_DIR / f"batch_{number:04d}.csv"
            dest.write_bytes(data["payload"])
            try:
                batch = registry.register(dest, report["rows"])
            except (SystemExit, FileNotFoundError) as exc:
                dest.unlink(missing_ok=True)
                st.error(str(exc))
                st.stop()
        st.success(
            f"Tersimpan: `{batch['file']}` · {batch['rows']:,} baris · "
            f"{batch['record_id_range'][0]}..{batch['record_id_range'][1]}"
        )
        # Store the batch info for processing
        st.session_state.pending_batch = {
            "file": batch["file"],
            "rows": batch["rows"],
            "date_order": date_order if "date_order" in locals() else "auto",
        }
        # Trigger processing
        process_pipeline(st.session_state.pending_batch["date_order"])

with tab_db:
    st.subheader("1 · Koneksi database")

    default_dsn = os.environ.get(
        "DEDUP_DEFAULT_DSN",
        "postgres://crm_owner:devpassword@127.0.0.1:5432/crm",
    )
    dsn = st.text_input(
        "Connection string (PostgreSQL/MySQL/SQLite)",
        value=default_dsn,
        help="Contoh: postgres://user:pass@host:5432/db atau data/synthetic/crm.duckdb",
    )
    table = ""
    table_options = []
    if dsn:
        try:
            with st.spinner("Mendaftar tabel..."):
                table_options = db_source.list_tables(dsn)
        except Exception as e:
            st.error(f"Gagal membaca tabel: {e}")
            table_options = []
    if table_options:
        table = st.selectbox(
            "Pilih tabel", options=table_options, index=0 if table_options else None
        )
    else:
        table = st.text_input("Nama tabel (kosongkan jika tidak ada tabel terdaftar)")
    
    if dsn and table:
        if st.button("Cek tabel", key="db_check"):
            with st.spinner("Memerikra struktur tabel..."):
                try:

                    report = db_source._check_table(dsn, table)
                    st.session_state.db_table_info = {
                        "dsn": dsn,
                        "table": table,
                        "columns": report["columns"],
                        "missing": report["missing_blocking"],
                        "blocked": report["shape_blocking"],
                        "shape_warnings": report["shape_warnings"],
                    }
                except SystemExit as e:
                    st.error(f"Tabel tidak bisa dipakai: {e}")
                    st.session_state.db_table_info = None
                except Exception as e:
                    st.error(f"Gagal memeriksa tabel: {e}")
                    st.session_state.db_table_info = None
    
    # Show DB validation info if we have checked a table
    if st.session_state.get("db_table_info"):
        info = st.session_state.db_table_info
        st.subheader("2 · Validasi tabel")
        st.write(f"**Tabel:** `{info['table']}`")
        st.write(f"**Sumber:** {info['dsn']}")
        st.write(f"**Kolom yang tersedia:** {len(info['columns'])}")
        if info["missing"]:
            st.error(f"Kolom yang dibutuhkan tidak ada: {', '.join(info['missing'])}")
        else:
            st.success("Semua kolom yang diperlukan tersedia")
        if info["blocked"]:
            st.error(
                "Bentuk data tabel tidak bisa diterima:\n"
                + "\n".join(f"- {b}" for b in info["blocked"])
            )
        if info.get("shape_warnings"):
            st.warning(
                "Peringatan bentuk data (tidak memblokir, tapi menurunkan ketepatan):\n"
                + "\n".join(f"- {w}" for w in info["shape_warnings"])
            )
        with st.expander("Lihat semua kolom"):
            st.json({c: "kolom" for c in info["columns"]})

        suggestions = info.get("column_suggestions") or []
        if suggestions:
            with st.expander(f"Saran nama kolom ({len(suggestions)})"):
                for s in suggestions:
                    st.caption(
                        f"`{s['found_column']}` → `{s['expected_source']}`"
                        f"  ({s['canonical']}, kemiripan {s['similarity']:.2f})"
                    )
        if not info["missing"] and not info["blocked"]:
            st.session_state.source_type = "db"
            st.session_state.source_data = {
                "dsn": info["dsn"],
                "table": info["table"],
            }
            st.session_state.last_payload_info = {
                "source": "db",
                "dsn": info["dsn"][:20] + "...",
                "table": info["table"],
            }
            st.subheader("3 · Ekspor dan analisis")
            date_order_db = st.radio(
                "Format tanggal (jika ada kolom tanggal):",
                ["auto", "dmy", "mdy"],
                index=0,
                horizontal=True,
                key="db_date_order",
            )
            if st.button("Ekspor tabel & jalankan pipeline", type="primary", key="db_export"):
                with st.spinner("Mengekspor tabel ke CSV..."):
                    try:
                        from src.db_export import export_batch

                        result = export_batch(
                            info["dsn"], info["table"], use_watermark=True
                        )
                    except Exception as e:
                        st.error(f"Gagal mengekspor: {e}")
                        st.stop()
                # Proses diluar spinner sehingga log pipeline tidak bertumpuk
                if result["status"] == "noop":
                    st.info(result["message"])
                    st.session_state.pending_batch = None
                    st.stop()
                if result["status"] == "already_registered":
                    st.info(
                        f"{result['message']} Batch `{result['batch_file']}` "
                        f"({result['rows']:,} baris) sudah terdaftar dan tidak "
                        "diproses ulang. Hapus watermark untuk paksa re-export."
                    )
                    st.session_state.pending_batch = None
                    st.stop()
                st.success(
                    f"Tabel diekspor sebagai `{result['batch_file']}` "
                    f"({result['rows']:,} baris)"
                )
                st.session_state.pending_batch = {
                    "file": result["batch_file"],
                    "rows": result["rows"],
                    "date_order": date_order_db,
                }
                process_pipeline(date_order_db, batch_file=result["batch_file"])

monitoring_sidebar()
page_guide(__file__)
render_last_run()