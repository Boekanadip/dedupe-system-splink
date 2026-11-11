from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import LABELS_DIR, OUTPUT_DIR, PROJECT_ROOT, PROCESSED_DATA_PATH
from src.data_access import read_pairs, read_processed
from src.labels import exclude_gold_pairs, load_labels
from src.review_db import load_queue as load_db_queue, update_decisions
from src.ui import (
    decision_label,
    field_label,
    format_probability,
    how_to_read,
    label_label,
    model_levels,
    page_header,
    probability_band_help,
    probability_verdict,
    render_sidebar,
    review_status_label,
    show_evidence,
    stratum_label,
    verdict_plain,
)

QUEUE_PATH = LABELS_DIR / "review_queue.csv"
PREDS_PATH = OUTPUT_DIR / "splink_predictions.parquet"
EDITABLE = ["label", "reviewer", "reviewer_note"]

SECONDS_PER_PAIR = 30

GRID_COLUMNS: list[tuple[str, str]] = [
    ("record_id_l", "Record A"),
    ("record_id_r", "Record B"),
    ("agree_count", "Field yang cocok"),
    ("first_name_std_l", "Nama depan A"),
    ("first_name_std_r", "Nama depan B"),
    ("last_name_std_l", "Nama belakang A"),
    ("last_name_std_r", "Nama belakang B"),
    ("email_std_l", "Email A"),
    ("email_std_r", "Email B"),
    ("phone_std_l", "Telepon A"),
    ("phone_std_r", "Telepon B"),
    ("dob_std_l", "Tanggal lahir A"),
    ("dob_std_r", "Tanggal lahir B"),
    ("city_std_l", "Kota A"),
    ("city_std_r", "Kota B"),
    ("match_probability", "Peluang"),
    ("stratum", "Asal pasangan"),
    ("label", "Keputusan Anda"),
    ("review_status", "Status"),
    ("reviewer", "Nama Anda"),
    ("reviewer_note", "Catatan"),
]
GRID_TITLES = {raw: title for raw, title in GRID_COLUMNS}

page_header(
    "Pemeriksaan Pasangan",
    "Sistem tidak yakin apakah dua record itu orang yang sama. "
    "Anda yang memutuskan, satu per satu.",
)
render_sidebar("review")

try:
    queue = load_db_queue()
except Exception as exc:
    st.warning(f"Database review belum tersedia; memakai file lokal sementara: {exc}")
    queue = pd.read_csv(QUEUE_PATH) if QUEUE_PATH.exists() else pd.DataFrame()

if queue.empty and not QUEUE_PATH.exists():
    st.info("Belum ada antrean. Jalankan pipeline dari halaman Upload dulu.")
    st.stop()
if queue.empty:
    st.info("Belum ada antrean.")
    st.stop()
for col in EDITABLE:
    queue[col] = queue[col].where(queue[col].notna(), "").astype(str)
hidden_gold_count = 0
gold, _ = load_labels("gold")
if gold is not None:
    visible_queue = exclude_gold_pairs(queue, gold)
    hidden_gold_count = len(queue) - len(visible_queue)
    queue = visible_queue

pending = int((queue["review_status"] == "pending").sum())
reviewed = int((queue["review_status"] != "pending").sum())
n_match = int((queue["label"] == "match").sum())
n_nomatch = int((queue["label"] == "no_match").sum())

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Pasangan aktif", f"{len(queue):,}")
k2.metric("Menunggu", f"{pending:,}", help="Belum ada keputusan dari Anda.")
k3.metric("Sudah diperiksa", f"{reviewed:,}")
k4.metric("Ditetapkan sama", f"{n_match:,}", help="Anda memutuskan ini orang yang sama.")
k5.metric("Ditetapkan beda", f"{n_nomatch:,}", help="Anda memutuskan ini dua orang berbeda.")
if hidden_gold_count:
    st.caption(
        f"{hidden_gold_count:,} pasangan yang sudah tersimpan di daftar utama "
        "disembunyikan dari antrean. Riwayatnya tetap ada di berkas data."
    )
if queue.empty:
    if hidden_gold_count:
        st.success("Semua pasangan antrean sudah tersimpan di daftar utama. Tidak ada yang perlu ditinjau.")
    else:
        st.info("Tidak ada pasangan untuk ditinjau.")
    st.stop()

if pending > 0:
    hours = pending * SECONDS_PER_PAIR / 3600
    if hours >= 1:
        cost = f"± {hours:,.0f} jam kerja".replace(",", ".")
    else:
        cost = f"± {pending * SECONDS_PER_PAIR / 60:.0f} menit".replace(".", ",")
    st.caption(
        f"⏱ Perkiraan waktu memeriksa semua yang menunggu: **{cost}** "
        f"(asumsi {SECONDS_PER_PAIR} detik per pasangan). "
        "Kalau angkanya terlalu besar, saring dulu lewat tab Asal pasangan "
        "atau minta sistem menaikkan batas bawah agar pasangan yang jelas-jelas "
        "bukan duplikat tidak masuk antrean."
    )
