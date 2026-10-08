"""Streamlit upload page: validate a new CSV, register it as a batch, re-run.

Flow, in numbered sections on the page:

    1 pilih file -> 2 validasi -> 3 jawab tanggal -> 4 daftarkan + jalankan -> 5 hasil

Rules this page keeps (PRD §8):
- Raw bytes reach data/raw/ ONLY when the register button is clicked. An
  abandoned or re-selected upload leaves nothing on disk.
- A payload whose sha256 is already registered skips registration and only
  re-runs the pipeline, so retrying after a failed run cannot double-count.
- The day/month question is asked when the column gives no evidence; it is
  never guessed, because dob_exact and city_dob depend on the answer.
- The pipeline reuses the last trained model by default (MASTER_CONTEXT §15:
  new data must not silently retrain). Retrain is an explicit checkbox.

Run:
    .venv/Scripts/streamlit run app.py --server.address 0.0.0.0
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import streamlit as st

from src import registry
from src.config import OUTPUT_DIR, PROJECT_ROOT
from src.ui import monitoring_sidebar, page_guide, page_header
from src.validate_upload import validate_file

RAW_DIR = PROJECT_ROOT / "data" / "raw"
RUN_SUMMARY = OUTPUT_DIR / "run_summary.json"
BATCH_REPORT = OUTPUT_DIR / "batch_linkage_report.json"

st.set_page_config(page_title="Upload - Entity Resolution", page_icon="📤", layout="wide")
page_header(
    "Upload Data",
    "Tambahkan data customer baru. Data lama tidak akan hilang atau ditimpa.",
)

with st.expander("Alur proses", expanded=False):
    st.markdown(
        """
Setiap file baru melewati tahap-tahap ini. Data yang sudah ada tidak dihapus.

1. **Pengecekan file** — dicek kolomnya lengkap, format tanggalnya apa.
2. **Pembersihan** — nama, email, nomor telepon dibersihkan supaya bisa dibandingkan. Nilai aslinya tetap disimpan, tidak ditimpa.
3. **Penyaringan** — sistem membagi data ke ribuan kelompok kecil supaya tidak perlu membandingkan semuanya. 12 aturan dipakai sekaligus.
4. **Penilaian** — tiap pasangan yang lolos penyaringan diberi angka peluang 0%–100%.
5. **Keputusan** — peluang 90% ke atas digabung sendiri (setelah Anda menyetujui proposal di halaman Data Batch Baru); yang tidak yakin menunggu Anda.
6. **Pengelompokan** — semua yang sudah digabung dirangkum jadi satu entitas.
7. **Rangkuman** — tiap entitas dapat satu baris profil bersih.

## Cara baca hasilnya

Setiap pasangan record dapat satu peluang dari 0% sampai 100%:

| Peluang | Arti | Yang dilakukan |
| --- | --- | --- |
| 90% ke atas | sangat yakin orang sama | Digabung otomatis |
| 0% sampai 90% | tidak yakin | Masuk antrean, periksa Anda |
| nyaris 0% | yakin dua orang berbeda | Dianggap berbeda orang |

Halaman **Pemeriksaan** (kiri) dipakai untuk menilai satu per satu.
Halaman **Pengaturan Sistem** menyimpan percobaan batas dan perbandingan antar versi model.
Setiap keputusan Anda disimpan dengan bukti per-field, jadi auditnya bisa ditelusuri ulang.
"""
    )


def validate_payload(payload: bytes) -> dict:
    """Validate from a temp file; data/raw/ stays untouched until register."""
    digest = hashlib.sha256(payload).hexdigest()
    cached = st.session_state.get("validation_sha")
    if cached == digest:
        return st.session_state["validation"]
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    try:
        report, _frame = validate_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    st.session_state["validation"] = report
    st.session_state["validation_sha"] = digest
    return report


def run_pipeline(command: list[str]) -> dict:
    """Run and stream the log line by line; a frozen screen for 90s reads as a hang."""
    log_box = st.empty()
    status_box = st.empty()
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
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


def render_last_run() -> None:
    last = st.session_state.get("last_run")
    if not last:
        return
    st.subheader("5 · Hasil")
    if last["returncode"] != 0:
        st.error(
            "Pipeline gagal — batch sudah terdaftar. Perbaiki lalu tekan tombol "
            "jalankan lagi; registrasi dilewati otomatis, tidak dobel."
        )
        with st.expander("Log", expanded=True):
            st.code(last["log"][-6000:])
        return

    st.success(f"Selesai — {last['seconds']} detik.")
    m1, m2 = st.columns(2)
    m1.metric("Runtime", f"{last['seconds']} s")
    m2.metric("Model", last.get("model_version") or "-")
    if last.get("steps"):
        st.caption("Detik per langkah:")
        st.table([{"langkah": s["step"], "detik": s["seconds"]} for s in last["steps"]])

    if last.get("batch_report"):
        br = last["batch_report"]
        st.caption("Angka lintas batch:")
        a, b, c, d = st.columns(4)
        a.metric("Match lintas batch", f"{br['cross_batch_match_pairs']:,}")
        b.metric("Duplikat di batch baru", f"{br['new_batch_internal_pairs']:,}")
        c.metric("Salah gabung", f"{br['wrong_merges']:,}")
        d.metric("entity_id lama berubah", f"{br['old_entity_ids_changed']:,}")

    st.caption("Artifacts:")
    st.caption(
        f"- `outputs/entity_map.parquet` — record → entity\n"
        f"- `outputs/master_customers.parquet` — satu baris per entity\n"
        f"- `outputs/splink_predictions.parquet` — skor semua pasangan\n"
        f"- `data/labels/review_queue.csv` — pasangan yang menunggu manusia"
    )
    st.caption(
        "Next steps: isi kolom `label` (match / no_match) di review_queue.csv, "
        "lalu `python -m src.labels --promote` untuk menaikkan ke gold label."
    )
    with st.expander("Log"):
        st.code(last["log"][-6000:])


monitoring_sidebar()
page_guide(__file__)
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
    report = validate_payload(payload)

    # ---- 2 Validasi
    st.subheader("2 · Validasi")
    info = report["file"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Baris", f"{report['rows']:,}")
    c2.metric("Kolom", report["columns"])
    c3.metric("Delimiter / encoding", f"{info['delimiter']!r} · {info['encoding']}")
    c4.metric("Status", report["status"].upper())

    registered = next(
        (b for b in registry.load()["batches"] if b["sha256"] == digest), None
    )
    if report["blocking"]:
        st.caption("Tidak ada yang disimpan.")
        for reason in report["blocking"]:
            st.error(reason)
        st.stop()
    for reason in report["warnings"]:
        st.warning(reason)
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
    if registered:
        st.info(
            f"File ini sudah terdaftar sebagai `{registered['file']}` "
            f"({registered['rows']:,} baris). Registrasi dilewati."
        )
    if not st.button("Analisis batch", type="primary"):
        st.stop()

    batch = registered
    if batch is None:
        number = max(
            (b["batch_id"] for b in registry.load()["batches"]), default=0
        ) + 1
        while (RAW_DIR / f"batch_{number:04d}.csv").exists():
            number += 1
        dest = RAW_DIR / f"batch_{number:04d}.csv"
        dest.write_bytes(payload)
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

    from src import model_lifecycle

    has_model = model_lifecycle.latest() is not None
    has_entities = (PROJECT_ROOT / "outputs" / "entity_map.parquet").exists()
    if has_model and has_entities:
        command = [sys.executable, "-m", "src.incremental", "--stage"]
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
