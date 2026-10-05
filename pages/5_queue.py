"""Halaman cakupan antrean pemeriksaan.

Antrean pemeriksaan hanya sampel dari ribuan pasangan yang perlu diperiksa.
Halaman ini menampilkan seluruhnya, lalu menunjukkan pasangan mana yang sudah
masuk antrean dan mana yang belum, supaya bisa langsung dikerjakan.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import LABELS_DIR, OUTPUT_DIR
from src.ui import (
    format_probability,
    how_to_read,
    monitoring_sidebar,
    page_guide,
    page_header,
    paginate,
    probability_verdict,
)

st.set_page_config(page_title="Antrean - Entity Resolution", page_icon="📋", layout="wide")
page_header(
    "Antrean Pemeriksaan",
    "Semua pasangan yang perlu diperiksa manusia. Antrean kerja hanya mengambil "
    "sebagian kecil dari daftar ini.",
)
monitoring_sidebar()
page_guide(__file__)
how_to_read()

QUEUE_PATH = LABELS_DIR / "review_queue.csv"
PREDS_PATH = OUTPUT_DIR / "splink_predictions.parquet"

if not PREDS_PATH.exists():
    st.info("Belum ada data hasil pemeriksaan. Jalankan pipeline dulu dari halaman Upload.")
    st.stop()

preds = pd.read_parquet(
    PREDS_PATH,
    columns=["record_id_l", "record_id_r", "match_probability", "decision"],
)
# Filter lewat kolom decision, bukan perbandingan angka, supaya halaman ini
# selalu sama dengan yang dipakai pipeline.
review = preds[preds["decision"] == "REVIEW"].copy()

if QUEUE_PATH.exists():
    queue = pd.read_csv(QUEUE_PATH)
    queued = set(zip(queue["record_id_l"], queue["record_id_r"]))
else:
    queued = set()
review["sudah_di_antrean"] = [
    (l, r) in queued for l, r in zip(review["record_id_l"], review["record_id_r"])
]

st.subheader("Ringkasan")
total = len(review)
n_queued = int(review["sudah_di_antrean"].sum())
m1, m2, m3 = st.columns(3)
m1.metric("Pasangan perlu diperiksa", f"{total:,}", help="Semua pasangan yang tidak yakin, sebelum diantrekan.")
m2.metric("Sudah masuk antrean", f"{n_queued:,}", help="Tersedia di halaman Pemeriksaan untuk Anda nilai.")
m3.metric("Belum masuk antrean", f"{total - n_queued:,}", help="Belum pernah dilihat manusia.")

st.subheader("Saring")
f1, f2 = st.columns(2)
queued_filter = f1.selectbox(
    "Sudah di antrean?", ["(semua)", "Sudah", "Belum"]
)
score_min = f2.slider("Peluang minimal", 0.0, 1.0, 0.0)
filtered = review[review["match_probability"] >= score_min]
if queued_filter == "Sudah":
    filtered = filtered[filtered["sudah_di_antrean"]]
elif queued_filter == "Belum":
    filtered = filtered[~filtered["sudah_di_antrean"]]
st.caption(f"Menampilkan {len(filtered):,} dari {total:,} pasangan.")

st.subheader("Daftar pasangan")
page_df, _ = paginate(filtered, page_size=50, key="queue_page")
table = page_df[["record_id_l", "record_id_r", "match_probability", "sudah_di_antrean"]].copy()
table["Peluang sama"] = table["match_probability"].map(format_probability)
table["Di antrean"] = table["sudah_di_antrean"].map(
    {True: "Sudah", False: "Belum"}
)
table["Record A"] = table["record_id_l"]
table["Record B"] = table["record_id_r"]
st.dataframe(
    table[["Record A", "Record B", "Peluang sama", "Di antrean"]],
    width="stretch",
    hide_index=True,
    height=460,
)

if not filtered.empty:
    st.caption(probability_verdict(float(filtered["match_probability"].max())))

st.subheader("Masukkan ke antrean kerja")
st.caption(
    "Pasangan yang sedang disaring di atas akan ditambahkan ke antrean, supaya "
    "bisa diputuskan di halaman **Pemeriksaan**. Memakai antrean tidak mengubah "
    "data asli apa pun."
)
if st.button("Tambahkan yang disaring ke antrean"):
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
    st.success(f"Menambahkan {len(new_rows):,} pasangan ke antrean kerja.")
    st.rerun()
