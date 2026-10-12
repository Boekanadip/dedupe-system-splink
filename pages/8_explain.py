"""Halaman "Kenapa?" — untuk menjawab satu pertanyaan: kenapa sistem mengambil
keputusan itu untuk sepasang record.

Perbedaan inti dari halaman lain: di sini semua data dari kedua record
dibandingkan berdampingan sekaligus, beserta seberapa kuat tiap data mendukung
atau menolak anggapan bahwa keduanya orang yang sama.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import MATCH_THRESHOLD, OUTPUT_DIR, REVIEW_THRESHOLD, predictions_path
from src.ui import (
    workflow_step,
    decision_label,
    format_probability,
    format_rate,
    how_to_read,
    model_levels,
    monitoring_sidebar,
    page_guide,
    page_header,
    probability_verdict,
    show_evidence,
    verdict_plain,
)

st.set_page_config(page_title="Kenapa - Entity Resolution", page_icon="🔍", layout="wide")
page_header(
    "Kenapa Sistem Bilang Begitu?",
    "Pilih dua record, lalu lihat satu per satu apakah tiap data mereka "
    "mendukung atau menolak anggapan bahwa mereka orang yang sama.",
)
monitoring_sidebar()
page_guide(__file__)
workflow_step(__file__)
how_to_read()

preds_path = predictions_path(full=True)
if not preds_path.exists():
    st.info("Belum ada data hasil pemeriksaan. Jalankan pipeline dulu dari halaman Upload.")
    st.stop()

levels = model_levels()
if not levels:
    st.warning("Belum ada model yang tersimpan, jadi bobot per field tidak bisa ditampilkan.")
    st.stop()

preds = pd.read_parquet(preds_path)
st.caption(
    "Aturan penyimpulan: peluang **90% ke atas** digabung otomatis, "
    "**nyaris 0%** dianggap berbeda orang, sisanya menunggu keputusan manusia. "
    "Bobot setiap field diambil dari model yang sedang dipakai."
)

# Daftar berisi PASANGAN yang benar-benar pernah dibandingkan, bukan dua
# dropdown bebas. Dulu memilih dua record secara terpisah menghasilkan ribuan
# kombinasi yang tidak pernah disaring, dan halaman berhenti di pesan "tidak
# pernah dibandingkan" — padahal yang dicari orang adalah alasan kenapa sebuah
# pasangan digabung atau dipisah.
#
# VECTORIZED on purpose: the first version built the label with .apply() over
# 1.1M rows, which took tens of seconds and made the page look hung. String
# concatenation and .map() run in C and finish immediately.
compared = preds[
    ["record_id_l", "record_id_r", "match_probability", "decision"]
].copy()
compared["pasangan"] = (
    compared["record_id_l"].astype(str) + "  ↔  " + compared["record_id_r"].astype(str)
)
compared = compared.sort_values("match_probability", ascending=False).reset_index(drop=True)
compared["label_pil"] = (
    compared["pasangan"]
    + " · " + compared["decision"].map(decision_label)
    + " · " + compared["match_probability"].map(format_probability)
)

st.caption(f"Menampilkan {len(compared):,} pasangan yang pernah dibandingkan sistem.")
pick_idx = st.selectbox(
    "Pilih pasangan",
    range(len(compared)),
    format_func=lambda i: compared.loc[i, "label_pil"],
    key="explain_pair",
)
row = compared.loc[pick_idx]

pair = preds[
    (preds["record_id_l"] == row["record_id_l"])
    & (preds["record_id_r"] == row["record_id_r"])
]
if pair.empty:
    st.warning("Pasangan ini tidak lagi ada di hasil prediksi terbaru.")
    st.stop()
p = pair.iloc[0].to_dict()

probability = float(p.get("match_probability", 0) or 0)
m1, m2 = st.columns(2)
m1.metric("Peluang sama", format_probability(probability))
m2.metric("Keputusan sistem", decision_label(p.get("decision", "-")))
st.caption(f"Skor tanpa pembulatan: P={probability:.3e}; match_weight={float(p['match_weight']):.2f} (log2 odds).")

st.info(probability_verdict(probability))
st.caption(verdict_plain(p.get("decision", "-")))

st.subheader("Bukti satu per satu")
st.caption(
    "Urut dari yang paling kuat mendukung sampai yang paling menolak. "
    "Klik kolom untuk melihat nilai aslinya."
)
show_evidence(p, levels)

support = 0.0
against = 0.0
for field in ("first_name_std", "last_name_std", "email_std", "phone_std",
              "dob_std", "address_std", "city_std", "state_std", "country_std"):
    gamma_col = f"gamma_gamma_{field}"
    code = p.get(gamma_col)
    if code is None or pd.isna(code):
        continue
    _, m, u = levels.get(gamma_col, {}).get(int(code), (None, 0.0, 0.0))
    if m > 0 and u > 0:
        import math

        weight = math.log2(m / u)
        support += max(weight, 0.0)
        against += min(weight, 0.0)

c1, c2 = st.columns(2)
c1.metric("Total bukti mendukung", f"+{support:.0f}")
c2.metric("Total bukti menolak", f"{against:.0f}")
st.caption(
    "Bukti positif berarti data yang sama sulitnya muncul kalau kebetulan orang "
    "beda. Bukti negatif sebaliknya. Untuk kota, provinsi, dan negara, sistem "
    "mengurangi bobot nama yang umum (misal \"Springfield\") karena nama "
    "seperti itu banyak dipakai orang berbeda."
)

if p.get("decision") == "REVIEW":
    st.info(
        "Pasangan ini menunggu keputusan manusia. Buka halaman **Pemeriksaan** "
        "untuk menilai sendiri — angka di sini tidak otomatis dipakai."
    )
