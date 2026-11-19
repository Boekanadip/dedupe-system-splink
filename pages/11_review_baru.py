"""Dashboard baru: sidebar nav + KPI cards + charts + activity + insights."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from src.ui import page_header, render_sidebar
from src.splink_model import get_valid_comparison_columns
from src.config import (
    ENTITY_MAP_PATH,
    MASTER_PATH,
    PROCESSED_DATA_PATH,
    SMOKE_SAMPLE_SIZE,
    predictions_path,
    read_meta,
)
from src.data_access import read_entity_map, read_master, read_pairs, read_processed

st.set_page_config(page_title="Dashboard - Entity Resolution", page_icon="📊", layout="wide")

# ── Custom CSS (warna persis mockup) ──────────────────────────────────────
st.markdown(
    """
    <style>
    :root {
        --bg:#f5f5f5;
        --sidebar:#f8f9fa;
        --text:#333;
        --muted:#666;
        --border:#e2e8f0;
        --accent-match:#f2a44a;
        --accent-review:#4cc9f0;
        --accent-primary:#007bff;
    }
    .main {background:var(--bg);}
    .sidebar .stSidebar {background:var(--sidebar);}
    .stButton>button {width:100%;}
    .stat-card {
        background:white;
        padding:16px 20px;
        border-radius:8px;
        border:1px solid var(--border);
        margin:8px 0;
        text-align:center;
    }
    .stat-value {font-size:2rem;font-weight:700;color:var(--accent-match);}
    .stat-label {color:var(--muted);font-size:0.85rem;margin-top:4px;}
    .stSelectbox>div>div>div {border:1px solid var(--border);}
    .insight-card {
        background:white;
        padding:16px 20px;
        border-radius:8px;
        border:1px solid var(--border);
        margin:12px 0;
    }
    .badge {padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:600;}
    .badge-pass {background:#e6fffa;color:#047857;}
    .badge-warning {background:#fffbeb;color:#d97706;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Helper: load data ────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"

@st.cache_data(ttl=600)
def _load_preds():
    p = predictions_path(full=True)
    if p.exists():
        return read_pairs(columns=["decision", "match_probability", "record_id_l", "record_id_r"])
    return pd.DataFrame()

@st.cache_data(ttl=600)
def _load_entity_map():
    return read_entity_map()

@st.cache_data(ttl=600)
def _load_history():
    h = OUTPUT_DIR / "incremental_history.jsonl"
    if h.exists():
        rows = []
        for line in h.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        return pd.DataFrame(rows)
    return pd.DataFrame()

@st.cache_data(ttl=600)
def _load_shadow():
    s = OUTPUT_DIR / "shadow_test.json"
    if s.exists():
        return json.loads(s.read_text(encoding="utf-8"))
    return {}

@st.cache_data(ttl=600)
def _load_eval():
    e = OUTPUT_DIR / "evaluation_report.json"
    if e.exists():
        return json.loads(e.read_text(encoding="utf-8"))
    return {}

preds = _load_preds()
entity_map = _load_entity_map()
history_df = _load_history()
shadow = _load_shadow()
eval_report = _load_eval()

entity_count = int(entity_map["entity_id"].nunique()) if not entity_map.empty else 0
record_count = len(entity_map)
records_merged = max(0, record_count - entity_count)

# ── Hitung metrik ────────────────────────────────────────────────────────
if not preds.empty and "decision" in preds.columns:
    dc = preds["decision"].value_counts()
    review_pairs = int(dc.get("REVIEW", 0))
    match_pairs = int(dc.get("MATCH", 0))
    non_match_pairs = int(dc.get("NON_MATCH", 0))
    total_pairs = int(dc.sum())
    pct_match = round(match_pairs / total_pairs * 100, 1) if total_pairs else 0.0
else:
    dc = pd.Series(dtype="int64")
    review_pairs = 0
    match_pairs = 0
    non_match_pairs = 0
    total_pairs = 0
    pct_match = 0.0

# ── Sidebar ──────────────────────────────────────────────────────────────
render_sidebar("dashboard")

st.sidebar.markdown("### Filter")
status_filter = st.sidebar.radio(
    "Filter pasangan",
    ["Semua", "MATCH", "REVIEW", "NON_MATCH"],
    index=0,
    help="Filter tampilan histogram & tabel.",
)

# ── Header ───────────────────────────────────────────────────────────────
page_header(
    "Ringkasan",
    "Kondisi hasil deduplikasi sekarang: berapa customer yang berhasil dipastikan "
    "dan berapa yang masih perlu diperiksa.",
)

# ── KPI Cards ────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(
        f'<div class="stat-card"><div class="stat-value">{entity_count:,}</div>'
        f'<div class="stat-label">Customer unik</div></div>',
        unsafe_allow_html=True,
    )
with c2:
    st.markdown(
        f'<div class="stat-card"><div class="stat-value">{records_merged:,}</div>'
        f'<div class="stat-label">Record digabung</div></div>',
        unsafe_allow_html=True,
    )
with c3:
    st.markdown(
        f'<div class="stat-card"><div class="stat-value">{review_pairs:,}</div>'
        f'<div class="stat-label">Pasangan REVIEW</div></div>',
        unsafe_allow_html=True,
    )
with c4:
    st.markdown(
        f'<div class="stat-card"><div class="stat-value">{pct_match}%</div>'
        f'<div class="stat-label">Persentase MATCH</div></div>',
        unsafe_allow_html=True,
    )

# ── Charts ───────────────────────────────────────────────────────────────
st.subheader("Distribusi Keputusan")
if not preds.empty and "decision" in preds.columns:
    filtered = preds if status_filter == "Semua" else preds[preds["decision"] == status_filter.lower()]
    fig = go.Figure()
    if not filtered.empty:
        counts = filtered["decision"].value_counts()
        colors = {"MATCH": "#f2a44a", "REVIEW": "#4cc9f0", "NON_MATCH": "#666"}
        for d in counts.index:
            fig.add_trace(go.Bar(x=[d], y=[counts[d]], marker_color=colors.get(d, "#666")))
    fig.update_layout(
        template="plotly_dark",
        font=dict(color="#e5e7eb"),
        showlegend=False,
        margin=dict(l=0, r=0, t=30, b=0),
    )
    st.plotly_chart(fig, width='stretch')

st.subheader("Persentase Probabilitas Match")
if not preds.empty and "match_probability" in preds.columns:
    fig2 = go.Figure(data=[go.Histogram(x=preds["match_probability"], nbinsx=10, marker_color="#007bff")])
    fig2.update_layout(
        template="plotly_dark",
        font=dict(color="#e5e7eb"),
        xaxis_title="Probabilitas",
        yaxis_title="Jumlah pasangan",
        margin=dict(l=0, r=0, t=30, b=0),
    )
    st.plotly_chart(fig2, width='stretch')

# ── Activity Feed ────────────────────────────────────────────────────────
st.subheader("Aktivitas Terbaru")
if not history_df.empty:
    recent = history_df.tail(5).sort_values("timestamp", ascending=False)
    for _, r in recent.iterrows():
        ts = r.get("timestamp", "")
        batch = r.get("batch", "unknown")
        rows = r.get("rows", 0)
        runtime = r.get("runtime_seconds", 0)
        st.markdown(
            f'<div class="insight-card">'
            f'<strong>{batch}</strong>: {rows} rows • {runtime:.1f}s • {ts}'
            f'</div>',
            unsafe_allow_html=True,
        )
    if st.button("Refresh aktivitas", key="refresh_activity"):
        st.rerun()
else:
    st.info("Belum ada riwayat aktivitas. Jalankan pipeline dari Upload Data.")

# ── Insights Panel ───────────────────────────────────────────────────────
st.subheader("Insights")
c1, c2 = st.columns(2)
with c1:
    verdict = shadow.get("verdict", "UNKNOWN")
    badge_cls = "badge-pass" if verdict == "PASS" else "badge-warning"
    st.markdown(
        f'<div class="insight-card">'
        f'<strong>Verdict</strong>: <span class="badge {badge_cls}">{verdict}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
with c2:
    entities_shadow = shadow.get("arm_084", {}).get("entities", "-")
    st.markdown(
        f'<div class="insight-card">'
        f'<strong>Entitas (threshold 0.84)</strong>: {entities_shadow}'
        f'</div>',
        unsafe_allow_html=True,
    )

st.caption(
    f"Referensi mockup: 51.555 pasangan • 92,3% match. "
    f"Data aktual: {total_pairs:,} pasangan • {pct_match}% match "
    f"({entity_count:,} customer unik, {records_merged:,} record digabung, "
    f"{review_pairs:,} pasangan REVIEW)."
)

# ── Tabel pasangan (opsional) ────────────────────────────────────────────
with st.expander("Lihat pasangan detail", expanded=False):
    if not preds.empty and "decision" in preds.columns:
        disp = preds if status_filter == "Semua" else preds[preds["decision"] == status_filter.lower()]
        st.dataframe(
            disp[["record_id_l", "record_id_r", "match_probability", "decision"]]
            .head(50),
            column_config={
                "match_probability": st.column_config.ProgressColumn(
                    "Probabilitas", min_value=0, max_value=1
                )
            },
            hide_index=True,
            width='stretch',
        )
    else:
        st.info("Belum ada hasil prediksi.")