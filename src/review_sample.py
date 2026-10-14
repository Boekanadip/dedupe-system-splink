"""Ambil sampel acak pasangan kandidat untuk ditinjau manusia.

TIGA SASARAN SAMPEL (--band)
  review     kelompok REVIEW: pasangan yang secara eksplisit tidak diputuskan
             oleh model. Inilah antrean peninjauan manusia dari kebijakan tiga arah.
  non_match  pasangan yang ditolak model. Belum ada pemeriksaan untuk kelompok
             ini, sehingga sampelnya digunakan untuk memperkirakan pasangan
             cocok yang terlewat (false negative).
  match      pasangan yang dinyatakan MATCH oleh model. Dataset ini memiliki
             device_id untuk kelompok tersebut, tetapi dataset mendatang belum
             tentu memilikinya, sehingga alur manual harus dapat berjalan sendiri.

ALASAN PENGAMBILAN SAMPEL BERDASARKAN KELOMPOK
Pengambilan sampel merata dari 293.883 pasangan hanya menghasilkan sekitar 1,9
pasangan cocok dari 200 — kelompok match hanya 0,6% dari populasi. Pemisahan
berdasarkan keputusan membuat setiap estimasi dapat diperoleh dengan jumlah
sampel yang wajar.

Berkas ditulis dengan `label` kosong. Mengisinya berarti melakukan peninjauan;
label tersebut kemudian dipromosikan dengan python -m src.labels --promote.
"""

from __future__ import annotations

import argparse

import pandas as pd

from .config import (
    LABELS_DIR,
    MATCH_THRESHOLD,
    PROCESSED_DATA_PATH,
    RANDOM_SEED,
    REVIEW_THRESHOLD,
    predictions_path,
    active_path,
)
from .labels import REVIEW_FIELDS

SAMPLE_PATH = LABELS_DIR / "review_queue.csv"

STRATUM_COLUMNS = [
    "agree_email",
    "agree_phone",
    "agree_dob",
    "agree_name",
    "agree_city",
]

BANDS = ("review", "non_match", "match")


def build_sample(full: bool, n: int, seed: int, band: str = "review") -> pd.DataFrame:
    preds_path = active_path(predictions_path(full=full))
    if not preds_path.exists():
        raise FileNotFoundError(
            f"{preds_path.name} not found. Run: python -m src.splink_model"
            + (" --full" if full else "")
        )
    preds = pd.read_parquet(preds_path)
    if "decision" in preds.columns:
        label = {"review": "REVIEW", "non_match": "NON_MATCH", "match": "MATCH"}[band]
        selected = preds[preds["decision"] == label][
            ["record_id_l", "record_id_r", "match_probability"]
        ]
    else:
        # Artefak lama tidak memiliki kolom keputusan, jadi tentukan kategorinya
        # dari nilai ambang.
        if band == "match":
            selected = preds[preds["match_probability"] >= MATCH_THRESHOLD]
        elif band == "non_match":
            selected = preds[preds["match_probability"] < REVIEW_THRESHOLD]
        else:
            selected = preds[
                (preds["match_probability"] >= REVIEW_THRESHOLD)
                & (preds["match_probability"] < MATCH_THRESHOLD)
            ]
        selected = selected[["record_id_l", "record_id_r", "match_probability"]]
        print(f"NOTE: no decision column; band '{band}' derived from thresholds.")

    if selected.empty:
        raise SystemExit(
            f"No candidate pairs in band '{band}'. The band is empty by measurement, "
            "not by error — see outputs/stress_test.json for why."
        )

    records = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    left = records[["record_id", *REVIEW_FIELDS]].rename(
        columns={**{"record_id": "record_id_l"}, **{c: f"{c}_l" for c in REVIEW_FIELDS}}
    )
    right = records[["record_id", *REVIEW_FIELDS]].rename(
        columns={**{"record_id": "record_id_r"}, **{c: f"{c}_r" for c in REVIEW_FIELDS}}
    )

    sample = selected.sample(n=min(n, len(selected)), random_state=seed).reset_index(drop=True)
    sample = sample.merge(left, on="record_id_l").merge(right, on="record_id_r")

    # Kolom yang cocok menentukan apakah peninjau dapat menilai pasangan ini.
    for flag, field in (
        ("agree_email", "email_std"),
        ("agree_phone", "phone_std"),
        ("agree_dob", "dob_std"),
        ("agree_city", "city_std"),
    ):
        sample[flag] = sample[f"{field}_l"].eq(sample[f"{field}_r"])
    sample["agree_name"] = sample["first_name_std_l"].eq(sample["first_name_std_r"]) & sample[
        "last_name_std_l"
    ].eq(sample["last_name_std_r"])

    sample["stratum"] = {"review": "review_band", "non_match": "fp_check_non_match",
                         "match": "match_precision_check"}[band]
    sample["label"] = None
    sample["review_status"] = "pending"
    sample["reviewer"] = None
    sample["reviewer_note"] = None
    sample = sample.sort_values("match_probability", ascending=False)

    return sample[
        [
            "record_id_l", "record_id_r", "stratum",
            *STRATUM_COLUMNS,
            "match_probability",
            *[f"{f}_{side}" for side in ("l", "r") for f in REVIEW_FIELDS],
            "label", "review_status", "reviewer", "reviewer_note",
        ]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sample candidate pairs for manual review, by decision band."
    )
    parser.add_argument("--n", type=int, default=100, help="Pairs to sample (default 100).")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument(
        "--band",
        choices=list(BANDS),
        default="review",
        help=(
            "Which decision band to sample: 'review' (the human queue the three-way "
            "policy produces), 'non_match' (missed-match estimate), 'match' (precision "
            "estimate — the side device_id covers today, and device_id will not exist "
            "on every future dataset)."
        ),
    )
    parser.add_argument("--sample", action="store_true", help="Read sample-scope predictions.")
    parser.add_argument("--full", action="store_true", help="Read full-run predictions.")
    args = parser.parse_args()

    sample = build_sample(args.full, args.n, args.seed, band=args.band)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    sample.to_csv(SAMPLE_PATH, index=False)

    n = len(sample)
    print(f"Band sampled: {args.band} -> {n:,} pairs")
    print(f"Stratum: {sample['stratum'].unique()[0]}")
    print(f"Agreement breakdown: {sample[STRATUM_COLUMNS].sum().to_dict()}")
    print(f"Saved: {SAMPLE_PATH}")
    print("Fill the 'label' column with match / no_match, then:")
    print("  python -m src.labels --promote")
    print(
        f"Interpretation rule: 0 surprises in {n} pairs -> upper bound "
        f"{round(100 * 3 / n, 1)}% at 95% confidence (rule of three). "
        "1 or more -> report the actual rate instead."
    )


if __name__ == "__main__":
    main()