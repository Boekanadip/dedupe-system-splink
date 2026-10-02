"""Dashboard: charts from the latest artifacts, auto-refreshing.

Reads the current output files on every refresh, so after a retrain the numbers
move. Refresh is every 10 minutes via a Streamlit fragment; while a retrain is
running (outputs/.retraining lock exists) the refresh is skipped so it never
reads half-written artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
st.title("Dashboard")
st.caption("Visualisasi hasil — data terbaru setiap refresh (10 menit).")

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"
LOCK = OUTPUT_DIR / ".retraining"


@st.fragment(run_every=600)
def dashboard() -> None:
    if LOCK.exists():
        st.info("⏳ Retrain sedang berjalan — refresh ditunda sampai selesai.")
        return

    # ---- metrik kunci
    eval_path = OUTPUT_DIR / "evaluation_report.json"
    if eval_path.exists():
        report = json.loads(eval_path.read_text(encoding="utf-8"))
        entity = report.get("entity", {})
        decision = report.get("decision", {})
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Entity", f"{entity.get('entities', 0):,}")
        m2.metric("Record", f"{entity.get('records', 0):,}")
        m3.metric("Auto-match", f"{decision.get('rates', {}).get('auto_match_rate', 0):.2%}")
        m4.metric("Review rate", f"{decision.get('rates', {}).get('review_rate', 0):.2%}")
        if report.get("model_version"):
            st.caption(f"Model: `{report['model_version']}`")

    # ---- keputusan
    pred_path = OUTPUT_DIR / "splink_predictions.parquet"
    if pred_path.exists():
        preds = pd.read_parquet(pred_path, columns=["decision", "match_probability"])
        st.subheader("Keputusan")
        st.bar_chart(preds["decision"].value_counts())

        # Linear bins show two spikes (0 and 1) and 18 empty bins: this model
        # lives in three clusters (1.0, ~1e-10, ~1e-94) and the gaps between
        # them carry no pairs. log10 makes the three clusters readable.
        st.subheader("Distribusi skor (skala log10)")
        positive = preds.loc[preds["match_probability"] > 0, "match_probability"]
        clipped = positive.clip(lower=1e-100)
        hist, edges = np.histogram(np.log10(clipped), bins=30)
        st.bar_chart(
            pd.Series(hist, index=[f"{e:.0f}" for e in edges[:-1]]),
        )
        st.caption(
            "Sumbu x = log10(P). Tiga klaster: 0 (=P 1.0, MATCH), −10 (band "
            "REVIEW), dan sekitar −40..−94 (NON_MATCH). Kosongnya bin di "
            "antaranya adalah sifat dataset ini — duplikat identik di semua "
            "field — bukan bug chart."
        )

    # ---- cluster
    cluster_path = OUTPUT_DIR / "cluster_summary.csv"
    if cluster_path.exists():
        cluster = pd.read_csv(cluster_path)
        st.subheader("Cluster")
        st.caption(
            f"Entities: {int(cluster['entities'].iloc[0]):,} · "
            f"Match edges: {int(cluster['match_edges'].iloc[0]):,} · "
            f"Review pairs: {int(cluster['review_pairs'].iloc[0]):,}"
        )

    # ---- entity dari waktu ke waktu (mingguan; per-run terlalu rapat kalau
    # upload datang berturut-turut dalam hari yang sama)
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
                "record masuk. Tabel lengkap ada di halaman Retrain (Retrain history)."
            )

    # ---- review queue
    queue_path = Path(__file__).resolve().parents[1] / "data" / "labels" / "review_queue.csv"
    if queue_path.exists():
        queue = pd.read_csv(queue_path)
        st.subheader("Review queue")
        status = queue["review_status"].value_counts()
        st.bar_chart(status)
        st.caption(f"Total {len(queue):,} pasangan")


dashboard()
