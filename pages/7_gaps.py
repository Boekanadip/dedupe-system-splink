"""Gap coverage page: what the pipeline never surfaced, with actions.

Two populations are invisible everywhere else:
  1. Singleton entities — a record that never matched anything. Either it is a
     genuinely unique customer, or a duplicate nobody caught. 94% of entities
     are singletons, so this is the biggest unanswered question in the output.
  2. REVIEW pairs that were never queued — the review queue is a SAMPLE of the
     review band (hundreds of ~46,000). Everything outside the sample has no
     path to a human decision.

Both are actionable here: pull a record's candidates, or promote uncovered
REVIEW pairs into the review queue.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ENTITY_MAP_PATH, LABELS_DIR, MASTER_PATH, PROCESSED_DATA_PATH, predictions_path
from src.labels import REVIEW_FIELDS, QUEUE_PATH, agree_fields, attach_evidence, carry_over_reviewed

st.set_page_config(page_title="Gaps", page_icon="🕳️", layout="wide")
st.title("Gaps & tindak lanjut")
st.caption(
    "Record yang tidak pernah tergabung (singleton) dan pasangan REVIEW yang "
    "tidak pernah masuk antrean — keduanya tidak terlihat di halaman lain."
)

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
review["queued"] = [
    (str(l), str(r)) in queued
    for l, r in zip(review["record_id_l"], review["record_id_r"])
]
uncovered = review[~review["queued"]]

# ---- ringkasan
st.subheader("Ringkasan")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Singleton entity", f"{len(singletons):,}",
          help="Record yang tidak pernah cocok dengan siapa pun — unik, atau duplikat yang lolos.")
c2.metric("REVIEW belum di antrean", f"{len(uncovered):,}")
c3.metric("REVIEW sudah di antrean", f"{int(review['queued'].sum()):,}")
conflicted = 0
if MASTER_PATH.exists():
    conflicted = int(
        pd.read_parquet(MASTER_PATH, columns=["conflicted_fields"])["conflicted_fields"]
        .map(len).gt(0).sum()
    )
c4.metric("Entity bermasalah", conflicted, help="Entity dengan field yang isinya beda antar record anggota.")

tab_s, tab_r = st.tabs(["Singleton", "REVIEW belum di antrean"])

# ================= tab singleton =================
with tab_s:
    st.caption(
        f"{len(singletons):,} record sendirian. 94% entity memang singleton, "
        "tapi tiap singleton yang seharusnya duplikat adalah kebocoran recall "
        "yang tidak pernah terlihat."
    )
    single_records = records[records["record_id"].isin(set(singletons))].copy()
    # Singleton that can never be blocked: no email AND no phone = recall ceiling.
    unlinkable = single_records["email"].isna() & single_records["phone_number"].isna()
    show = st.radio("Tampilkan", ["Semua singleton", "Singleton tanpa email & phone (tak terhubung)"], horizontal=True)
    if show.startswith("Singleton tanpa"):
        single_records = single_records[unlinkable]
        st.warning(
            f"{int(unlinkable.sum()):,} record tidak punya email DAN phone — "
            "aturan blocking tidak akan pernah menjadikannya kandidat. "
            "Ini recall ceiling, bukan keputusan model."
        )
    search = st.text_input("Cari nama/email di antara singleton", "")
    view = single_records
    if search:
        s = search.lower()
        view = view[
            view["first_name_std"].astype(str).str.contains(s, na=False)
            | view["last_name_std"].astype(str).str.contains(s, na=False)
            | view["email_std"].astype(str).str.contains(s, na=False)
        ]
    page_size = 50
    n_pages = max(1, (len(view) + page_size - 1) // page_size)
    page = st.number_input("Halaman singleton", min_value=1, max_value=n_pages, value=1, key="sing_page")
    start = (page - 1) * page_size
    st.dataframe(
        view.iloc[start:start + page_size][
            ["record_id", "customer_id", "first_name_std", "last_name_std",
             "email_std", "phone_std", "dob_std", "city_std"]
        ],
        use_container_width=True, height=350,
    )

    st.subheader("Tindak lanjut: telusuri kandidat satu record")
    st.caption("Pilih record singleton → lihat pasangan kandidatnya → antrekan ke reviewer.")
    pick = st.selectbox("Record", view["record_id"].tolist() if len(view) else [])
    if pick:
        cand = preds[
            (preds["record_id_l"] == pick) | (preds["record_id_r"] == pick)
        ].sort_values("match_probability", ascending=False)
        st.caption(
            f"{len(cand):,} kandidat pernah di-skor untuk record ini. "
            "Skor tertinggi ditampilkan — kalau semuanya jauh di bawah 1e-10, "
            "model memang yakin record ini unik."
        )
        show_cand = cand.head(50).copy()
        other = show_cand.apply(
            lambda r: r["record_id_r"] if r["record_id_l"] == pick else r["record_id_l"], axis=1
        )
        show_cand["kandidat"] = other.values
        st.dataframe(
            show_cand[["kandidat", "match_probability", "decision"]],
            use_container_width=True,
            column_config={"match_probability": st.column_config.NumberColumn("P", format="%.2e")},
        )
        if st.button(f"Antrekan 20 kandidat teratas ({pick})"):
            top = cand.head(20)[["record_id_l", "record_id_r", "match_probability"]]
            n = enqueue(top, "singleton_candidate")
            st.success(f"{n:,} pasangan masuk antrean review." if n else "Sudah semua di antrean.")
            st.rerun()

# ================= tab review tak-antre =================
with tab_r:
    st.caption(
        f"Antrean review berisi {len(queue):,} dari {len(review):,} pasangan REVIEW. "
        "Sisanya tidak punya jalur ke keputusan manusia — di sini bisa diantrekan."
    )
    f1, f2 = st.columns(2)
    top_n = f1.number_input("Jumlah pasangan diantrekan (skor tertinggi)", 50, 5000, 500, step=100)
    if f2.button(f"Antrekan {top_n} pasangan REVIEW tertinggi", type="primary"):
        take = uncovered.nlargest(top_n, "match_probability")[
            ["record_id_l", "record_id_r", "match_probability"]
        ]
        n = enqueue(take, "uncovered_review")
        st.success(f"{n:,} pasangan baru masuk antrean. Sisanya masih {len(uncovered) - n:,}.")
        st.rerun()

    page_size = 50
    n_pages = max(1, (len(uncovered) + page_size - 1) // page_size)
    page = st.number_input("Halaman REVIEW", min_value=1, max_value=n_pages, value=1, key="rev_page")
    start = (page - 1) * page_size
    st.dataframe(
        uncovered.iloc[start:start + page_size][
            ["record_id_l", "record_id_r", "match_probability", "queued"]
        ],
        use_container_width=True,
        column_config={"match_probability": st.column_config.NumberColumn("P", format="%.2e")},
    )
