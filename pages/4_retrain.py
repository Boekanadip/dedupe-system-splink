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
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import LABELS_DIR, OUTPUT_DIR, PROJECT_ROOT

st.set_page_config(page_title="Retrain", page_icon="🔄", layout="wide")
st.title("Retrain & model management")
st.caption(
    "Retrain adalah aksi eksplisit di halaman ini — tidak bareng data masuk. "
    "Data baru tetap lewat incremental; retrain hanya kalau memang dibutuhkan."
)

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
st.subheader("Status model")
if cur:
    st.success(f"Model aktif: `{cur}`")
else:
    st.warning("Belum ada model.")
c1, c2 = st.columns(2)
if versions:
    latest_meta = versions[-1]
    c1.metric("Input rows", f"{latest_meta.get('input_rows', 0):,}")
    c2.metric("Pairs scored", f"{latest_meta.get('pairs_scored', 0):,}")

# ---- retrain
st.subheader("Retrain model")
st.caption(
    "Full pipeline dijalankan ulang di SEMUA data (bukan incremental). "
    "Menghasilkan model version baru. ±2-3 menit."
)
@st.fragment(run_every="3s")
def retrain_runner() -> None:
    """Stream the retrain log live without freezing the page.

    The subprocess blocks this thread, but only this fragment: the rest of the
    page and every other Streamlit tab keep responding while it runs.
    """
    if LOCK.exists():
        st.warning("⏳ Retrain sedang berjalan. Halaman ini tetap bisa dipakai.")
    running = st.session_state.get("retrain_running", False)
    if running:
        log = st.session_state.get("retrain_log", "")
        with st.expander("Log retrain", expanded=True):
            st.code(log[-4000:] if log else "Menunggu output…", language="log")
        st.caption("Menunggu proses selesai…")
        return

    if st.button("Retrain sekarang", type="primary"):
        LOCK.write_text("running", encoding="utf-8")
        st.session_state["retrain_running"] = True
        st.session_state["retrain_log"] = ""
        process = subprocess.Popen(
            [sys.executable, "-m", "src.run_all"],
            cwd=PROJECT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        lines: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            st.session_state["retrain_log"] = "".join(lines)
        process.wait()
        LOCK.unlink(missing_ok=True)
        st.session_state["retrain_running"] = False
        st.session_state["retrain_exit"] = process.returncode
        st.rerun()

    if "retrain_exit" in st.session_state:
        if st.session_state["retrain_exit"] == 0:
            st.success("Retrain selesai. Model baru aktif.")
        else:
            st.error("Retrain gagal — lihat log di bawah.")
        with st.expander("Log retrain"):
            st.code(st.session_state.get("retrain_log", "")[-4000:], language="log")


retrain_runner()

# ---- drift
st.subheader("Drift (perubahan antar model)")
if len(versions) >= 2:
    prev, last = versions[-2], versions[-1]
    pe = prev.get("evaluation", {}).get("decision_rates", {})
    le = last.get("evaluation", {}).get("decision_rates", {})
    d1, d2 = st.columns(2)
    d1.metric(
        "Auto-match rate",
        f"{le.get('MATCH', 0):.2%}",
        delta=f"{(le.get('MATCH', 0) - pe.get('MATCH', 0)):.2%}",
    )
    d2.metric(
        "Review rate",
        f"{le.get('REVIEW', 0):.2%}",
        delta=f"{(le.get('REVIEW', 0) - pe.get('REVIEW', 0)):.2%}",
    )
    st.caption("Delta vs model sebelumnya. Perubahan besar = pertimbangkan retrain.")
else:
    st.caption("Butuh 2 model version untuk membandingkan drift.")

# ---- perbandingan model (A/B)
st.subheader("Perbandingan model")
if len(versions) >= 2:
    rows = []
    for v in versions:
        ev = v.get("evaluation", {}).get("decision_rates", {})
        rows.append(
            {
                "version": v["version"],
                "input_rows": v.get("input_rows", 0),
                "match": f"{ev.get('MATCH', 0):.2%}",
                "review": f"{ev.get('REVIEW', 0):.2%}",
                "non_match": f"{ev.get('NON_MATCH', 0):.2%}",
                "runtime": f"{v.get('runtime_seconds', 0):.0f}s",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
else:
    st.caption("Butuh 2 model version.")

# ---- feedback
st.subheader("Feedback (manusia)")
fb_path = LABELS_DIR / "feedback.csv"
if fb_path.exists():
    fb = pd.read_csv(fb_path)
    st.caption(f"{len(fb):,} baris feedback")
    st.dataframe(
        fb[["pair_id", "human_label", "reviewer", "model_version", "stratum"]].tail(20),
        use_container_width=True,
    )
else:
    st.caption("Belum ada feedback.")

# ---- triage laporan keanggotaan (dari halaman Master)
flags_path = LABELS_DIR / "membership_flags.csv"
if flags_path.exists():
    st.subheader("Triage: laporan salah gabung / salah pecah")
    flags = pd.read_csv(flags_path)
    flags["status"] = flags["status"].fillna("open")
    open_count = int((flags["status"] == "open").sum())
    st.caption(
        f"{len(flags):,} laporan · {open_count:,} belum ditangani. "
        "Laporan ini umpan balik untuk retrain: entity salah gabung/pecah "
        "seharusnya memicu peninjauan pasangan di antrean review."
    )
    edited_flags = st.data_editor(
        flags,
        disabled=[c for c in flags.columns if c not in ("status", "note")],
        use_container_width=True,
        column_config={
            "status": st.column_config.SelectboxColumn(
                "Status", options=["open", "resolved", "ignored"]
            ),
            "note": st.column_config.TextColumn("Catatan"),
        },
    )
    if st.button("Simpan triage"):
        edited_flags.to_csv(flags_path, index=False)
        st.success("Triage disimpan.")
        st.rerun()
else:
    st.caption("Belum ada laporan keanggotaan (tandai dari halaman Master).")

# ---- threshold exploration
st.subheader("Threshold exploration")
st.caption(
    "Apa yang terjadi kalau ambang MATCH/REVIEW digeser? Sweep dihitung ulang "
    "dari label silver (bersifat optimis — pasangan mudah) dan gold (100 pasangan "
    "positif, tanpa negatif sehingga presisi tidak bisa diukur di sana)."
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
        f"Silver: {len(silver):,} label · {len(merged):,} ada di prediksi "
        f"({coverage:.1%} coverage blocking). Sisanya tidak pernah jadi kandidat — "
        "recall sebenarnya ≤ angka ini."
    )
    sweep = pd.DataFrame(
        [evaluate_at(merged, "label", "match_probability", t) for t in THRESHOLDS]
    )
    c1, c2 = st.columns(2)
    with c1:
        st.dataframe(
            sweep[["threshold", "tp", "fp", "fn", "tn", "precision", "recall", "f1"]],
            use_container_width=True,
        )
    with c2:
        st.line_chart(
            sweep.set_index("threshold")[["precision", "recall", "f1"]]
        )

    # Terapkan threshold — aksi eksplisit, bukan otomatis.
    st.markdown("**Terapkan threshold**")
    model_dir = MODELS_DIR / cur if cur else None
    cur_match, cur_review = 0.9, 1e-10
    if model_dir and (model_dir / "thresholds.json").exists():
        tfile = json.loads((model_dir / "thresholds.json").read_text(encoding="utf-8"))
        cur_match = tfile.get("match_threshold", cur_match)
        cur_review = tfile.get("review_threshold", cur_review)
    t1, t2, t3 = st.columns([2, 2, 3])
    new_match = t1.number_input(
        "MATCH ≥", min_value=0.0, max_value=1.0, value=float(cur_match), step=0.01,
        format="%.4f",
    )
    new_review = t2.number_input(
        "REVIEW ≥", min_value=0.0, max_value=1.0, value=float(cur_review),
        format="%.6g",
    )
    reviewer_name = t3.text_input("Reviewer yang memutuskan", value="reviewer")
    st.caption(
        "Menerapkan threshold: (1) keputusan di prediksi dihitung ulang, "
        "(2) clustering + master + evaluasi dijalankan ulang (~10 detik), "
        "(3) nilai dicatat ke thresholds.json model aktif. Setelah ini semua "
        "angka entity ikut berubah — pastikan sudah yakin."
    )
    if st.button("Terapkan threshold", type="primary"):
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
            # Keputusan di prediksi harus dihitung ulang dulu: clustering membaca
            # kolom decision, bukan config.
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
st.subheader("Promotion checklist")
gold_path = LABELS_DIR / "gold_labels.csv"
queue_path = LABELS_DIR / "review_queue.csv"
checks = []
if gold_path.exists():
    gold = pd.read_csv(gold_path)
    checks.append((f"Gold label: {len(gold)} baris", len(gold) > 0))
else:
    checks.append(("Gold label: tidak ada", False))
if queue_path.exists():
    queue = pd.read_csv(queue_path)
    pending = int((queue["review_status"] == "pending").sum())
    checks.append((f"Review queue pending: {pending}", pending == 0))
else:
    checks.append(("Review queue: tidak ada", True))
checks.append((f"Model version: {cur}", cur is not None))
for label, ok in checks:
    st.write(f"{'✅' if ok else '❌'} {label}")

# ---- rollback
st.subheader("Model rollback")
st.caption("Kembalikan model aktif ke version sebelumnya (ubah latest.json).")
if len(versions) >= 2:
    target = st.selectbox("Rollback ke", [v["version"] for v in versions[:-1]])
    if st.button("Rollback"):
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
    st.caption("Butuh 2 model version untuk rollback.")

# ---- retrain history
st.subheader("Retrain history")
history_path = OUTPUT_DIR / "incremental_history.jsonl"
if history_path.exists():
    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if history:
        st.dataframe(pd.DataFrame(history), use_container_width=True)
    else:
        st.caption("Belum ada riwayat.")
else:
    st.caption("Belum ada riwayat.")

# ---- provenance
st.subheader("Training provenance")
if versions:
    v = versions[-1]
    st.caption(
        f"Model `{v['version']}` dilatih dari {v.get('input_rows', 0):,} row, "
        f"{v.get('pairs_scored', 0):,} pasang, runtime {v.get('runtime_seconds', 0):.0f}s, "
        f"seed {v.get('random_seed', '-')}, splink {v.get('splink_version', '-')}."
    )
