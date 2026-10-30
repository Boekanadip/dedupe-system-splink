"""Dasbor: penyegaran manual"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

import sys
from pathlib import Path

from src.ui import (
    workflow_step,
    DECISION_LABEL,
    format_rate,
    monitoring_sidebar,
    page_guide,
    page_header,
)
from src.config import (
    ENTITY_MAP_PATH,
    PROCESSED_DATA_PATH,
    SMOKE_SAMPLE_SIZE,
    predictions_path,
    read_meta,
)
from src.export import csv_bytes, save_to_database

st.set_page_config(page_title="Dashboard - Entity Resolution", page_icon="📊", layout="wide")
page_header(
    "Ringkasan",
    "Kondisi hasil deduplikasi sekarang: berapa customer yang berhasil dipastikan "
    "dan berapa yang masih perlu diperiksa.",
)
monitoring_sidebar()
page_guide(__file__)
workflow_step(__file__)

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"
LOCK = OUTPUT_DIR / ".retraining"

if LOCK.exists():
    try:
        pid = int(LOCK.read_text(encoding="utf-8").strip())
    except Exception:
        pid = None

    import psutil
    alive = bool(pid and psutil.pid_exists(pid))
    if alive:
        st.info("Retrain berjalan — dashboard bisa menunda refresh sampai lock hilang.")
    else:
        st.warning("Lock retrain basi (proses sudah mati). Bersihkan di halaman Pengaturan Sistem.")

st.set_page_config(page_title="Dashboard - Entity Resolution", page_icon="📊", layout="wide")
page_header(
    "Ringkasan",
    "Kondisi hasil deduplikasi sekarang: berapa customer yang berhasil dipastikan "
    "dan berapa yang masih perlu diperiksa.",
)
monitoring_sidebar()
page_guide(__file__)
workflow_step(__file__)

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"
LOCK = OUTPUT_DIR / ".retraining"

# =============================================================================
# LAPORAN PEMILIHAN KOLOM DINAMIS
# =============================================================================

st.subheader("🔧 Pilih Kolom untuk Pencocokan")
st.caption(
    "Pilih atribut mana yang ingin Anda gunakan untuk membandingkan dua record. "
    "Pilihan ini akan membentuk konfigurasi Splink baru secara dinamis dan memengaruhi "
    "proses pencocokan, bukan hanya tampilan. Tabel sumber tidak pernah ditimpa."
)

# Dapatkan daftar kolom standar yang valid
valid_columns = sorted(list(get_valid_comparison_columns()))

# Dapatkan kolom yang ada di data standar (jika file ada)
available_cols = valid_columns.copy()
if PROCESSED_DATA_PATH.exists():
    try:
        df_sample = pd.read_parquet(PROCESSED_DATA_PATH)
        available_cols = [c for c in valid_columns if c in df_sample.columns]
    except Exception:
        available_cols = valid_columns  # fallback

# Inisialisasi session state
if "selected_match_cols" not in st.session_state:
    st.session_state.selected_match_cols = available_cols[:4] if available_cols else []

# Tampilkan kolom yang tersedia
st.caption("Kolom standar yang tersedia:")
for col in valid_columns:
    st.caption(f"• {col}")

# Pilihan kolom pengguna
selected_cols = st.session_state.selected_match_cols
st.subheader("Kolom yang dipilih")
if selected_cols:
    st.info(f"✅ Kolom yang dipilih: {', '.join(selected_cols)}")
else:
    st.info("Belum ada kolom yang dipilih.")

# Tombol jalankan ulang
c1, c2 = st.columns([3, 1])
with c1:
    st.button("🔄 Jalankan Ulang dengan Kolom Ini", type="primary", disabled=not selected_cols)
with c2:
    st.caption("Klik tombol untuk menjalankan ulang dengan kolom yang dipilih")

# =============================================================================
# MAIN CONTENT AREA
# =============================================================================

# Dashboard header
st.set_page_config(page_title="Dashboard - Entity Resolution", page_icon="📊", layout="wide")
page_header(
    "Ringkasan",
    "Kondisi hasil deduplikasi sekarang: berapa customer yang berhasil dipastikan "
    "dan berapa yang masih perlu diperiksa.",
)
monitoring_sidebar()
page_guide(__file__)
workflow_step(__file__)

# =============================================================================
# Metrik Kunci
# =============================================================================

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"
LOCK = OUTPUT_DIR / ".retraining"

if LOCK.exists():
    try:
        pid = int(LOCK.read_text(encoding="utf-8").strip())
    except Exception:
        pid = None
    import psutil
    alive = bool(pid and psutil.pid_exists(pid))
    if alive:
        st.info("Retrain berjalan — dashboard bisa menunda refresh sampai lock hilang.")
    else:
        st.warning("Lock retrain basi (proses sudah mati). Bersihkan di halaman Pengaturan Sistem.")

# ==============================
# Metrik Kunci
# =============================================================================

eval_path = OUTPUT_DIR / "evaluation_report.json"
report = json.loads(eval_path.read_text(encoding="utf-8")) if eval_path.exists() else {}
report_meta = read_meta(ENTITY_MAP_PATH)
scope = entity_meta.get("scope", report.get("scope", "full"))
full_scope = scope != "sample"
pred_path = predictions_path(full=full_scope)
prediction_stamp = ""
prediction_meta = {}

preds = pd.DataFrame()
if pred_path.exists():
    prediction_stat = pred_path.stat()
    prediction_stamp = f"{scope}-{prediction_stat.st_mtime_ns}-{prediction_stat.st_size}"
    prediction_meta = read_meta(pred_path)
    preds = pd.read_parquet(
        pred_path,
        columns=["decision", "match_probability", "record_id_l", "record_id_r"],
    )

# Hitung metrik kunci
decision_counts = (
    preds["decision"].value_counts()
    if not preds.empty and "decision" in preds
    else pd.Series(dtype="int64")
)
candidate_pairs = int(decision_counts.sum())
review_pairs = int(decision_counts.get("REVIEW", 0))
predictions_available = pred_path.exists() and "decision" in preds

# Distribusi keputusan
st.subheader("Hasil keputusan")
c1, c2 = st.columns([1, 4])
c1.metric("Customer unik", f"{live_entities if live_entities is not None else 0:,}",
          help="Jumlah customer yang berhasil dipastikan setelah duplikat digabung.")
c2.metric("Record yang digabung", f"{records_merged:,}",
          help="Record yang berhasil dipastikan sebagai duplikat.")

c1, c2, c3 = st.columns([1, 4, 4])
c1.caption(f"Total customer: {live_records:,}")
c2.metric("Customer dipastikan", f"{live_entities:,}")
c3.metric("Pasangan REVIEW", f"{review_pairs:,}", 
          help="Pasangan yang belum diputuskan secara final")

# Histogram keputusan
if preds.empty:
    st.info("Belum ada hasil prediksi. Silakan jalankan proses deduplikasi.")
else:
    # Buat histogram keputusan
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=counts.index,
        y=counts.values,
        text=counts.values,
        textposition="outside",
        marker_color="#f2a44a" if counts.index[0] == "MATCH" else 
               "#4cc9f0" if counts.index[0] == "REVIEW" else "#666",
        ))
    fig.update_layout(
        title="Distribusi Keputusan",
        xaxis_title="Status",
        yaxis_title="Jumlah pasangan",
        template="plotly_dark",
        font=dict(color="#e5e7eb"),
    )
    st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# Ekspor Hasil
# =============================================================================
st.subheader("📊 Unduh / Simpan Hasil")
st.caption(
    "Dua opsi di bawah berdiri sendiri: mengunduh CSV tidak memerlukan database, "
    "dan menyimpan ke database tidak memerlukan unduhan."
)

# Buat DataFrame ekspor dengan kolom yang relevan
export_df = preds.copy()
if not export_df.empty:
    # Pastikan kolom keputusan ada
    if "decision" not in export_df.columns and "match_probability" in export_df.columns:
        export_df["decision"] = export_df["match_probability"].apply(
            lambda p: "MATCH" if p >= match_threshold
            else ("REVIEW" if p >= review_threshold else "NON_MATCH")
        )
    
    if "decision" in export_df.columns:
        reviewed = int((export_df["decision"] == "REVIEW").sum())
        if reviewed:
            st.warning(
                f"⚠️ Hasil belum bersih: {reviewed:,} pasangan masih berstatus REVIEW "
                "dan belum diputuskan."
            )
    
    # Tombol unduh CSV
    with c_dl:
        st.download_button(
            "Unduh CSV",
            data=csv_bytes(export_df),
            file_name="hasil_deduplikasi.csv",
            mime="text/csv",
            disabled=export_df.empty,
            help="Tidak ada hasil untuk diunduh" if export_df.empty else "Unduh hasil dedupasi saat ini"
        )
    
    with c_db:
        db_table = st.text_input(
            "Nama tabel tujuan", 
            value="splink_data.dedup_outputs",
            help="Nama tabel tujuan. Tabel sumber tidak pernah ditimpa."
        )
        if st.button("Simpan ke database", disabled=export_df.empty):
            try:
                rows = save_to_database(export_df, db_table)
                st.success(f"✅ Berhasil disimpan: {rows:,} baris ke {db_table}.")
            except Exception as e:
                st.error(f"❌ Gagal menyimpan: {str(e)}")