if "msg" in st.session_state:
    st.info(st.session_state["msg"])

tab_compare, tab_list = st.tabs(["Bandingkan satu per satu", "Daftar (massal)"])


def apply_labels(pairs: list[tuple[str, str, str, str, str]]) -> int:
    """pairs: (l, r, label, reviewer, note). Simpan ke PostgreSQL, fallback ke CSV."""
    if not pairs:
        return 0
    updates = pd.DataFrame(
        [
            {"record_id_l": l, "record_id_r": r, "label": label,
             "reviewer": reviewer, "reviewer_note": note or ""}
            for l, r, label, reviewer, note in pairs
        ]
    )
    try:
        update_decisions(updates)
    except Exception as exc:
        frame = pd.read_csv(QUEUE_PATH)
        for c in EDITABLE:
            frame[c] = frame[c].where(frame[c].notna(), "").astype(str)
        for rid_l, rid_r, label, reviewer, note in pairs:
            mask = (frame["record_id_l"] == rid_l) & (frame["record_id_r"] == rid_r)
            frame.loc[mask, "label"] = label
            frame.loc[mask, "reviewer"] = reviewer
            if note is not None:
                frame.loc[mask, "reviewer_note"] = note
            frame.loc[mask, "review_status"] = "reviewed" if label else "pending"
        frame.to_csv(QUEUE_PATH, index=False)
        st.warning(f"PostgreSQL gagal; keputusan disimpan lokal sementara: {exc}")
    for rid_l, rid_r, label, reviewer, note in pairs:
        queue_mask = (queue["record_id_l"] == rid_l) & (queue["record_id_r"] == rid_r)
        queue.loc[queue_mask, "label"] = label
        queue.loc[queue_mask, "reviewer"] = reviewer
        if note is not None:
            queue.loc[queue_mask, "reviewer_note"] = note
        queue.loc[queue_mask, "review_status"] = "reviewed" if label else "pending"
    return len(pairs)


