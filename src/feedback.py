"""Simpan hasil peninjauan manusia sebagai data umpan balik yang dapat digunakan kembali
(PRD FR-09, FR-15, bagian 12 DESIGN).

Bagian 12 DESIGN menetapkan kolom yang harus dibawa:

    pair_id, record_id_l, record_id_r, score, decision,
    human_label, reviewer, timestamp, model_version

Tiga kolom tersebut saat ini belum dicatat di mana pun. `timestamp` dan
`model_version` memungkinkan label dilacak: tanpanya, keputusan peninjau tidak
dapat ditautkan ke model yang menghasilkan skor. Bagian 15 MASTER_CONTEXT
mencantumkan "akumulasi besar kasus yang telah ditinjau" sebagai pemicu
pelatihan ulang, sehingga model asal setiap kasus harus diketahui.

Hanya menambahkan, sesuai rancangan. data/labels/feedback.csv adalah tempat
penyimpanan umpan balik yang terus bertambah, sebagaimana dijelaskan pada bagian
14 MASTER_CONTEXT. Promosi dari antrean bersifat idempoten berdasarkan
(record_id_l, record_id_r, model_version): mempromosikan ulang antrean yang sama
setelah menambahkan catatan peninjau akan memperbarui baris tersebut, bukan
menduplikasinya, agar penilaian peninjau tidak dihitung dua kali.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd

from . import model_lifecycle
from .config import LABELS_DIR, PREDICTIONS_FULL_PATH, PREDICTIONS_SAMPLE_PATH
from .labels import (
    FP_SAMPLE_PATH,
    GOLD_PATH,
    QUEUE_PATH,
    _read_review,
    normalise_label,
)

FEEDBACK_PATH = LABELS_DIR / "feedback.csv"

REVIEW_SOURCES = (QUEUE_PATH, FP_SAMPLE_PATH)

FEEDBACK_COLUMNS = [
    "pair_id",
    "record_id_l",
    "record_id_r",
    "score",
    "decision",
    "human_label",
    "reviewer",
    "timestamp",
    "model_version",
    "stratum",
]


def _pair_id(left: str, right: str) -> str:
    a, b = sorted((str(left), str(right)))
    return f"{a}__{b}"


def _model_version() -> str | None:
    """Model yang menghasilkan skor yang sedang ditinjau."""
    latest = model_lifecycle.latest()
    return latest.name if latest else None


def _decisions_for() -> pd.DataFrame:
    """Pasangan record_id -> (skor, keputusan) dari berkas prediksi yang tersedia."""
    empty = pd.DataFrame(columns=["pair_id", "match_probability", "decision"])
    for path in (PREDICTIONS_FULL_PATH, PREDICTIONS_SAMPLE_PATH):
        if not path.exists():
            continue
        available = set(pd.read_parquet(path).columns)
        wanted = [
            c
            for c in ("record_id_l", "record_id_r", "match_probability", "decision")
            if c in available
        ]
        preds = pd.read_parquet(path, columns=wanted)
        if "decision" not in preds.columns:
            preds["decision"] = None
        preds["pair_id"] = [
            _pair_id(a, b) for a, b in zip(preds.record_id_l, preds.record_id_r)
        ]
        return preds[["pair_id", "match_probability", "decision"]]
    return empty


def collect() -> pd.DataFrame:
    """Baca semua sumber peninjauan dan hasilkan baris umpan balik dari masing-masing sumber.

    gold_labels.csv adalah sumber data, bukan sekadar keluaran: berkas ini
    menyimpan hasil tinjauan secara permanen setelah antrean asalnya dibuat ulang.
    Tanpanya, umpan balik akan hilang setiap kali pipeline membangun ulang antrean.
    """
    sources = [*REVIEW_SOURCES, GOLD_PATH]
    reviewed = []
    for path in sources:
        if not path.exists():
            continue
        frame = _read_review(path)
        if "label" not in frame.columns:
            continue
        frame = frame.copy()
        # Label acuan sudah memakai istilah baku, sedangkan antrean menyimpan nilai mentah.
        frame["human_label"] = frame["label"].map(normalise_label)
        frame = frame[frame["human_label"].notna()]
        if frame.empty:
            continue
        frame["source"] = path.name
        reviewed.append(frame)

    if not reviewed:
        return pd.DataFrame(columns=FEEDBACK_COLUMNS)

    labels = pd.concat(reviewed, ignore_index=True)
    labels = labels.drop_duplicates(subset=["record_id_l", "record_id_r"], keep="last")
    a = labels["record_id_l"].astype(str)
    b = labels["record_id_r"].astype(str)
    labels["record_id_l"] = [min(x, y) for x, y in zip(a, b)]
    labels["record_id_r"] = [max(x, y) for x, y in zip(a, b)]
    labels["pair_id"] = [
        _pair_id(x, y) for x, y in zip(labels.record_id_l, labels.record_id_r)
    ]

    # Skor dan keputusan selalu diambil dari parquet prediksi, bukan dari berkas
    # peninjauan: Excel mengubah angka menjadi format desimal berkoma saat berkas
    # dibuka dan disimpan, sehingga salinannya tidak dapat dipercaya. Hapus dulu
    # kolom match_probability dari berkas peninjauan agar penggabungan tidak
    # menghasilkan kolom duplikat dengan akhiran.
    labels = labels.drop(columns=["match_probability"], errors="ignore")
    scores = _decisions_for()
    labels = labels.merge(scores, on="pair_id", how="left")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    labels["score"] = labels["match_probability"]
    labels["timestamp"] = now
    if "reviewer" not in labels.columns:
        labels["reviewer"] = None
    labels["model_version"] = _model_version()

    return labels[FEEDBACK_COLUMNS].sort_values("pair_id").reset_index(drop=True)


def merge(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    """Tambahkan umpan balik baru; perbarui baris yang sudah ada untuk model yang sama.

    Kuncinya adalah (pair_id, model_version): pasangan yang sama saat ditinjau
    menggunakan v1 dan v2 merupakan dua pengamatan berbeda terhadap dua model.
    """
    if existing.empty:
        return incoming
    if incoming.empty:
        return existing

    key = ["pair_id", "model_version"]
    # Penilaian terbaru dari peninjau menggantikan penilaian sebelumnya; karena
    # itu, letakkan `incoming` di urutan terakhir.
    merged = pd.concat([existing, incoming], ignore_index=True)
    merged = merged.drop_duplicates(subset=key, keep="last")
    return merged.sort_values(key).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persist reviewed pairs as reusable feedback (DESIGN section 12)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching feedback.csv.",
    )
    args = parser.parse_args()

    incoming = collect()
    if incoming.empty:
        print("No reviewed pairs found in the review queue or FP sample.")
        print("Fill a 'label' column first: python -m src.review_sample --band match")
        return

    existing = (
        pd.read_csv(FEEDBACK_PATH) if FEEDBACK_PATH.exists() else pd.DataFrame()
    )
    updated = merge(existing, incoming)

    print(f"Collected {len(incoming):,} reviewed pair(s) from the queue sources.")
    print(f"Feedback rows: {len(existing):,} -> {len(updated):,}")
    print(f"Label breakdown: {incoming['human_label'].value_counts().to_dict()}")
    version = _model_version()
    print(f"Attributed to model version: {version or 'UNKNOWN (no saved model)'}")

    if args.dry_run:
        print("\n--dry-run: feedback.csv not written.")
        return

    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    updated.to_csv(FEEDBACK_PATH, index=False)
    print(f"Saved: {FEEDBACK_PATH}")
    print(
        "This file is the accumulation MASTER_CONTEXT section 15 uses as a "
        "retraining trigger. It is append-only; do not hand-edit it."
    )


if __name__ == "__main__":
    main()
