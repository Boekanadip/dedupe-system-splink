"""Dasbor: penyegaran manual"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

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
from src.config import (
    ENTITY_MAP_PATH,
    PROCESSED_DATA_PATH,
    SMOKE_SAMPLE_SIZE,
    predictions_path,
    read_meta,
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
report = json.loads(eval_path.read_text(encoding="utf-8")) if eval_path.exists() else {}
entity_meta = read_meta(ENTITY_MAP_PATH)
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
    preds = pd.read_parquet(pred_path, columns=["decision", "match_probability"])

decision_counts = (
    preds["decision"].value_counts()
    if not preds.empty and "decision" in preds
    else pd.Series(dtype="int64")
)
candidate_pairs = int(decision_counts.sum())
review_pairs = int(decision_counts.get("REVIEW", 0))
predictions_available = pred_path.exists() and "decision" in preds
entity_snapshot = pd.DataFrame()
if ENTITY_MAP_PATH.exists():
    entity_snapshot = pd.read_parquet(ENTITY_MAP_PATH, columns=["record_id", "entity_id"])
    if not full_scope:
        sample_ids = set(
            pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id"])
            .head(SMOKE_SAMPLE_SIZE)["record_id"]
        )
        entity_snapshot = entity_snapshot[entity_snapshot["record_id"].isin(sample_ids)]
    live_records = len(entity_snapshot)
    live_entities = int(entity_snapshot["entity_id"].nunique())
else:
    live_records = None
    live_entities = None
report_is_stale = bool(
    eval_path.exists()
    and pred_path.exists()
    and pred_path.stat().st_mtime > eval_path.stat().st_mtime
)

if eval_path.exists():
    entity = report.get("entity", {})
    decision = report.get("decision", {})
    linkage = report.get("linkage", {})
    if predictions_available:
        auto_match_rate = decision_counts.get("MATCH", 0) / candidate_pairs if candidate_pairs else 0
        review_rate = review_pairs / candidate_pairs if candidate_pairs else 0
    else:
        auto_match_rate = decision.get("rates", {}).get("auto_match_rate", 0)
        review_rate = decision.get("rates", {}).get("review_rate", 0)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Customer unik", f"{live_entities if live_entities is not None else entity.get('entities', 0):,}",
             help="Jumlah orang yang berhasil dipastikan setelah duplikat digabung.")
    m2.metric("Total record", f"{live_records if live_records is not None else entity.get('records', 0):,}",
             help="Jumlah baris data masuk, sebelum ada yang digabung.")
    m3.metric("Digabung otomatis", format_rate(auto_match_rate),
             help="Berapa persen pasangan yang sistem yakin dan langsung digabung.")
    m4.metric("Pasangan REVIEW", format_rate(review_rate),
             help="Persentase pasangan kandidat, bukan customer unik atau jumlah tugas antrean.")
    if report_is_stale:
        st.warning(
            "Laporan evaluasi kualitas lebih lama daripada prediksi saat ini. "
            "Jumlah dan grafik keputusan di atas memakai prediksi terbaru; metrik "
            "kualitas di bawah disembunyikan sampai evaluasi dijalankan ulang."
        )
    model_version = prediction_meta.get("model_version") or report.get("model_version")
    if model_version:
        st.caption(f"Model yang dipakai: `{model_version}`")

        # ---- versi yang dihitung dari keputusan manusia
        try:
            if report_is_stale:
                raise RuntimeError("artefak evaluasi belum diperbarui setelah prediksi berubah")
            from src.threshold_eval import evaluate_at
            from src.labels import load_labels

            labels, src_label = load_labels("gold")
            preds_g = pd.read_parquet(
                pred_path,
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
                        f" **Cakupan terbatas.** Angka di atas dihitung dari "
                        f"{len(merged):,} pasangan yang sudah pernah diputuskan "
                        f"manusia (sumber: `{src_label}`)."
                    )
        except Exception as exc:
            st.caption(f"Pengukuran dari keputusan manusia belum tersedia: {exc}")

# ---- keputusan
if not preds.empty:
    st.caption(
        f"Scope: **{scope}** · Sumber: `{pred_path.name}`"
        + (
            " · Prediksi diperbarui: "
            + pd.Timestamp(prediction_stat.st_mtime, unit="s", tz="UTC").strftime(
                "%Y-%m-%d %H:%M UTC"
            )
            if prediction_stamp
            else ""
        )
    )
    st.subheader("Hasil keputusan")
    st.caption(
        "Setiap pasangan kandidat mendapat satu keputusan. Angka adalah jumlah "
        "pasangan, bukan jumlah customer; satu record dapat muncul di banyak pasangan."
    )
    counts = (
        preds["decision"]
        .value_counts()
        .reindex(["NON_MATCH", "REVIEW", "MATCH"], fill_value=0)
    )
    total = int(counts.sum())
    status_labels = [DECISION_LABEL.get(str(k), str(k)) for k in counts.index]
    pct_labels = [
        f"{value:,} ({value / total:.1%})" if total else "0 (0.0%)"
        for value in counts.values
    ]
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
    st.plotly_chart(
        fig, width="stretch", key=f"decision-chart-{prediction_stamp}"
    )

    st.subheader("Sebaran peluang")
    st.caption(
        "Distribusi peluang kandidat dengan rentang yang mengikuti batas NON_MATCH, "
        "REVIEW, dan MATCH. Ini menunjukkan sebaran skor, bukan ukuran akurasi."
    )
    probs = pd.to_numeric(preds["match_probability"], errors="coerce").dropna().clip(0, 1)
    thresholds = report.get("decision", {}).get("thresholds", {})
    review_threshold = float(
        prediction_meta.get("review_threshold", thresholds.get("review", 0.35))
    )
    match_threshold = float(
        prediction_meta.get("match_threshold", thresholds.get("match", 0.84))
    )
    bins = sorted(
        {
            0.0, 1.0, review_threshold, match_threshold,
            1e-12, 1e-10, 1e-8, 1e-6, 1e-4, 0.01, 0.1, 0.5, 0.75, 0.95, 0.99,
        }
    )
    bins = [edge for edge in bins if 0 <= edge <= 1]
    hist = pd.cut(probs, bins=bins, include_lowest=True)
    bin_counts = hist.value_counts().sort_index()
    labels = [
        f"{interval.left:.2g}–{interval.right:.2g}"
        for interval in bin_counts.index
    ]
    bin_pcts = [
        f"{count:,} ({count / len(probs):.1%})" if len(probs) else "0 (0.0%)"
        for count in bin_counts.values
    ]
    fig2 = go.Figure(
        go.Bar(
            x=labels,
            y=bin_counts.values,
            text=bin_pcts,
            textposition="outside",
            marker_color="#6ee7a0",
            textfont=dict(color="#e5e7eb"),
        )
    )
    fig2.update_layout(
        title=dict(text="Sebaran peluang<br><sup>Sumbu Y: jumlah pasangan</sup>", x=0),
        xaxis_title="Rentang peluang",
        yaxis_title="Jumlah pasangan kandidat",
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#e5e7eb"),
        showlegend=False,
        bargap=0.12,
    )
    fig2.update_xaxes(tickangle=-45, type="category")
    st.plotly_chart(
        fig2, width="stretch", key=f"probability-chart-{prediction_stamp}"
    )

# ---- kelompok
cluster_path = OUTPUT_DIR / "cluster_summary.csv"
if cluster_path.exists() or ENTITY_MAP_PATH.exists():
    st.subheader("Hasil pengelompokan")
    c1, c2, c3 = st.columns(3)
    c1.metric("Customer unik", f"{live_entities if live_entities is not None else 0:,}")
    records_merged = (
        live_records - live_entities
        if live_records is not None and live_entities is not None
        else 0
    )
    c2.metric("Record yang digabung", f"{records_merged:,}",
             help="Record yang berhasil dipastikan sebagai duplikat.")
    c3.metric(
        "Pasangan REVIEW (model)",
        f"{review_pairs:,}",
        help=(
            "Jumlah semua pasangan kandidat dalam rentang REVIEW, bukan jumlah "
            "orang atau jumlah tugas di antrean. Satu record bisa muncul di banyak pasangan."
        ),
    )

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
        history_stamp = (
            f"{history_path.stat().st_mtime_ns}-{history_path.stat().st_size}"
            if history_path.exists()
            else "fallback"
        )
        st.plotly_chart(
            fig3, width="stretch", key=f"batch-history-{history_stamp}"
        )
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
    pending = int(status.get("pending", 0))
    k1.metric("Pasangan dalam antrean", f"{total_q:,}")
    k2.metric("Sudah diperiksa", f"{reviewed:,}")
    k3.metric("Menunggu diperiksa", f"{pending:,}")
    st.caption(
        f"Antrean berisi {total_q:,} pasangan (sampel/seleksi untuk pemeriksaan), "
        f"berbeda dari seluruh pasangan REVIEW yang dihitung model. Tingkat selesai: "
        f"{done_rate:.1%}. Pekerjakan antrean di halaman **Pemeriksaan**."
    )
