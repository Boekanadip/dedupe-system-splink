"""Dashboard: manual refresh.

Reads current artifacts on every load / on explicit refresh. No auto-refresh
timer — the operator decides when to reload.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ui import (
    DECISION_LABEL,
    format_rate,
    monitoring_sidebar,
    page_guide,
    page_header,
)

st.set_page_config(page_title="Dashboard - Entity Resolution", page_icon="📊", layout="wide")
page_header(
    "Ringkasan",
    "Kondisi hasil deduplikasi sekarang: berapa customer yang berhasil dipastikan "
    "dan berapa yang masih perlu diperiksa.",
)
monitoring_sidebar()
page_guide(__file__)

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

c1, c2 = st.columns([1, 4])
if c1.button("Refresh", type="primary"):
    st.rerun()
c2.caption("Klik Refresh untuk memuat ulang artefak terbaru.")

# ---- metrik kunci
eval_path = OUTPUT_DIR / "evaluation_report.json"
if eval_path.exists():
    report = json.loads(eval_path.read_text(encoding="utf-8"))
    entity = report.get("entity", {})
    decision = report.get("decision", {})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Customer unik", f"{entity.get('entities', 0):,}",
             help="Jumlah orang yang berhasil dipastikan setelah duplikat digabung.")
    m2.metric("Total record", f"{entity.get('records', 0):,}",
             help="Jumlah baris data masuk, sebelum ada yang digabung.")
    m3.metric("Digabung otomatis", format_rate(decision.get("rates", {}).get("auto_match_rate", 0)),
             help="Berapa persen pasangan yang sistem yakin dan langsung digabung.")
    m4.metric("Perlu diperiksa", format_rate(decision.get("rates", {}).get("review_rate", 0)),
             help="Berapa persen pasangan yang menunggu keputusan manusia.")
    if report.get("model_version"):
        st.caption(f"Model yang dipakai: `{report['model_version']}`")

# ---- keputusan
pred_path = OUTPUT_DIR / "splink_predictions.parquet"
if pred_path.exists():
    preds = pd.read_parquet(pred_path, columns=["decision", "match_probability"])
    st.subheader("Hasil keputusan")
    st.caption(
        "Setiap pasangan kandidat dapat satu dari tiga label. "
        "Yang perlu diperiksa tidak pernah digabung sendiri."
    )
    import plotly.express as px
    import plotly.graph_objects as go

    counts = preds["decision"].value_counts().sort_values(ascending=True)
    total = int(counts.sum())
    status_labels = [DECISION_LABEL.get(str(k), str(k)) for k in counts.index]
    pct_labels = [f"{value:,} ({value / total:.1%})" for value in counts.values]
    fig = go.Figure(
        go.Bar(
            x=counts.values,
            y=status_labels,
            orientation="h",
            text=pct_labels,
            textposition="outside",
            marker_color="#5aa9e6",
            textfont=dict(color="#e5e7eb"),
        )
    )
    fig.update_layout(
        title=dict(text="Hasil keputusan — urut terbanyak ke tersedikit<br><sup>Sumbu Y: status</sup>", x=0),
        xaxis_title="Jumlah pasangan",
        yaxis=dict(tickangle=0),
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#e5e7eb"),
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch")

    st.subheader("Sebaran peluang")
    st.caption(
        "Histogram peluang tiap pasangan kandidat. Punggung kiri yang tinggi "
        "berarti banyak pasangan nyaris pasti berbeda — sistem bekerja."
    )
    probs = preds["match_probability"].clip(lower=0, upper=1)
    hist, edges = pd.cut(probs, bins=25, retbins=True, include_lowest=True)
    bin_counts = hist.value_counts().sort_index()
    bin_centers = [(interval.left + interval.right) / 2 for interval in bin_counts.index]
    bin_pcts = [f"{count:,} ({count / len(probs):.1%})" for count in bin_counts.values]
    fig2 = go.Figure(
        go.Bar(
            x=bin_centers,
            y=bin_counts.values,
            width=(edges[1] - edges[0]) * 0.9,
            text=bin_pcts,
            textposition="outside",
            marker_color="#6ee7a0",
            textfont=dict(color="#e5e7eb"),
        )
    )
    fig2.update_layout(
        title=dict(text="Sebaran peluang<br><sup>Sumbu Y: jumlah pasangan</sup>", x=0),
        xaxis_title="Peluang sama",
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#e5e7eb"),
        showlegend=False,
        bargap=0,
    )
    st.plotly_chart(fig2, width="stretch")

# ---- cluster
cluster_path = OUTPUT_DIR / "cluster_summary.csv"
if cluster_path.exists():
    cluster = pd.read_csv(cluster_path)
    st.subheader("Hasil pengelompokan")
    c1, c2, c3 = st.columns(3)
    c1.metric("Customer unik", f"{int(cluster['entities'].iloc[0]):}")
    c2.metric("Record yang digabung", f"{int(cluster['records_merged'].iloc[0]):,}",
             help="Record yang berhasil dipastikan sebagai duplikat.")
    c3.metric("Perlu diperiksa", f"{int(cluster['review_pairs'].iloc[0]):,}")

history_path = OUTPUT_DIR / "incremental_history.jsonl"
if history_path.exists():
    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if history:
        st.subheader("Batch per minggu")
        df = pd.DataFrame(history)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["minggu"] = df["timestamp"].dt.to_period("W").astype(str)
        weekly = (
            df.groupby("minggu")
            .agg(batch=("batch", "count"), record_baru=("new_records", "sum"),
                 entity_baru=("new_entities", "sum"))
        )
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=weekly.index, y=weekly["batch"], mode="lines+markers", name="Batch", line=dict(color="#f2a44a", width=2)))
        fig3.add_trace(go.Scatter(x=weekly.index, y=weekly["record_baru"], mode="lines+markers", name="Record baru", line=dict(color="#4cc9f0", width=2)))
        fig3.add_trace(go.Scatter(x=weekly.index, y=weekly["entity_baru"], mode="lines+markers", name="Entity baru", line=dict(color="#7bf1a8", width=2)))
        fig3.update_layout(
            title=dict(text="Batch per minggu<br><sup>Sumbu X: minggu · Sumbu Y: jumlah</sup>", x=0),
            xaxis=dict(tickangle=0),
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font=dict(color="#e5e7eb"),
        )
        st.plotly_chart(fig3, width="stretch")
        st.caption(
            f"{len(history):,} batch tercatat, {int(df['new_records'].sum()):,} "
            "record masuk. Tabel lengkap ada di halaman Pengaturan Sistem (Riwayat Pemrosesan)."
        )

queue_path = Path(__file__).resolve().parents[1] / "data" / "labels" / "review_queue.csv"
if queue_path.exists():
    queue = pd.read_csv(queue_path)
    st.subheader("Antrean pemeriksaan")
    status = queue["review_status"].value_counts()
    reviewed = int(status.get("reviewed", 0))
    total_q = int(len(queue))
    done_rate = reviewed / total_q if total_q else 0.0
    k1, k2, k3 = st.columns(3)
    k1.metric("Perlu diperiksa", f"{total_q:,}")
    k2.metric("Sudah diperiksa", f"{reviewed:,}")
    k3.metric("Tingkat selesai", f"{done_rate:.1%}")
    st.caption(
        f"Total {total_q:,} pasangan. Yang menunggu bisa dikerjakan di halaman "
        "**Pemeriksaan**."
    )
