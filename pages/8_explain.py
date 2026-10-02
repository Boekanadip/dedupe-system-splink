"""Explain: why did the system decide MATCH/REVIEW/NON_MATCH for one pair.

Reads the gamma comparison vector + m/u from the active model, converts each
field into its log2(m/u) Bayes-weight contribution, and shows side-by-side
values with agree/mismatch flags. Thresholds from src/config (with override).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import MATCH_THRESHOLD, OUTPUT_DIR, REVIEW_THRESHOLD, predictions_path
from src.labels import REVIEW_FIELDS
from src import model_lifecycle

st.set_page_config(page_title="Explain", page_icon="🔍", layout="wide")
st.title("Explain: kenapa pasangan ini diputuskan begitu?")
st.caption(
    "Bobot per field (log2 m/u dari model aktif) + nilai side-by-side. "
    "Positif = bukti mendukung match, negatif = bukti menolak. "
    "city/state/country pakai term-frequency adjustment, jadi jumlah bobot "
    "tidak persis sama dengan total weight."
)

preds_path = predictions_path(full=True)
if not preds_path.exists():
    st.info("Belum ada predictions. Jalankan pipeline dulu.")
    st.stop()

preds = pd.read_parquet(preds_path)
latest = model_lifecycle.latest()
if latest is None:
    st.warning("Tidak ada model tersimpan.")
    st.stop()
model = model_lifecycle.load_model_json(latest)
settings = model.get("settings", model)

# gamma code -> (label, m, u) per comparison. Splink numbers the levels with the
# HIGHEST code = first listed level (exact match); verified against match_weight
# on three real pairs (sum of log2(m/u) + prior reproduces it within TF-adjust
# rounding on city/state/country).
LEVELS: dict[str, dict[int, tuple[str, float, float]]] = {}
for comp in settings.get("comparisons", []):
    col = "gamma_" + comp.get("output_column_name", "")
    levels = [
        (
            str(lvl.get("label_for_charts", f"level {i}"))[:60],
            float(lvl.get("m_probability", 0) or 0),
            float(lvl.get("u_probability", 0) or 0),
        )
        for i, lvl in enumerate(comp.get("comparison_levels", []))
    ]
    n = len(levels)
    LEVELS[col] = {n - 1 - i: levels[i] for i in range(n)}

FIELD_OF = {
    "gamma_gamma_first_name_std": "first_name",
    "gamma_gamma_last_name_std": "last_name",
    "gamma_gamma_email_std": "email",
    "gamma_gamma_address_std": "address",
    "gamma_gamma_city_std": "city",
    "gamma_gamma_state_std": "state",
    "gamma_gamma_country_std": "country",
    "gamma_gamma_dob_std": "dob",
    "gamma_gamma_phone_std": "phone",
}
VALCOL = {f: f"{f}_std" for f in FIELD_OF.values()}

c1, c2 = st.columns(2)
l_ids = sorted(preds["record_id_l"].unique().tolist())
r_ids = sorted(preds["record_id_r"].unique().tolist())
rid_l = c1.selectbox("Record L", l_ids, index=0)
rid_r = c2.selectbox("Record R", [r for r in r_ids if r != rid_l] or r_ids)

pair = preds[
    ((preds["record_id_l"] == rid_l) & (preds["record_id_r"] == rid_r))
    | ((preds["record_id_l"] == rid_r) & (preds["record_id_r"] == rid_l))
]
if pair.empty:
    st.warning("Pasangan ini tidak pernah jadi kandidat (tidak diblock bersama). Artinya: sistem tidak pernah menilainya — recall ceiling, bukan keputusan model.")
    st.stop()
p = pair.iloc[0].to_dict()

m1, m2, m3 = st.columns(3)
m1.metric("Decision", p.get("decision", "-"))
m2.metric("P(match)", f"{p.get('match_probability', 0):.4g}")
m3.metric("Total weight", f"{p.get('match_weight', 0):.2f}")
st.caption(f"Threshold: MATCH ≥ {MATCH_THRESHOLD} · REVIEW ≥ {REVIEW_THRESHOLD} · model `{latest.name}`")

rows = []
for gcol, fname in FIELD_OF.items():
    code = p.get(gcol)
    label, m, u = LEVELS.get(gcol, {}).get(int(code) if pd.notna(code) else -1, ("?", 0, 0))
    w = math.log2(m / u) if m > 0 and u > 0 else None
    lv, rv = p.get(f"{VALCOL[fname]}_l"), p.get(f"{VALCOL[fname]}_r")
    rows.append({
        "field": fname,
        "L": "" if pd.isna(lv) else str(lv),
        "cocok?": "✅" if str(lv) == str(rv) and pd.notna(lv) else ("➖" if pd.isna(lv) or pd.isna(rv) else "❌"),
        "R": "" if pd.isna(rv) else str(rv),
        "level": label,
        "bobot": round(w, 2) if w is not None else None,
    })
ev = pd.DataFrame(rows).sort_values("bobot", ascending=False, na_position="last")
st.subheader("Bukti per field (diurut kontribusi)")
st.dataframe(ev, use_container_width=True, hide_index=True)

pos = ev[ev["bobot"].fillna(0) > 0]["bobot"].sum()
neg = ev[ev["bobot"].fillna(0) < 0]["bobot"].sum()
st.info(
    f"Mendukung match: +{pos:.1f} · Menolak: {neg:.1f} · "
    + ("Keputusan MATCH karena bukti positif dominan." if p.get("decision") == "MATCH"
       else "Keputusan REVIEW: bukti campur — manusia yang memutuskan, bukan model." if p.get("decision") == "REVIEW"
       else "Keputusan NON_MATCH: bukti menolak dominan.")
)
