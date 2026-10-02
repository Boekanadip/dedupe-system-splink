"""Human review page (PRD FR-09). A separate Streamlit tab.

The model is deliberately not 100% automatic: pairs in the REVIEW band are
queued here for a person to decide. This page is that queue.

Opsi A (simple): edits are written straight back to review_queue.csv, which is
the file `python -m src.labels --promote` reads. Safe for a single reviewer;
two people editing at the same time would overwrite each other.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import LABELS_DIR, PROJECT_ROOT

QUEUE_PATH = LABELS_DIR / "review_queue.csv"

st.set_page_config(page_title="Review", page_icon="🧐", layout="wide")
st.title("Review queue")
st.caption(
    "Pasangan yang model tidak yakin — manusia yang memutuskan. "
    "Isi label, tekan Simpan, lalu Promote untuk menaikkan ke gold label."
)

if not QUEUE_PATH.exists():
    st.info("Belum ada antrian. Jalankan pipeline dulu dari halaman upload.")
    st.stop()

queue = pd.read_csv(QUEUE_PATH)

# ---- statistik
pending = int((queue["review_status"] == "pending").sum())
reviewed = int((queue["review_status"] != "pending").sum())
st.caption(f"Total {len(queue):,} pasangan · {pending:,} menunggu · {reviewed:,} sudah direview")

# ---- filter
st.subheader("Filter")
f1, f2 = st.columns(2)
strata = ["(semua)"] + sorted(queue["stratum"].unique().tolist())
statuses = ["(semua)"] + sorted(queue["review_status"].unique().tolist())
stratum_filter = f1.selectbox("Stratum", strata)
status_filter = f2.selectbox("Status", statuses)
filtered = queue
if stratum_filter != "(semua)":
    filtered = filtered[filtered["stratum"] == stratum_filter]
if status_filter != "(semua)":
    filtered = filtered[filtered["review_status"] == status_filter]
st.caption(f"Menampilkan {len(filtered):,} dari {len(queue):,}")

# ---- tabel editable
st.subheader("Antrian")
editable = ["label", "reviewer", "reviewer_note"]
disabled = [c for c in queue.columns if c not in editable]
# Empty CSV cells read as NaN (float); the editor needs strings to edit them.
for col in editable:
    queue[col] = queue[col].where(queue[col].notna(), "").astype(str)
edited = st.data_editor(
    filtered,
    disabled=disabled,
    use_container_width=True,
    height=600,
    column_config={
        "label": st.column_config.SelectboxColumn(
            "Label", options=["", "match", "no_match"], required=False
        ),
        "reviewer": st.column_config.TextColumn("Reviewer"),
        "reviewer_note": st.column_config.TextColumn("Catatan"),
        "match_probability": st.column_config.NumberColumn("Skor", format="%.4f"),
    },
)

# ---- simpan
if st.button("Simpan perubahan", type="primary"):
    # Merge edits back: data_editor returns only the filtered rows, so the
    # edited values are written onto the matching rows of the full queue.
    merged = queue.copy()
    key = ["record_id_l", "record_id_r"]
    for _, row in edited.iterrows():
        mask = (merged["record_id_l"] == row["record_id_l"]) & (
            merged["record_id_r"] == row["record_id_r"]
        )
        for col in editable:
            value = row[col]
            merged.loc[mask, col] = None if value == "" else value
    merged.to_csv(QUEUE_PATH, index=False)
    st.success(f"Disimpan: {len(edited):,} baris.")
    st.rerun()

# ---- promote
st.subheader("Promote ke gold")
st.caption(
    "Label yang sudah diisi akan disalin ke gold_labels.csv (gold lama di-backup "
    "dulu). Gold dipakai untuk evaluasi dan retraining."
)
if st.button("Promote ke gold label"):
    result = subprocess.run(
        [sys.executable, "-m", "src.labels", "--promote"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )
    with st.expander("Log promote", expanded=result.returncode != 0):
        st.code(result.stdout[-3000:] + ("\n" + result.stderr[-1000:] if result.stderr else ""))
    if result.returncode == 0:
        st.success("Promote selesai.")
    else:
        st.error("Promote gagal — lihat log.")
