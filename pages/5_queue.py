"""Review queue coverage page.

The review queue is a SAMPLE of the REVIEW band (a few hundred of tens of
thousands). This page shows the full REVIEW band with coverage: which pairs are
already queued, which are not, and lets a reviewer work through them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import LABELS_DIR, OUTPUT_DIR, PROJECT_ROOT

st.set_page_config(page_title="Review queue", page_icon="📋", layout="wide")
st.title("Review queue coverage")
st.caption(
    "Semua pasangan di band REVIEW. Antrian review adalah sample — "
    "halaman ini melihat semuanya."
)

QUEUE_PATH = LABELS_DIR / "review_queue.csv"
PREDS_PATH = OUTPUT_DIR / "splink_predictions.parquet"

if not PREDS_PATH.exists():
    st.info("Belum ada predictions. Jalankan pipeline dulu.")
    st.stop()

preds = pd.read_parquet(
    PREDS_PATH,
    columns=["record_id_l", "record_id_r", "match_probability", "match_weight", "decision"],
)
review = preds[preds["decision"] == "REVIEW"].copy()
# REVIEW-band probabilities sit between 1e-10 and 0.9, so most read as 0.0000 in
# a fixed-decimal column. log10 turns them into a readable number, and
# match_weight (log2) is Splink's own scale.
review["log10_p"] = review["match_probability"].apply(
    lambda p: round(p, 12) and __import__("math").log10(p) if p > 0 else None
)

# Which are already in the queue?
if QUEUE_PATH.exists():
    queue = pd.read_csv(QUEUE_PATH)
    queued = set(zip(queue["record_id_l"], queue["record_id_r"]))
else:
    queued = set()
review["queued"] = [
    (l, r) in queued for l, r in zip(review["record_id_l"], review["record_id_r"])
]

st.subheader("Coverage")
total = len(review)
n_queued = int(review["queued"].sum())
m1, m2, m3 = st.columns(3)
m1.metric("Total REVIEW pair", f"{total:,}")
m2.metric("Sudah di antrian", f"{n_queued:,}")
m3.metric("Belum di antrian", f"{total - n_queued:,}")

# ---- filter
st.subheader("Filter")
f1, f2 = st.columns(2)
queued_filter = f1.selectbox("Status antrian", ["(semua)", "Sudah", "Belum"])
score_min = f2.slider("Skor minimum", 0.0, 1.0, 0.0)
filtered = review[review["match_probability"] >= score_min]
if queued_filter == "Sudah":
    filtered = filtered[filtered["queued"]]
elif queued_filter == "Belum":
    filtered = filtered[~filtered["queued"]]
st.caption(f"Menampilkan {len(filtered):,} dari {total:,}")

# ---- tabel dengan paginasi
st.subheader("Pasangan REVIEW")
page_size = 50
n_pages = max(1, (len(filtered) + page_size - 1) // page_size)
page = st.number_input("Halaman", min_value=1, max_value=n_pages, value=1)
start = (page - 1) * page_size
page_df = filtered.iloc[start : start + page_size]
st.caption(f"Halaman {page} dari {n_pages}")
st.dataframe(
    page_df[["record_id_l", "record_id_r", "log10_p", "match_weight", "match_probability", "queued"]],
    use_container_width=True,
    column_config={
        "log10_p": st.column_config.NumberColumn("log10(P)", format="%.2f"),
        "match_weight": st.column_config.NumberColumn("Weight (log2)", format="%.2f"),
        "match_probability": st.column_config.NumberColumn("P", format="%.2e"),
    },
)

# ---- tambah ke antrian
st.subheader("Tambah ke antrian review")
st.caption(
    "Masukkan pasangan terpilih ke review_queue.csv (stratum incremental_new_batch) "
    "agar muncul di halaman Review."
)
if st.button("Tambah yang terfilter ke antrian"):
    from src.labels import carry_over_reviewed

    new_rows = filtered[["record_id_l", "record_id_r", "match_probability"]].copy()
    new_rows["stratum"] = "manual_review"
    new_rows["label"] = None
    new_rows["review_status"] = "pending"
    new_rows["reviewer"] = None
    new_rows["reviewer_note"] = None
    old_queue = pd.read_csv(QUEUE_PATH) if QUEUE_PATH.exists() else pd.DataFrame()
    combined = pd.concat([old_queue, new_rows], ignore_index=True)
    combined = carry_over_reviewed(combined)
    combined.to_csv(QUEUE_PATH, index=False)
    st.success(f"Ditambahkan {len(new_rows):,} pasangan ke antrian.")
    st.rerun()
