"""Batch review page: what the system proposes for a new batch, before it merges.

Incremental --stage computes a proposal for every new record and applies
nothing. This page is the human gate:

  * see the proposed entity for each record and the model score
  * uncheck records you dispute (disputed records enter the dataset as their own
    entity — they are never dropped)
  * Apply the proposal, or Reject it and drop the batch's staging entirely
  * the date-format answer used for this batch is shown, and re-stage is offered
    when the column gave no evidence of its own
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import MASTER_PATH, OUTPUT_DIR, PROJECT_ROOT
from src.profiling import load_raw
from src.ui import format_probability, monitoring_sidebar, page_guide, page_header
from src.validate_upload import validate_file

st.set_page_config(page_title="Batch - Entity Resolution", page_icon="📦", layout="wide")
page_header(
    "Data Batch Baru",
    "Sebelum data baru dipakai, periksa dulu setiap barisnya. Baris yang tidak "
    "disetujui tetap masuk sebagai customer sendiri, tidak dipaksa bergabung.",
)
monitoring_sidebar()
page_guide(__file__)

STAGING_DIR = OUTPUT_DIR / "staging"
RAW_DIR = PROJECT_ROOT / "data" / "raw"


def run(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "src.incremental", *args],
        cwd=PROJECT_ROOT, text=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


files = sorted(STAGING_DIR.glob("*.parquet")) if STAGING_DIR.exists() else []
staged_only = [f for f in files if not f.name.endswith(".predictions.parquet")]
if not staged_only:
    st.info("Belum ada batch yang di-stage. Upload batch baru di halaman App.")
    st.stop()

selected = st.selectbox("Pilih batch", [f.name for f in staged_only])
if not selected:
    st.stop()
batch_file = selected.replace(".parquet", "")
staging = pd.read_parquet(STAGING_DIR / selected)

# ---- jawaban tanggal yang dipakai batch ini
try:
    report, _ = validate_file(RAW_DIR / batch_file)
    dates = report.get("date_formats", {})
    if dates:
        parts = []
        ambiguous = []
        for col, ev in dates.items():
            if ev.get("needs_answer"):
                ambiguous.append(col)
                parts.append(f"**{col}**: TIDAK ADA BUKTI — harus ditanya")
            else:
                parts.append(
                    f"**{col}**: {ev['detected_order']} "
                    f"(hari>12 di {ev['day_gt_12']:,} baris)"
                )
        st.subheader("Format tanggal")
        for p in parts:
            st.caption(p)
        if ambiguous:
            st.warning(
                "Kolom ini tidak bisa disimpulkan sendiri. Stage ulang dengan "
                "jawaban eksplisit."
            )
            order = st.radio(
                "Format tanggal batch ini:",
                ["dmy", "mdy"], index=0,
                help="dmy = 11/04/1988 = 11 April. mdy = 04/11/1988 = 11 April.",
            )
            if st.button("Stage ulang dengan jawaban ini"):
                code, log = run(["--reject", "--batch", batch_file])
                if code != 0:
                    st.error(log[-1500:]); st.stop()
                code, log = run(["--stage", "--batch", batch_file, "--date-order", order])
                st.code(log[-3000:])
                if code != 0:
                    st.error("Stage ulang gagal — lihat log.")
                    st.stop()
                st.success("Stage ulang selesai dengan jawaban tanggal.")
                st.rerun()
except SystemExit as exc:
    st.caption(f"Validasi batch gagal: {exc}")

# ---- ringkasan
st.subheader(f"{batch_file} — {len(staging):,} record")
counts = staging["action"].value_counts().to_dict()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Match (gabung entity lama)", f"{counts.get('match', 0):,}")
c2.metric("New (entity baru)", f"{counts.get('new', 0):,}")
c3.metric("Skor rata-rata",
          f"{staging['match_probability'].mean():.3f}"
          if staging["match_probability"].notna().any() else "-")
c4.metric("Model saat stage", str(staging["model_version"].iloc[0]) if "model_version" in staging.columns else "-")

if "model_version" in staging.columns:
    latest = PROJECT_ROOT / "models" / "latest.json"
    if latest.exists():
        import json
        active = json.loads(latest.read_text(encoding="utf-8"))["version"]
        if staging["model_version"].iloc[0] != active:
            st.error(
                f"Proposal ini discoring oleh `{staging['model_version'].iloc[0]}` "
                f"tapi model aktif sekarang `{active}`. Proposal basi — "
                "Reject lalu stage ulang."
            )

# ---- approval per record
st.subheader("Detail — centang record yang disetujui")
st.caption(
    "Default: semua record disetujui. Record yang di-uncheck TIDAK digabung ke "
    "entity yang diusulkan — record tetap masuk data sebagai entity baru "
    "sendiri (tidak pernah dihapus)."
)
master_lookup = pd.read_parquet(MASTER_PATH).set_index("entity_id")
display = staging.copy()
if "approved" not in display.columns:
    display["approved"] = True
display["approved"] = display["approved"].fillna(True).astype(bool)
for col in ["master_first_name_std", "master_last_name_std", "master_email_std", "master_phone_std"]:
    display[col] = display["proposed_entity_id"].map(master_lookup[col])
    display[col] = display[col].where(display[col].notna(), "").astype(str)

# Peluang ditampilkan sebagai teks persen, bukan angka eksponensial mentah.
if "match_probability" in display.columns:
    display["match_probability"] = display["match_probability"].map(format_probability)

editable_cols = ["approved"]
disabled_cols = [c for c in display.columns if c not in editable_cols]
edited = st.data_editor(
    display,
    disabled=disabled_cols,
    width="stretch",
    height=520,
    column_config={
        "approved": st.column_config.CheckboxColumn("Setujui", default=True),
        "match_probability": st.column_config.TextColumn("Peluang"),
    },
)

n_approved = int(edited["approved"].sum())
st.caption(f"{n_approved:,} dari {len(edited):,} record disetujui.")

# ---- aksi
st.subheader("Aksi")
a1, a2 = st.columns(2)
if a1.button("Simpan persetujuan", type="secondary"):
    # Tulis kolom approved kembali ke staging file (record_id urut sama).
    fresh = pd.read_parquet(STAGING_DIR / selected)
    approved_map = dict(zip(edited["record_id"], edited["approved"]))
    fresh["approved"] = fresh["record_id"].map(approved_map).fillna(False).astype(bool)
    fresh.to_parquet(STAGING_DIR / selected, index=False)
    st.success(f"Persetujuan disimpan: {int(fresh['approved'].sum()):,} record.")
    st.rerun()

if a2.button("Apply proposal", type="primary"):
    with st.spinner("Menerapkan proposal..."):
        code, log = run(["--apply", "--batch", batch_file])
    with st.expander("Log apply", expanded=code != 0):
        st.code(log[-3000:])
    if code == 0:
        st.success("Proposal diterapkan. Batch sudah digabung — cek halaman Master & Dashboard.")
        st.rerun()
    else:
        st.error("Apply gagal — lihat log.")

st.divider()
st.subheader("Tolak proposal")
st.caption(
    "Hapus proposal tanpa menggabung apa pun. Batch tetap terdaftar dan bisa di-stage ulang."
)
confirm_reject = st.checkbox(
    "Saya paham proposal ini akan dihapus",
    key="reject_confirm",
    value=False,
)
if st.button("Tolak proposal", type="secondary", disabled=not confirm_reject):
    code, log = run(["--reject", "--batch", batch_file])
    with st.expander("Log reject", expanded=code != 0):
        st.code(log[-2000:])
    if code == 0:
        st.success("Proposal dibatalkan. Staging dihapus; batch tetap terdaftar.")
        st.rerun()
    else:
        st.error("Reject gagal — lihat log.")
