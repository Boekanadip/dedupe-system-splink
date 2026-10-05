"""Halaman celah: data yang tidak pernah muncul di halaman lain.

Dua kelompok yang biasanya luput dari pandangan:
  1. Record sendirian — record yang tidak pernah cocok dengan siapa pun. Bisa
     memang customer unik, bisa juga duplikat yang tidak ketahuan. 94% entitas
     ada di kelompok ini, jadi ini pertanyaan terbesar di hasil akhir.
  2. Pasangan yang perlu diperiksa tapi belum masuk antrean — antrean hanya
     sampel, jadi sisanya tidak punya jalur ke keputusan manusia.

Keduanya bisa ditindak di sini: tarik kandidat satu record, atau masukkan
pasangan yang belum masuk antrean.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ENTITY_MAP_PATH, LABELS_DIR, MASTER_PATH, PROCESSED_DATA_PATH, predictions_path
from src.labels import REVIEW_FIELDS, QUEUE_PATH, agree_fields, attach_evidence, carry_over_reviewed
from src.ui import (
    decision_label,
    field_label,
    format_probability,
    how_to_read,
    monitoring_sidebar,
    page_guide,
    page_header,
    paginate,
    probability_verdict,
)

st.set_page_config(page_title="Celah - Entity Resolution", page_icon="🕳️", layout="wide")
page_header(
    "Celah yang Terlewat",
    "Dua hal yang tidak muncul di halaman lain: record yang tidak pernah tergabung, "
    "dan pasangan yang perlu diperiksa tapi belum masuk antrean.",
)
monitoring_sidebar()
page_guide(__file__)
how_to_read()

for _p in (ENTITY_MAP_PATH, PROCESSED_DATA_PATH, predictions_path(full=True)):
    if not _p.exists():
        st.info(f"Belum ada `{_p.name}`. Jalankan pipeline dari halaman Upload dulu.")
        st.stop()

QUEUE_COLUMNS = [
    "record_id_l", "record_id_r", "stratum",
    "agree_email", "agree_phone", "agree_dob", "agree_name", "agree_city",
    "match_probability",
    *[f"{f}_{side}" for side in ("l", "r") for f in REVIEW_FIELDS],
    "label", "review_status", "reviewer", "reviewer_note",
]


def load_queue() -> pd.DataFrame:
    if QUEUE_PATH.exists():
        queue = pd.read_csv(QUEUE_PATH)
        for col in ("stratum", "label", "review_status", "reviewer", "reviewer_note"):
            if col not in queue.columns:
                queue[col] = None
        return queue
    return pd.DataFrame(columns=QUEUE_COLUMNS)


def enqueue(pairs: pd.DataFrame, stratum: str) -> int:
    """Append pairs to the review queue with full side-by-side evidence."""
    records = pd.read_parquet(PROCESSED_DATA_PATH)
    new = pairs[["record_id_l", "record_id_r", "match_probability"]].copy()
    new = agree_fields(records, new)
    new = new.merge(
        pairs[["record_id_l", "record_id_r", "match_probability"]],
        on=["record_id_l", "record_id_r"], how="left",
    )
    new = attach_evidence(records, new)
    new["stratum"] = stratum
    new["label"] = None
    new["review_status"] = "pending"
    new["reviewer"] = None
    new["reviewer_note"] = None
    for col in QUEUE_COLUMNS:
        if col not in new.columns:
            new[col] = None
    new = new[QUEUE_COLUMNS]
    queue = load_queue()
    existing = set(zip(queue["record_id_l"].astype(str), queue["record_id_r"].astype(str)))
    new = new[~new.apply(lambda r: (str(r["record_id_l"]), str(r["record_id_r"])) in existing, axis=1)]
    if new.empty:
        return 0
    combined = pd.concat([queue, new], ignore_index=True)
    combined = carry_over_reviewed(combined)
    combined.to_csv(QUEUE_PATH, index=False)
    return len(new)


entity_map = pd.read_parquet(ENTITY_MAP_PATH)
records = pd.read_parquet(PROCESSED_DATA_PATH)
preds = pd.read_parquet(
    predictions_path(full=True),
    columns=["record_id_l", "record_id_r", "match_probability", "decision"],
)
queue = load_queue()
queued = set(zip(queue["record_id_l"].astype(str), queue["record_id_r"].astype(str)))

sizes = entity_map.groupby("entity_id")["record_id"].transform("size")
singletons = entity_map[sizes == 1]["record_id"]
review = preds[preds["decision"] == "REVIEW"].copy()
review["sudah_di_antrean"] = [
    (str(l), str(r)) in queued
    for l, r in zip(review["record_id_l"], review["record_id_r"])
]
uncovered = review[~review["sudah_di_antrean"]]

st.subheader("Ringkasan")
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Record sendirian",
    f"{len(singletons):,}",
    help="Record yang tidak pernah cocok dengan siapa pun. Bisa customer unik, "
         "bisa duplikat yang tidak ketahuan.",
)
c2.metric(
    "Perlu diperiksa, belum di antrean",
    f"{len(uncovered):,}",
    help="Pasangan yang perlu dilihat manusia, tapi belum masuk antrean kerja.",
)
c3.metric("Sudah di antrean", f"{int(review['sudah_di_antrean'].sum()):,}")
conflicted = 0
if MASTER_PATH.exists():
    conflicted = int(
        pd.read_parquet(MASTER_PATH, columns=["conflicted_fields"])["conflicted_fields"]
        .map(len).gt(0).sum()
    )
c4.metric(
    "Entitas dengan data berbeda",
    conflicted,
    help="Satu entitas tapi isinya tidak sama antar record — perlu dipilih mana yang benar.",
)

tab_s, tab_r = st.tabs(["Record sendirian", "Perlu diperiksa, belum di antrean"])

# ================= record sendirian =================
with tab_s:
    st.caption(
        f"{len(singletons):,} record belum pernah bergabung dengan siapa pun. "
        "Sebagian besar memang customer unik. Tapi kalau ternyata ada yang "
        "seharusnya bergabung, itu berarti sistem melewatkannya — dan itu "
        "tidak akan terlihat di halaman mana pun."
    )
    single_records = records[records["record_id"].isin(set(singletons))].copy()
    # Record tanpa email DAN tanpa phone tidak akan pernah masuk kandidat:
    # tidak ada kolom yang bisa dibandingkan. Ini batas kemampuan, bukan
    # keputusan model.
    unlinkable = single_records["email"].isna() & single_records["phone_number"].isna()
    show = st.radio(
        "Tampilkan",
        ["Semua record sendirian", "Hanya yang tidak punya email & telepon"],
        horizontal=True,
    )
    if show.startswith("Hanya"):
        single_records = single_records[unlinkable]
        st.warning(
            f"{int(unlinkable.sum()):,} record tidak punya email maupun telepon. "
            "Tanpa salah satu dari keduanya, sistem tidak akan pernah "
            "menjadi kandidat — makanya tidak ada yang bisa dicocokkan. "
            "Ini batas data, bukan penilaian model."
        )
    search = st.text_input("Cari nama atau email", "")
    view = single_records
    if search:
        s = search.lower()
        view = view[
            view["first_name_std"].astype(str).str.contains(s, na=False)
            | view["last_name_std"].astype(str).str.contains(s, na=False)
            | view["email_std"].astype(str).str.contains(s, na=False)
        ]
    page_df, _ = paginate(view, page_size=50, key="sing_page")
    shown = page_df[[
        "record_id", "customer_id", "first_name_std", "last_name_std",
        "email_std", "phone_std", "dob_std", "city_std",
    ]].copy()
    shown.columns = [
        "Kode record", "Kode dari sistem asal", "Nama depan", "Nama belakang",
        "Email", "Telepon", "Tanggal lahir", "Kota",
    ]
    st.dataframe(shown, width="stretch", height=350, hide_index=True)

    st.subheader("Telusuri kandidat satu record")
    st.caption(
        "Pilih satu record di bawah, lalu lihat siapa saja yang pernah "
        "dipertimbangkan sistem untuknya."
    )
    pick = st.selectbox("Pilih record", view["record_id"].tolist() if len(view) else [])
    if pick:
        cand = preds[
            (preds["record_id_l"] == pick) | (preds["record_id_r"] == pick)
        ].sort_values("match_probability", ascending=False)
        st.caption(
            f"{len(cand):,} record lain pernah dibandingkan dengan `{pick}`. "
            "Yang paling mirip ditampilkan lebih dulu."
        )
        show_cand = cand.head(50).copy()
        show_cand["kandidat"] = show_cand.apply(
            lambda r: r["record_id_r"] if r["record_id_l"] == pick else r["record_id_l"], axis=1
        )
        top_table = show_cand[["kandidat", "match_probability", "decision"]].copy()
        top_table["Peluang sama"] = top_table["match_probability"].map(format_probability)
        top_table["Kandidat"] = top_table["kandidat"]
        top_table["Status model"] = top_table["decision"].map(decision_label)
        st.dataframe(
            top_table[["Kandidat", "Peluang sama", "Status model"]],
            width="stretch",
            hide_index=True,
        )
        st.caption(probability_verdict(float(show_cand["match_probability"].iloc[0])))
        if st.button(f"Masukkan 20 kandidat teratas ({pick}) ke antrean"):
            top = cand.head(20)[["record_id_l", "record_id_r", "match_probability"]]
            n = enqueue(top, "singleton_candidate")
            st.success(f"{n:,} pasangan masuk antrean pemeriksaan." if n else "Semua sudah ada di antrean.")
            st.rerun()

# ================= perlu diperiksa tapi belum di antrean =================
with tab_r:
    st.caption(
        f"Antrean kerja berisi {len(queue):,} dari {len(review):,} pasangan yang "
        "perlu diperiksa. Sisanya belum pernah dilihat manusia sama sekali. "
        "Masukkan yang skornya tertinggi supaya yang paling mungkin duplicate "
        "pertama dicek."
    )
    f1, f2 = st.columns(2)
    top_n = f1.number_input(
        "Berapa pasangan yang mau dimasukkan?", min_value=50, max_value=5000, value=500, step=100,
        help="Pasangan dengan peluang paling tinggi akan lebih dulu diantre.",
    )
    if f2.button(f"Masukkan {top_n} pasangan tertinggi", type="primary"):
        take = uncovered.nlargest(top_n, "match_probability")[
            ["record_id_l", "record_id_r", "match_probability"]
        ]
        n = enqueue(take, "uncovered_review")
        st.success(f"{n:,} pasangan baru masuk antrean. Sisanya masih {len(uncovered) - n:,}.")
        st.rerun()

    page_df, _ = paginate(uncovered, page_size=50, key="rev_page")
    table = page_df[["record_id_l", "record_id_r", "match_probability"]].copy()
    table["Record A"] = table["record_id_l"]
    table["Record B"] = table["record_id_r"]
    table["Peluang sama"] = table["match_probability"].map(format_probability)
    st.dataframe(
        table[["Record A", "Record B", "Peluang sama"]],
        width="stretch",
        hide_index=True,
    )
