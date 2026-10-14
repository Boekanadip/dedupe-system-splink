"""Dasbor: penyegaran manual.

Artefak terbaru dibaca setiap kali halaman dimuat atau saat disegarkan secara
manual. Tidak ada penyegaran otomatis; operator menentukan kapan harus memuat
ulang.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ui import (
    workflow_step,
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
    linkage = report.get("linkage", {})
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

    # ---- kualitas penggabungan.
    precision = linkage.get("precision_on_truth")
    mixed = entity.get("entities_mixing_two_device_ids")
    if precision is not None or mixed is not None:
        st.subheader("Kualitas penggabungan")
        q1, q2, q3 = st.columns(3)
        q1.metric(
            "Ketepatan (device_id)",
            format_rate(precision) if precision is not None else "-",
            help=(
                "Dari pasangan yang digabung, berapa persen device_id-nya sama. "
                "Ini BATAS ATAS: satu orang bisa memakai banyak perangkat, jadi "
                "angka ini sengaja menampilkan yang terburuk."
            ),
        )
        q2.metric(
            "Salah gabung (device_id)",
            f"{linkage.get('false_merges', 0):,}",
            help="Pasangan digabung tapi device_id-nya berbeda.",
        )
        q3.metric(
            "Customer tercemar",
            f"{mixed:,}" if mixed is not None else "-",
            help="Jumlah customer yang di dalamnya ada lebih dari satu device_id.",
        )
        st.caption(
            "⚠ **Cara membaca angka ini.** Penghitungan memakai `device_id`, yang "
            "pada dataset ini identik dengan `customer_id`. Jadi angka ini adalah "
            "**batas atas** kesalahan, bukan ukuran akurasi di dunia nyata. "
            "Angka yang lebih dipercaya ada di bawah, dihitung dari keputusan "
            "manusia."
        )

        # ---- versi yang dihitung dari keputusan manusia
        try:
            from src.threshold_eval import evaluate_at
            from src.labels import load_labels

            labels, src_label = load_labels("gold")
            preds_g = pd.read_parquet(
                OUTPUT_DIR / "splink_predictions.parquet",
                columns=["record_id_l", "record_id_r", "match_probability"],
            )
            if labels is not None and not labels.empty:
                merged = preds_g.merge(
                    labels[["record_id_l", "record_id_r", "is_positive"]],
                    on=["record_id_l", "record_id_r"], how="inner",
                )
                merged["label"] = merged["is_positive"].astype(int)
                if merged["label"].nunique() > 1:
                    g = evaluate_at(merged, "label", "match_probability", 0.9)
                    g1, g2, g3 = st.columns(3)
                    g1.metric(
                        "Ketepatan (keputusan manusia)",
                        format_rate(g["precision"]),
                        help="Dari yang sistem bilang sama, berapa persen yang "
                             "manusia juga setujui. Ini angka yang paling dipercaya.",
                    )
                    g2.metric(
                        "Kelengkapan (keputusan manusia)",
                        format_rate(g["recall"]),
                        help="Dari yang manusia bilang sama, berapa persen yang "
                             "berhasil ditangkap sistem.",
                    )
                    g3.metric(
                        "Cakupan pengukuran",
                        f"{len(merged):,} dari {int(linkage.get('match_edges', 0)):,}",
                        help="Berapa pasangan yang benar-benar punya label manusia. "
                             "Sisanya belum pernah dinilai, jadi angka di kiri hanya "
                             "mewakili sebagian.",
                    )
                    st.caption(
                        f"⚠ **Cakupan terbatas.** Angka di atas dihitung dari "
                        f"{len(merged):,} pasangan yang sudah pernah diputuskan "
                        f"manusia (sumber: `{src_label}`). Sisa pasangan belum "
                        "pernah dinilai, jadi angka ini belum mewakili seluruh "
                        "data — dan memang tidak boleh dikutip seolah-olah iya."
                    )
        except Exception as exc:
            st.caption(f"Pengukuran dari keputusan manusia belum tersedia: {exc}")

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

# ---- kelompok
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
run_summary_path = OUTPUT_DIR / "run_summary.json"
history: list[dict] = []
if history_path.exists():
    history = [
        json.loads(line)
        for line in history_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
if not history and run_summary_path.exists():
    summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
    history = [{
        "timestamp": eval_path.stat().st_mtime if eval_path.exists() else 0,
        "batch": f"full:{summary.get('model_version', 'unknown')}",
        "new_records": entity.get("records", 0) if eval_path.exists() else 0,
        "new_entities": entity.get("entities", 0) if eval_path.exists() else 0,
    }]
    if isinstance(history[0]["timestamp"], (int, float)):
        from datetime import datetime as _dt
        history[0]["timestamp"] = _dt.fromtimestamp(history[0]["timestamp"]).isoformat(timespec="seconds")
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