with tab_compare:
    st.caption(
        "Buka **Asal** untuk menyaring asal pasangan, **Status** untuk menyaring "
        "yang sudah pernah diputuskan."
    )
    f1, f2 = st.columns(2)
    strata = ["(semua)"] + sorted(queue["stratum"].unique().tolist())
    statuses = ["(semua)"] + sorted(queue["review_status"].unique().tolist())
    stratum_filter = f1.selectbox(
        "Asal pasangan",
        strata,
        format_func=lambda s: "(semua asal)" if s == "(semua)" else stratum_label(s),
        key="cmp_stratum",
    )
    status_filter = f2.selectbox(
        "Status",
        statuses,
        format_func=lambda s: "(semua status)" if s == "(semua)" else review_status_label(s),
        key="cmp_status",
    )

    pool = queue
    if stratum_filter != "(semua)":
        pool = pool[pool["stratum"] == stratum_filter]
    if status_filter != "(semua)":
        pool = pool[pool["review_status"] == status_filter]
    st.caption(f"Menampilkan {len(pool):,} dari {len(queue):,} pasangan.")

    if pool.empty:
        st.info("Tidak ada pasangan untuk pilihan saringan ini.")
    else:
        pair_labels = [
            f"{r.record_id_l} vs {r.record_id_r} · peluang {format_probability(r.match_probability)}"
            for r in pool.itertuples()
        ]

        cursor = int(st.session_state.get("cmp_cursor", 0)) % len(pool)
        idx = st.selectbox(
            "Pilih pasangan", range(len(pool)),
            index=cursor,
            format_func=lambda i: pair_labels[i],
        )
        row = pool.iloc[idx]

        probability = float(row["match_probability"])
        value_fields = (
            "first_name_std", "last_name_std", "email_std", "phone_std",
            "dob_std", "address_std", "city_std", "state_std", "country_std",
        )
        evidence_row = {"record_id_l": row["record_id_l"], "record_id_r": row["record_id_r"]}
        # Antrean dapat berisi pasangan lama yang sudah tidak ada di data aktif.
        # Gunakan evidence yang sudah disimpan di baris antrean terlebih dahulu.
        for field in value_fields:
            for side in ("l", "r"):
                column = f"{field}_{side}"
                if column in row.index and pd.notna(row[column]):
                    evidence_row[column] = row[column]
        if PREDS_PATH.exists():
            try:
                pred_columns = read_pairs(columns=[]).columns.tolist()
                wanted = ["record_id_l", "record_id_r", "decision", "gamma_name", "gamma_contact", "gamma_location"]
                wanted += [f"{f}_{side}" for f in value_fields for side in ("l", "r")]
                wanted = [column for column in wanted if column in pred_columns]
                gdf = read_pairs(columns=wanted) if wanted else pd.DataFrame()
                ghit = gdf[
                    (gdf["record_id_l"].astype(str) == str(row["record_id_l"]))
                    & (gdf["record_id_r"].astype(str) == str(row["record_id_r"]))
                ] if not gdf.empty else pd.DataFrame()
                if not ghit.empty:
                    evidence_row.update(ghit.iloc[0].to_dict())
            except Exception:
                pass

        # Queue lama berisi evidence lengkap; fallback ke sumber standar bila
        # pasangan tidak ada lagi di artifact prediction aktif.
        missing_values = [f"{field}_{side}" not in evidence_row for field in value_fields for side in ("l", "r")]
        if any(missing_values):
            try:
                records = read_processed(columns=["record_id", *value_fields])
                records["record_id"] = records["record_id"].astype(str)
                left = records[records["record_id"] == str(row["record_id_l"])].iloc[0]
                right = records[records["record_id"] == str(row["record_id_r"])].iloc[0]
                for field in value_fields:
                    evidence_row[f"{field}_l"] = left[field]
                    evidence_row[f"{field}_r"] = right[field]
            except (FileNotFoundError, IndexError, KeyError):
                pass

        m1, m2 = st.columns(2)
        m1.metric(
            "Peluang sama",
            format_probability(probability),
            help=probability_band_help(),
        )
        m2.metric("Status model", decision_label(evidence_row.get("decision", "REVIEW")))

        # Tampilkan isi pasangan dari hasil prediksi aktual.
        st.subheader("Data dua record")
        pair_values = []
        for field, label in [
            ("first_name_std", "Nama depan"), ("last_name_std", "Nama belakang"),
            ("email_std", "Email"), ("phone_std", "Telepon"),
            ("dob_std", "Tanggal lahir"), ("address_std", "Alamat"),
            ("city_std", "Kota"), ("state_std", "Provinsi"), ("country_std", "Negara"),
        ]:
            pair_values.append({
                "Informasi": label,
                "Record A": evidence_row.get(f"{field}_l", "-"),
                "Record B": evidence_row.get(f"{field}_r", "-"),
            })
        st.dataframe(pd.DataFrame(pair_values), width="stretch", hide_index=True)

        st.info(probability_verdict(probability))

        st.caption(
            f"**{row['record_id_l']}** dibandingkan dengan **{row['record_id_r']}** · "
            f"asal: {stratum_label(row['stratum'])} · "
            f"keputusan saat ini: {label_label(row['label'])} · "
            f"diperiksa oleh: {row['reviewer'] or 'belum ada'}"
        )

        with st.expander("Kenapa sistem berpikir begitu? (bandingkan tiap field)", expanded=True):
            show_evidence(evidence_row, model_levels())

        st.divider()
        st.write("**Catatan pemeriksaan**")
        note = st.text_input(
            "Alasan keputusan (opsional)",
            key="cmp_note",
            placeholder="misal: nama ganti karena menikah, nomor lama sudah tidak aktif",
            label_visibility="collapsed",
        )
        reviewer = st.text_input(
            "Nama Anda",
            value="reviewer",
            key="cmp_reviewer",
            label_visibility="collapsed",
        )
        st.caption("Klik salah satu tombol di bawah. Pilihan otomatis berpindah ke pasangan berikutnya.")
        b1, b2, b3, b4 = st.columns([1.2, 1.2, 1, 3])
        if b1.button("Orang yang sama", type="primary", key="btn_match"):
            apply_labels([(row["record_id_l"], row["record_id_r"], "match", reviewer, note)])
            st.session_state["msg"] = (
                f"Tersimpan — {row['record_id_l']} vs {row['record_id_r']} → orang yang sama"
            )
            st.session_state["cmp_cursor"] = (int(idx) + 1) % len(pool)
            st.toast("Tersimpan: orang yang sama")
            st.rerun()
        if b2.button("Berbeda orang", key="btn_nomatch"):
            apply_labels([(row["record_id_l"], row["record_id_r"], "no_match", reviewer, note)])
            st.session_state["msg"] = (
                f"Tersimpan — {row['record_id_l']} vs {row['record_id_r']} → berbeda orang"
            )
            st.session_state["cmp_cursor"] = (int(idx) + 1) % len(pool)
            st.toast("Tersimpan: berbeda orang")
            st.rerun()
        if b3.button("Lewati dulu", key="btn_skip"):
            st.session_state["msg"] = "Dilewati tanpa keputusan."
            st.session_state["cmp_cursor"] = (int(idx) + 1) % len(pool)
            st.rerun()
        b4.caption(verdict_plain(evidence_row.get("decision", "REVIEW")))


