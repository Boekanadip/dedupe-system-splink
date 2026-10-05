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
        st.warning("Lock retrain basi (proses sudah mati). Bersihkan di halaman Model.")

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
    counts = preds["decision"].value_counts()
    chart = pd.DataFrame(
        {
            "Jumlah pasangan": counts.values,
            "Status": [DECISION_LABEL.get(str(k), str(k)) for k in counts.index],
        }
    ).set_index("Status")
    st.bar_chart(chart)

    st.subheader("Sebaran peluang")
    st.caption(
        "Seberapa yakin sistem untuk tiap pasangan. Tiga kelompok yang terpisah "
        "jelas berarti sistem bekerja: yang hampir pasti sama, yang ragu-ragu, "
        "dan yang hampir pasti berbeda."
    )
    buckets = pd.cut(
        preds["match_probability"],
        bins=[-0.001, 0.0001, 0.5, 0.9, 1.0001],
        labels=[
            "Hampir pasti berbeda",
            "Ragu-ragu",
            "Cenderung sama",
            "Hampir pasti sama",
        ],
    )
    bucket_counts = buckets.value_counts().reindex(
        ["Hampir pasti sama", "Cenderung sama", "Ragu-ragu", "Hampir pasti berbeda"]
    )
    st.bar_chart(bucket_counts)

# ---- cluster
cluster_path = OUTPUT_DIR / "cluster_summary.csv"
if cluster_path.exists():
    cluster = pd.read_csv(cluster_path)
    st.subheader("Hasil pengelompokan")
    c1, c2, c3 = st.columns(3)
    c1.metric("Customer unik", f"{int(cluster['entities'].iloc[0]):,}")
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
        st.bar_chart(weekly)
        st.caption(
            f"{len(history):,} batch tercatat, {int(df['new_records'].sum()):,} "
            "record masuk. Tabel lengkap ada di halaman Model (Retrain history)."
        )

queue_path = Path(__file__).resolve().parents[1] / "data" / "labels" / "review_queue.csv"
if queue_path.exists():
    queue = pd.read_csv(queue_path)
    st.subheader("Antrean pemeriksaan")
    status = queue["review_status"].value_counts()
    chart = pd.DataFrame(
        {
            "Jumlah pasangan": status.values,
            "Status": [
                "Sudah diperiksa" if str(k) == "reviewed" else "Menunggu"
                for k in status.index
            ],
        }
    ).set_index("Status")
    st.bar_chart(chart)
    st.caption(
        f"Total {len(queue):,} pasangan. Yang menunggu bisa dikerjakan di halaman "
        "**Pemeriksaan**."
    )
