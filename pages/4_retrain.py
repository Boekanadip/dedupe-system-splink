"""Retrain & model management page.

Retraining is deliberately NOT bundled with data entry: it is a separate,
explicit action on its own page. This page also holds model rollback, retrain
history, drift indicators, feedback status, threshold evaluation, A/B
comparison, training provenance, and a promotion checklist.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import LABELS_DIR, OUTPUT_DIR, PROJECT_ROOT
from src.run_all import RUN_SUMMARY_PATH
from src.ui import (
    format_count,
    format_duration,
    format_history_table,
    format_rate,
    format_threshold,
    monitoring_sidebar,
    page_guide,
    page_header,
    stratum_label,
)

import psutil

st.set_page_config(page_title="Model - Entity Resolution", page_icon="⚙️", layout="wide")
page_header(
    "Pengaturan Sistem",
    "Halaman ini tempat mengubah batas kepastian dan melatih ulang sistem. "
    "Semuanya harus diklik manual — sistem tidak pernah mengubah dirinya sendiri.",
)
monitoring_sidebar()
page_guide(__file__)

MODELS_DIR = PROJECT_ROOT / "models"
LOCK = OUTPUT_DIR / ".retraining"
LATEST = MODELS_DIR / "latest.json"


def model_versions() -> list[dict]:
    versions = []
    for d in sorted(MODELS_DIR.glob("v*")):
        meta = d / "metadata.json"
        ev = d / "evaluation.json"
        info = {"version": d.name, "path": d}
        if meta.exists():
            info.update(json.loads(meta.read_text(encoding="utf-8")))
        if ev.exists():
            info["evaluation"] = json.loads(ev.read_text(encoding="utf-8"))
        versions.append(info)
    return versions


def current_version() -> str | None:
    if LATEST.exists():
        return json.loads(LATEST.read_text(encoding="utf-8")).get("version")
    return None


versions = model_versions()
cur = current_version()

# ---- status sekarang
st.subheader("Model yang Sedang Dipakai")
if cur:
    st.success(f"Model aktif: `{cur}`")
else:
    st.warning("Belum ada model. Jalankan dari halaman Upload dulu.")
c1, c2 = st.columns(2)
if versions:
    latest_meta = next((v for v in versions if v["version"] == cur), versions[-1])
    c1.metric("Jumlah record", format_count(latest_meta.get("input_rows", 0)),
              help="Berapa baris data yang dipelajari model ini.")
    c2.metric("Pasangan dibandingkan", format_count(latest_meta.get("pairs_scored", 0)),
              help="Berapa pasangan record yang dinilai model ini.")

# ---- retrain
RETRAIN_LOG = OUTPUT_DIR / "retrain.log"
STALE_SEC = 600


def lock_status() -> tuple[bool, int, bool]:
    """(ada_lock, detik sejak log terakhir tumbuh, pid masih hidup)."""
    if not LOCK.exists():
        return False, 0, False
    ref = RETRAIN_LOG if RETRAIN_LOG.exists() else LOCK
    idle = int(time.time() - ref.stat().st_mtime)
    try:
        pid = int(LOCK.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pid = None
    return True, idle, bool(pid and psutil.pid_exists(pid))


st.subheader("Latih Ulang Model")
st.caption(
    "Jalankan ulang seluruh pipeline di SEMUA data (bukan incremental). "
    "Menghasilkan versi model baru; versi lama tetap tersimpan dan bisa di-rollback."
)


@st.fragment(run_every=2)
def retrain_runner() -> None:
    """Pantau retrain lewat file log, bukan pipe stdout.

    Sebelumnya subprocess di-pipe ke `for line in process.stdout` di dalam
    fragment ber-`run_every`. Rerun fragment memutus loop itu, menutup pipe,
    membunuh proses training di tengah jalan, dan `LOCK.unlink()` tidak pernah
    tercapai — lock basi selamanya. Proses terpisah + log di disk tidak bisa
    dipotong begitu; liveness dicek via PID di lock file.
    """
    locked, idle, alive = lock_status()

    if locked and not alive:
        finished = (RUN_SUMMARY_PATH.exists()
                    and RUN_SUMMARY_PATH.stat().st_mtime > LOCK.stat().st_mtime)
        if finished:
            summary = json.loads(RUN_SUMMARY_PATH.read_text(encoding="utf-8"))
            st.success(f"Retrain selesai — model {summary['model_version']}; "
                       f"total {format_duration(summary['total_seconds'])}.")
            LOCK.unlink(missing_ok=True)
        else:
            st.error(
                f"Pipeline retrain tidak menyelesaikan semua tahap; log diam {idle // 60} menit. "
                "Sebagian artefak atau versi model mungkin sudah berubah. Periksa log sebelum mengulang."
            )
            if st.button("Bersihkan lock", type="primary"):
                LOCK.unlink(missing_ok=True)
                st.rerun()
        if RETRAIN_LOG.exists():
            with st.expander("Log retrain", expanded=not finished):
                st.code(RETRAIN_LOG.read_text(encoding="utf-8", errors="replace")[-4000:], language="log")
        return

    if locked and idle > STALE_SEC:
        st.warning(
            f"Log diam {idle // 60} menit sementara proses masih hidup. "
            "Kalau diam tanpa batas, matikan retrain di terminal dan hapus log, "
            "lalu periksa apakah artefak sebagian terbuat."
        )

    if locked:
        st.info(f"Retrain berjalan — log terakhir {idle}s lalu.")
        if RETRAIN_LOG.exists():
            tail = RETRAIN_LOG.read_text(encoding="utf-8", errors="replace")
            with st.expander("Log retrain", expanded=True):
                st.code(tail[-4000:] if tail else "Menunggu output…", language="log")
        return

    confirmed = st.checkbox(
        "Saya paham retrain akan menghasilkan versi model baru",
        key="retrain_confirm",
        value=False,
    )
    if st.button("Retrain sekarang", type="primary", disabled=not confirmed):
        with open(RETRAIN_LOG, "w", encoding="utf-8") as log_handle:
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.run_all"],
                cwd=PROJECT_ROOT,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
        LOCK.write_text(str(proc.pid), encoding="utf-8")
        st.rerun()


retrain_runner()

# ---- drift
st.subheader("Perubahan sejak model sebelumnya")
ordered = sorted((v for v in versions if v.get("scope") == "full"),
                 key=lambda v: v.get("created_at") or "")
active_index = next((i for i, v in enumerate(ordered) if v["version"] == cur), None)
if active_index:
    prev, last = ordered[active_index - 1], ordered[active_index]
elif len(ordered) >= 2:
    prev, last = ordered[-2], ordered[-1]
else:
    prev = last = None
if prev and last:
    pe = prev.get("evaluation", {}).get("decision_rates", {})
    le = last.get("evaluation", {}).get("decision_rates", {})
    d1, d2 = st.columns(2)
    d1.metric(
        "Digabung otomatis",
        format_rate(le.get("MATCH", 0)),
        delta=format_rate(le.get("MATCH", 0) - pe.get("MATCH", 0)),
        delta_color="normal",
    )
    d2.metric(
        "Perlu diperiksa",
        format_rate(le.get("REVIEW", 0)),
        delta=format_rate(le.get("REVIEW", 0) - pe.get("REVIEW", 0)),
        delta_color="inverse",
    )
    st.caption(
        "Ini hanya hitungan keputusan per versi, BUKAN bukti akurasi. "
        "Gunakan bagian 'Apakah model jadi lebih baik?' di bawah untuk bukti sebanding."
    )
else:
    st.caption("Butuh 2 versi model untuk bisa dibandingkan.")

# ---- perbandingan model (A/B)
st.subheader("Daftar versi model")
if len(versions) >= 2:
    rows = []
    for v in versions:
        ev = v.get("evaluation", {}).get("decision_rates", {})
        rows.append(
            {
                "Versi": v["version"],
                "Lingkup": v.get("scope"),
                "Jumlah record": format_count(v.get("input_rows", 0)),
                "Digabung otomatis": format_rate(ev.get("MATCH", 0)),
                "Perlu diperiksa": format_rate(ev.get("REVIEW", 0)),
                "Berbeda orang": format_rate(ev.get("NON_MATCH", 0)),
                "Waktu proses": format_duration(v.get("runtime_seconds", 0)),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
else:
    st.caption("Butuh 2 versi model.")

st.subheader("Apakah model jadi lebih baik?")
VS_GOLD_PATH = OUTPUT_DIR / "version_gold_scores.json"
if not VS_GOLD_PATH.exists():
    st.caption("Bukti belum dihitung. Jalankan: `python -m src.version_gold_scores` di terminal.")
else:
    report = json.loads(VS_GOLD_PATH.read_text(encoding="utf-8"))
    prov = report.get("provenance", {})
    vs = report.get("versions", [])
    st.caption(report.get("limitation", ""))
    st.caption(
        "Semua versi diukur ulang pada revisi gold dan data bersih yang sama, kandidat sama, "
        f"batas yang sama ({format_threshold(vs[0]['own_match_threshold'] if vs else 0.9)}). "
        "Jadi beda angka adalah beda model, bukan beda data atau batas."
    )
    current_rows = vs[-1].get("trained_on_rows") if vs else None
    for entry in vs:
        rows_trained = entry.get("trained_on_rows")
        if current_rows and rows_trained and rows_trained != current_rows:
            entry["_training_data_note"] = (
                f"dilatih pada {rows_trained:,} baris; dinilai ulang sekarang "
                f"pada {current_rows:,} baris — sebanding untuk model, bukan "
                "untuk snapshot"
            )
    # Same gold, same candidates, same 0.9, one dot per version.
    ref = vs[0]["own_match_threshold"] if vs else 0.9
    f1 = []
    for entry in vs:
        m = entry["clean"][f"at_{ref}"]
        # A model that scores more positives only proves growth if false
        # positives do not rise. Keep both mistake directions visible.
        f1.append({"f1": m["f1"], "tp": m["tp"], "fp": m["fp"], "fn": m["fn"]})
    trend = pd.DataFrame(
        {"waktu": [datetime.fromisoformat(entry["created_at"]) if entry.get("created_at") else None for entry in vs],
         "F1": [row["f1"] for row in f1]}
    ).set_index("waktu")
    st.line_chart(trend)
    first = vs[0] if vs else {}
    clean0 = first.get('clean', {}).get(f"at_{ref}", {})
    incl0 = first.get('including_disputed', {}).get(f"at_{ref}", {})
    st.caption(
        f"Ukuran bukti: {int(prov.get('gold_pairs') or 0):,} pasang yang diperiksa manusia "
        f"({int(prov.get('gold_positive_pairs') or 0):,} benar-benar sama, "
        f"{int(prov.get('gold_disputed_pairs') or 0):,} masih berselisih). "
        f"Posisi bersih terbaru: TP={int(clean0.get('tp', 0) or 0)}, FP={int(clean0.get('fp', 0) or 0)}, "
        f"FN={int(clean0.get('fn', 0) or 0)}, F1={format_rate(clean0.get('f1', 0))}. "
        f"Termasuk berselisih: TP={int(incl0.get('tp', 0) or 0)}, "
        f"FP={int(incl0.get('fp', 0) or 0)}, FN={int(incl0.get('fn', 0) or 0)}, "
        f"F1={format_rate(incl0.get('f1', 0))}. "
        "Model datar karena buktinya belum mampu membedakan data baik dan data kotor."
    )
    with st.expander("Detail: tiap versi pada batas yang sama"):
        detail = pd.DataFrame(
            {
                "versi": [entry["version"] for entry in vs],
                "baris latih": [format_count(entry.get("trained_on_rows")) for entry in vs],
                "batas": [format_threshold(ref) for _ in vs],
                "benar sama": [row["tp"] for row in f1],
                "salah gabung": [row["fp"] for row in f1],
                "terlewat": [row["fn"] for row in f1],
                "F1 bersih": [format_rate(row["f1"]) for row in f1],
                "catatan": [entry.get("_training_data_note", "—") for entry in vs],
            }
        )
        st.dataframe(detail, width="stretch", hide_index=True)

# ---- feedback
st.subheader("Catatan dari pemeriksaan manual")
fb_path = LABELS_DIR / "feedback.csv"
if fb_path.exists():
    fb = pd.read_csv(fb_path)
    verdict = {
        "match": "Orang yang sama",
        "no_match": "Berbeda orang",
    }
    show = fb.tail(20).copy()
    show["pair_id"] = show["pair_id"].astype(str).str.replace("__", " vs ")
    show["human_label"] = show["human_label"].map(lambda v: verdict.get(str(v), str(v)))
    show["model_version"] = show["model_version"].astype(str)
    show = show.rename(columns={
        "pair_id": "Pasangan",
        "human_label": "Keputusan",
        "reviewer": "Diperiksa oleh",
        "model_version": "Model",
        "stratum": "Asal",
    })
    show["Asal"] = show["Asal"].map(lambda v: stratum_label(v))
    st.caption(
        f"Total {len(fb):,} keputusan manual. 20 terakhir ditampilkan di sini. "
        "Keputusan ini dipakai mengukur seberapa tepat sistem bekerja, bukan untuk "
        "melatih model secara diam-diam."
    )
    st.dataframe(
        show[["Pasangan", "Keputusan", "Diperiksa oleh", "Model", "Asal"]],
        width="stretch",
        hide_index=True,
        height=320,
    )
else:
    st.caption("Belum ada catatan pemeriksaan.")

# ---- triage laporan keanggotaan (dari halaman Master)
flags_path = LABELS_DIR / "membership_flags.csv"
if flags_path.exists():
    st.subheader("Laporan Salah Gabung / Salah Pecah")
    flags = pd.read_csv(flags_path)
    flags["status"] = flags["status"].fillna("open").astype(str)
    flags["note"] = flags["note"].where(flags["note"].notna(), "").astype(str)
    open_count = int((flags["status"] == "open").sum())
    st.caption(
        f"{len(flags):,} laporan · {open_count:,} belum ditangani. "
        "Laporan ini masuk dari halaman **Daftar Customer** ketika ada yang "
        "menyebut sekelompok customer ini salah digabung atau salah dipecah."
    )
    issue_label = {
        "wrong_merge": "Salah digabung",
        "wrong_split": "Salah dipecah",
    }
    status_label = {
        "open": "Belum ditangani",
        "resolved": "Sudah ditangani",
        "ignored": "Diabaikan",
    }
    # Nilai issue TIDAK diterjemahkan di kolom: file ini dibaca lagi oleh
    # triage dan entity_correction yang mencari 'wrong_merge'/'wrong_split'
    # persis. Yang diterjemahkan hanya judul kolomnya, dan nama kolom
    # dikembalikan ke bentuk asli sebelum disimpan.
    flags_titles = {
        "timestamp": "Dilaporkan",
        "entity_id": "Kode customer",
        "issue": "Jenis laporan",
        "reviewer": "Pelapor",
        "note": "Catatan",
        "status": "Tindak lanjut",
    }
    flags_view = flags.rename(
        columns={k: v for k, v in flags_titles.items() if k in flags.columns}
    )
    edited_view = st.data_editor(
        flags_view,
        disabled=[c for c in flags_view.columns if c not in ("Tindak lanjut", "Catatan")],
        width="stretch",
        hide_index=True,
        column_config={
            "Tindak lanjut": st.column_config.SelectboxColumn(
                "Tindak lanjut",
                options=["open", "resolved", "ignored"],
                format_func=lambda v: status_label.get(str(v), str(v)),
            ),
            "Catatan": st.column_config.TextColumn("Catatan"),
            "Dilaporkan": st.column_config.TextColumn("Dilaporkan", width="small"),
        },
    )
    with st.expander("Apa arti jenis laporan?"):
        st.markdown(
            "- **wrong_merge** — beberapa customer sebenarnya berbeda orang, tapi "
            "sistem menggabungkannya jadi satu.\n"
            "- **wrong_split** — satu orang sebenarnya terpecah jadi beberapa "
            "customer di sistem."
        )
    if st.button("Simpan tindak lanjut"):
        edited_view.rename(columns={v: k for k, v in flags_titles.items()}).to_csv(
            flags_path, index=False
        )
        st.success("Tindak lanjut disimpan.")
        st.rerun()
else:
    st.caption("Belum ada laporan. Tandai dari halaman Daftar Customer.")

# ---- threshold exploration
st.subheader("Coba Batas Kepastian")
st.caption(
    "Di bawah ini ditunjukkan apa yang terjadi kalau batas kepastian digeser. "
    "Angka-angkanya dihitung dari label perak (otomatis), jadi "
    "ini perkiraan — bukan jaminan."
)

preds_path = OUTPUT_DIR / "splink_predictions.parquet"
silver_path = LABELS_DIR / "silver_pairs.csv"
if preds_path.exists() and silver_path.exists():
    from src.threshold_eval import THRESHOLDS, evaluate_at

    preds = pd.read_parquet(
        preds_path, columns=["record_id_l", "record_id_r", "match_probability"]
    )
    silver = pd.read_csv(silver_path)[["record_id_l", "record_id_r", "label"]]
    merged = silver.merge(preds, on=["record_id_l", "record_id_r"], how="inner")
    coverage = len(merged) / len(silver) if len(silver) else 0.0
    st.caption(
        f"Dasar perhitungan: {len(silver):,} pasangan yang diperiksa. "
        f"{len(merged):,} di antaranya pernah jadi kandidat perbandingan "
        f"({format_rate(coverage)}). Sisanya terlewat karena datanya tidak mirip "
        "sama sekali, jadi angka aslinya bisa lebih baik dari yang tertulis."
    )
    sweep = pd.DataFrame(
        [evaluate_at(merged, "label", "match_probability", t) for t in THRESHOLDS]
    )
    shown = sweep[["threshold", "tp", "fp", "fn", "tn", "precision", "recall", "f1"]].copy()
    shown["threshold"] = shown["threshold"].map(lambda v: format_threshold(v))
    shown = shown.rename(columns={
        "threshold": "Batas",
        "tp": "Benar sama",
        "fp": "Salah gabung",
        "fn": "Terlewat",
        "tn": "Benar beda",
        "precision": "Ketepatan",
        "recall": "Kelengkapan",
        "f1": "Nilai gabungan",
    })
    for col in ("Benar sama", "Salah gabung", "Terlewat", "Benar beda"):
        shown[col] = shown[col].map(format_count)
    for col in ("Ketepatan", "Kelengkapan", "Nilai gabungan"):
        shown[col] = shown[col].map(lambda v: format_rate(v))

    c1, c2 = st.columns(2)
    with c1:
        st.dataframe(shown, width="stretch", hide_index=True, height=340)
    with c2:
        st.line_chart(
            sweep.set_index("threshold")[["precision", "recall", "f1"]]
        )
    with st.expander("Apa arti kolomnya?"):
        st.markdown(
            "- **Benar sama** — pasangan yang sistem bilang sama, dan memang sama.\n"
            "- **Salah gabung** — sistem bilang sama, padahal berbeda orang. "
            "Ini yang paling merusak: data jadi tercemar.\n"
            "- **Terlewat** — sebenarnya sama, tapi tidak terambil. Lebih baik "
            "daripada salah gabung.\n"
            "- **Ketepatan / Kelengkapan / Nilai gabungan** — 100% berarti tidak ada "
            "kesalahan sama sekali."
        )

    # Terapkan threshold — aksi eksplisit, bukan otomatis.
    st.markdown("**Ubah batas kepastian**")
    st.caption(
        "Batas ini yang menentukan kapan sistem menggabungkan sendiri. "
        "Semakin tinggi batas atas, semakin sedikit yang digabung otomatis — "
        "dan semakin banyak yang menunggu Anda periksa."
    )
    model_dir = MODELS_DIR / cur if cur else None
    cur_match, cur_review = 0.9, 1e-10
    if model_dir and (model_dir / "thresholds.json").exists():
        tfile = json.loads((model_dir / "thresholds.json").read_text(encoding="utf-8"))
        cur_match = tfile.get("match_threshold", cur_match)
        cur_review = tfile.get("review_threshold", cur_review)

    c0, c1 = st.columns([1, 1])
    c0.metric(
        "Batas gabung otomatis",
        format_threshold(cur_match),
        help="Peluang minimal agar sistem langsung menggabungkan tanpa bertanya.",
    )
    c1.metric(
        "Batas bawah",
        format_threshold(cur_review),
        help="Di bawah peluang ini, pasangan dianggap pasti dua orang berbeda.",
    )

    t1, t2, t3 = st.columns([2, 2, 3])
    new_match = t1.number_input(
        "Gabung otomatis bila peluang ≥",
        min_value=0.0, max_value=1.0, value=float(cur_match),
        step=0.01, format="%.2f",
        help="Contoh: 0,90 berarti pasangan dengan peluang 90% ke atas "
             f"langsung digabung. Sekarang: {format_threshold(cur_match)}.",
    )
    new_review = t2.number_input(
        "Anggap pasti beda bila peluang <",
        min_value=0.0, max_value=1.0, value=float(cur_review),
        step=0.0000001, format="%.10f",
        help="Nilai aslinya sengaja dibuat sangat kecil "
             f"({format_threshold(cur_review)}) supaya tidak ada yang salah gabung. "
             "Boleh diketik 0 bila tidak ada batas bawah.",
    )
    reviewer_name = t3.text_input("Nama Anda", value="reviewer")
    st.caption(
        "Setelah menekan tombol di bawah: (1) semua keputusan dihitung ulang, "
        "(2) pengelompokan dan daftar customer dijalankan ulang (±10 detik), "
        "(3) angka baru dicatat di model aktif. "
        "Semua angka customer bisa berubah — pastikan sudah yakin."
    )
    confirm_threshold = st.checkbox(
        "Saya paham semua angka customer akan berubah",
        key="threshold_confirm",
        value=False,
    )
    if st.button("Terapkan threshold", type="primary", disabled=not confirm_threshold):
        if not (0.0 <= new_review < new_match <= 1.0):
            st.error("Harus: 0 ≤ REVIEW < MATCH ≤ 1.")
        else:
            override = {
                "match_threshold": float(new_match),
                "review_threshold": float(new_review),
                "applied_at": datetime.now().isoformat(timespec="seconds"),
                "reviewer": reviewer_name,
                "previous": {"match_threshold": cur_match, "review_threshold": cur_review},
            }
            (OUTPUT_DIR / "thresholds_override.json").write_text(
                json.dumps(override, indent=2), encoding="utf-8"
            )
            if model_dir and (model_dir / "thresholds.json").exists():
                tfile.update(override)
                (model_dir / "thresholds.json").write_text(
                    json.dumps(tfile, indent=2), encoding="utf-8"
                )

            import numpy as np

            full = pd.read_parquet(preds_path)
            full["decision"] = np.where(
                full["match_probability"] >= float(new_match), "MATCH",
                np.where(full["match_probability"] >= float(new_review), "REVIEW", "NON_MATCH"),
            )
            full.to_parquet(preds_path, index=False)

            log_box = st.empty()
            lines: list[str] = []
            for module in ("clustering", "master_record", "evaluate"):
                proc = subprocess.Popen(
                    [sys.executable, "-m", f"src.{module}", "--full"]
                    if module == "clustering" else
                    [sys.executable, "-m", f"src.{module}"],
                    cwd=PROJECT_ROOT, text=True,
                    encoding="utf-8", errors="replace",
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    lines.append(line)
                    log_box.code("".join(lines[-30:]), language="log")
                if proc.wait() != 0:
                    st.error(f"Langkah {module} gagal — lihat log.")
                    st.stop()
            st.success(
                f"Threshold diterapkan: MATCH ≥ {new_match}, REVIEW ≥ {new_review}. "
                "Clustering, master dan evaluasi sudah dijalankan ulang."
            )
            st.rerun()
else:
    st.caption("Butuh predictions + silver_labels untuk sweep.")

# ---- promotion checklist
st.subheader("Cek Kelengkapan Sebelum Melatih Ulang")
st.caption(
    "Melatih ulang model hanya berguna kalau datanya sudah bersih. "
    "Daftar ini tidak harus semuanya centang hijau, tapi melihat isinya "
    "membantu memutuskan."
)
gold_path = LABELS_DIR / "gold_labels.csv"
queue_path = LABELS_DIR / "review_queue.csv"
checks = []
if gold_path.exists():
    gold = pd.read_csv(gold_path)
    checks.append((f"Keputusan manual tersimpan: {format_count(len(gold))} baris", len(gold) > 0))
else:
    checks.append(("Keputusan manual tersimpan: belum ada", False))
if queue_path.exists():
    queue = pd.read_csv(queue_path)
    pending = int((queue["review_status"] == "pending").sum())
    checks.append((f"Antrean kosong (sudah diperiksa semua): sisa {format_count(pending)}", pending == 0))
else:
    checks.append(("Antrean pemeriksaan: belum ada", True))
checks.append((f"Model aktif tersedia: {cur}", cur is not None))
for label, ok in checks:
    if ok:
        st.success(f"Lengkap — {label}")
    else:
        st.warning(f"Belum — {label}")

# ---- rollback
st.subheader("Kembalikan ke Model Sebelumnya")
st.caption(
    "Kalau model baru hasilnya lebih buruk, kembalikan sistem ke versi yang "
    "lama. Hanya model aktif yang berubah — data hasil processing tidak disentuh."
)
if len(versions) >= 2:
    target = st.selectbox(
        "Kembalikan ke versi",
        [v["version"] for v in versions[:-1]],
        format_func=lambda v: f"{v}  ({v[1:9].replace('-', '/')})",
    )
    confirm_rollback = st.checkbox(
        f"Saya paham model aktif akan diganti ke {target}",
        key="rollback_confirm",
        value=False,
    )
    if st.button("Kembalikan sekarang", disabled=not confirm_rollback):
        LATEST.write_text(
            json.dumps(
                {
                    "version": target,
                    "path": str(MODELS_DIR / target),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        st.success(f"Model aktif sekarang: {target}")
        st.rerun()
else:
    st.caption("Butuh 2 versi model untuk bisa mengembalikan.")

# ---- retrain history
st.subheader("Riwayat Pemrosesan")
st.caption(
    "Setiap kali data baru diproses, jejaknya tercatat di sini: berapa record "
    "masuk, berapa yang digabung, dan berapa yang perlu diperiksa."
)
history_path = OUTPUT_DIR / "incremental_history.jsonl"
if history_path.exists():
    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if history:
        st.dataframe(
            format_history_table(pd.DataFrame(history)),
            width="stretch",
            hide_index=True,
            height=300,
            column_config={
                "Catatan": st.column_config.TextColumn("Catatan", width="large"),
                "Waktu": st.column_config.TextColumn("Waktu", width="small"),
                "Durasi": st.column_config.TextColumn("Durasi", width="small"),
            },
        )
        st.caption(
            "Kolom **Anomali waktu** berarti durasi yang tercatat bukan waktu proses "
            "sesungguhnya — biasanya selisih waktu saat menunggu persetujuan."
        )
    else:
        st.caption("Belum ada riwayat.")
else:
    st.caption("Belum ada riwayat.")

# ---- provenance
st.subheader("Asal Data Model Ini")
if versions:
    v = versions[-1]
    st.caption(
        f"Model `{v['version']}` dibuat dari {format_count(v.get('input_rows', 0))} record, "
        f"menilai {format_count(v.get('pairs_scored', 0))} pasangan, "
        f"selama {format_duration(v.get('runtime_seconds', 0))}. "
        f"Acak: {v.get('random_seed', '-')} · pustaka: {v.get('splink_version', '-')}."
    )
    st.caption(
        "Nomor acak dipakai agar hasil bisa diulang persis. Kalau angkanya sama, "
        "kesimpulannya bisa dipercaya."
    )