with tab_list:
    st.caption(
        "Untuk memeriksa banyak pasangan sekaligus. Isi kolom **Keputusan Anda**, "
        "lalu klik **Simpan semua perubahan**."
    )
    filtered = queue.copy()
    if stratum_filter != "(semua)":
        filtered = filtered[filtered["stratum"] == stratum_filter]
    if status_filter != "(semua)":
        filtered = filtered[filtered["review_status"] == status_filter]
    for col in EDITABLE:
        filtered[col] = filtered[col].where(filtered[col].notna(), "").astype(str)

    st.caption(f"Menampilkan {len(filtered):,} dari {len(queue):,} pasangan.")
    shown = [raw for raw, _ in GRID_COLUMNS if raw in filtered.columns]
    grid = filtered[shown].rename(columns=GRID_TITLES)
    grid["Peluang"] = grid["Peluang"].map(format_probability)

    editable = [GRID_TITLES[c] for c in shown if c in EDITABLE]
    edited = st.data_editor(
        grid,
        disabled=[GRID_TITLES[c] for c in shown if c not in EDITABLE],
        width="stretch",
        height=500,
        hide_index=True,
        column_config={
            GRID_TITLES["label"]: st.column_config.SelectboxColumn(
                "Keputusan Anda",
                options=["", "match", "no_match"],
                format_func=lambda v: label_label(v),
                required=False,
            ),
            GRID_TITLES["reviewer"]: st.column_config.TextColumn("Nama Anda"),
            GRID_TITLES["reviewer_note"]: st.column_config.TextColumn("Catatan"),
            GRID_TITLES["match_probability"]: st.column_config.TextColumn("Peluang"),
            GRID_TITLES["review_status"]: st.column_config.TextColumn("Status"),
            GRID_TITLES["stratum"]: st.column_config.TextColumn("Asal pasangan"),
        },
    )

    edited = edited.rename(columns={title: raw for raw, title in GRID_COLUMNS})
    for col in EDITABLE:
        if col in edited.columns:
            edited[col] = edited[col].fillna("").astype(str)

    if st.button("Simpan semua perubahan", type="primary"):
        updates = edited[["record_id_l", "record_id_r", *EDITABLE]].copy()
        try:
            update_decisions(updates)
        except Exception as exc:
            merged = pd.read_csv(QUEUE_PATH) if QUEUE_PATH.exists() else pd.DataFrame()
            for _, r in updates.iterrows():
                mask = (merged["record_id_l"] == r["record_id_l"]) & (
                    merged["record_id_r"] == r["record_id_r"]
                )
                for col in EDITABLE:
                    merged.loc[mask, col] = "" if pd.isna(r[col]) else str(r[col])
                merged.loc[mask, "review_status"] = "reviewed" if r["label"] else "pending"
            merged.to_csv(QUEUE_PATH, index=False)
            st.warning(f"PostgreSQL gagal; keputusan disimpan lokal sementara: {exc}")
        st.session_state["msg"] = f"Tersimpan {len(edited):,} baris dari Daftar."
        st.toast("tersimpan")
        st.rerun()

st.divider()
st.subheader("Simpan keputusan ke daftar utama")
st.caption(
    "Menyalin seluruh keputusan Anda ke `gold_labels.csv`. File ini dipakai untuk "
    "mengukur seberapa tepat sistem, dan bahan pelatihan model berikutnya. "
    "Sistem tidak pernah memakai file ini untuk memutuskan secara diam-diam."
)
if st.button("Simpan ke daftar utama"):
    result = subprocess.run(
        [sys.executable, "-m", "src.labels", "--promote"],
        cwd=PROJECT_ROOT, text=True, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    log = (result.stdout or "")[-3000:] + (
        "\n" + (result.stderr or "")[-1000:] if result.stderr else ""
    )
    st.session_state["msg"] = "Berhasil disimpan ke daftar utama." if result.returncode == 0 else "Gagal menyimpan — lihat log."
    st.toast(st.session_state["msg"])
    with st.expander("Log penyimpanan", expanded=result.returncode != 0):
        st.code(log)
    st.rerun()

if st.session_state.get("msg", "").startswith("Berhasil disimpan"):
    st.divider()
    st.subheader("Habis ini ke mana?")

    if st.button("Buka Pengaturan Sistem untuk melatih ulang"):
        st.switch_page(st.session_state["registered_pages"]["retrain"])
