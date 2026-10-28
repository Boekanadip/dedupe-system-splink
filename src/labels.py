from __future__ import annotations

import argparse
import shutil
from datetime import datetime

import duckdb
import pandas as pd

from .config import (
    LABELS_DIR,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    predictions_path as config_predictions_path,
    atomic_write_parquet,
    atomic_write_json,
    active_path,
    atomic_write_csv,
)


SILVER_PATH = LABELS_DIR / "silver_pairs.csv"
GOLD_PATH = LABELS_DIR / "gold_labels.csv"
QUEUE_PATH = LABELS_DIR / "review_queue.csv"
FP_SAMPLE_PATH = LABELS_DIR / "review_fp_sample.csv"
TRUTHY = {"1", "true", "t", "yes", "y", "match", "positive", "duplicate", "dup"}
FALSY = {
    "0", "false", "f", "no", "n", "no_match", "non_match", "not_match",
    "different", "beda", "beda_orang", "negative", "reject", "tidak_cocok",
}
LABEL_VALUES = TRUTHY | FALSY


QUEUE_SAMPLE_PER_STRATUM = 200

QUEUE_SAMPLE_LOW_VALUE = 50

REVIEW_FIELDS = [
    "first_name_std",
    "last_name_std",
    "email_std",
    "phone_std",
    "dob_std",
    "city_std",
    "state_std",
    "address_std",
]

QUEUE_COLUMNS: list[str] = [
    "record_id_l",
    "record_id_r",
    "stratum",
    "agree_count",
    "agree_email",
    "agree_phone",
    "agree_dob",
    "agree_name",
    "agree_city",
    "match_probability",
    *[f"{f}_{side}" for side in ("l", "r") for f in REVIEW_FIELDS],
    "label",
    "review_status",
    "reviewer",
    "reviewer_note",
]


def exclude_gold_pairs(queue: pd.DataFrame, gold: pd.DataFrame) -> pd.DataFrame:
    """Return queue rows whose unordered record pair is not already in gold."""
    pair_columns = {"record_id_l", "record_id_r"}
    for name, frame in (("review queue", queue), ("gold labels", gold)):
        missing = pair_columns - set(frame.columns)
        if missing:
            raise ValueError(f"{name} is missing pair columns: {sorted(missing)}")

    gold_pairs = {
        tuple(sorted((str(left), str(right))))
        for left, right in gold[["record_id_l", "record_id_r"]].itertuples(
            index=False, name=None
        )
        if pd.notna(left) and pd.notna(right)
    }
    queue_pairs = [
        tuple(sorted((str(left), str(right))))
        for left, right in queue[["record_id_l", "record_id_r"]].itertuples(
            index=False, name=None
        )
    ]
    return queue.loc[[pair not in gold_pairs for pair in queue_pairs]].copy()


def _pairs_where(df: pd.DataFrame, where: str) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("src", df)
    return con.execute(
        f"""
        SELECT l."record_id" AS record_id_l,
               r."record_id" AS record_id_r
        FROM src AS l
        INNER JOIN src AS r
            ON l."record_id" < r."record_id"
        WHERE {where}
        """
    ).fetchdf()


def build_silver(df: pd.DataFrame) -> pd.DataFrame:
    positives = _pairs_where(
        df,
        """
        (
            l."phone_std" = r."phone_std"
            AND l."dob_std" = r."dob_std"
        )
        OR (
            l."email_std" = r."email_std"
            AND l."phone_std" = r."phone_std"
        )
        """,
    )
    positives["label"] = 1
    positives["evidence"] = "phone+dob | email+phone"

    negatives = _pairs_where(
        df,
        """
        (
            l."email_std" = r."email_std"
            AND NOT (l."phone_std" IS NOT DISTINCT FROM r."phone_std")
            AND NOT (l."dob_std" IS NOT DISTINCT FROM r."dob_std")
            AND NOT (l."first_name_std" IS NOT DISTINCT FROM r."first_name_std")
        )
        OR (
            l."phone_std" = r."phone_std"
            AND NOT (l."dob_std" IS NOT DISTINCT FROM r."dob_std")
            AND NOT (l."first_name_std" IS NOT DISTINCT FROM r."first_name_std")
        )
        """,
    )
    negatives["label"] = 0
    negatives["evidence"] = "conflicting dob and name"

    out = pd.concat([positives, negatives], ignore_index=True)
    out["label_source"] = "silver_deterministic"
    out["review_status"] = "unreviewed"
    return out[["record_id_l", "record_id_r", "label", "label_source", "review_status", "evidence"]]


def customer_id_agreement(df: pd.DataFrame, silver: pd.DataFrame) -> dict:

    cid = _pairs_where(df, 'l."customer_id" = r."customer_id"')
    labelled = silver[["record_id_l", "record_id_r"]].merge(
        cid, on=["record_id_l", "record_id_r"], how="inner"
    )
    positives = silver[silver["label"] == 1]
    positives_in_cid = positives.merge(cid, on=["record_id_l", "record_id_r"], how="inner")
    return {
        "customer_id_pairs": len(cid),
        "silver_positive_pairs": len(positives),
        "silver_positive_in_customer_id": len(positives_in_cid),
        "customer_id_pairs_not_silver_positive": len(cid) - len(positives_in_cid),
    }


def agree_fields(df: pd.DataFrame, preds: pd.DataFrame) -> pd.DataFrame:

    con = duckdb.connect()
    con.register("src", df)
    con.register("pred", preds)
    return con.execute(
        """
        SELECT
            p.record_id_l,
            p.record_id_r,
            (l.email_std = r.email_std) AS agree_email,
            (l.phone_std = r.phone_std) AS agree_phone,
            (l.dob_std = r.dob_std) AS agree_dob,
            (l.first_name_std = r.first_name_std AND l.last_name_std = r.last_name_std) AS agree_name,
            (l.city_std = r.city_std) AS agree_city
        FROM pred p
        JOIN src l ON l.record_id = p.record_id_l
        JOIN src r ON r.record_id = p.record_id_r
        """
    ).fetchdf()


def attach_evidence(df: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
   
    left = df[["record_id", *REVIEW_FIELDS]].rename(
        columns={**{"record_id": "record_id_l"}, **{c: f"{c}_l" for c in REVIEW_FIELDS}}
    )
    right = df[["record_id", *REVIEW_FIELDS]].rename(
        columns={**{"record_id": "record_id_r"}, **{c: f"{c}_r" for c in REVIEW_FIELDS}}
    )
    return (
        pairs.merge(left, on="record_id_l", how="left")
        .merge(right, on="record_id_r", how="left")
    )


def build_review_queue(df: pd.DataFrame, full: bool = False) -> pd.DataFrame:

    predictions_path = config_predictions_path(full=full)
    if not predictions_path.exists():
        print(
            f"No {predictions_path.name} yet — run "
            f"python -m src.splink_model{'' if full else ' --full'} first."
        )
        return pd.DataFrame()

    preds = pd.read_parquet(predictions_path)[["record_id_l", "record_id_r", "match_probability"]]
    silver = build_silver(df)
    modelled = set(preds["record_id_l"]) | set(preds["record_id_r"])
    silver_in_scope = silver[
        silver["record_id_l"].isin(modelled) & silver["record_id_r"].isin(modelled)
    ]
    print(
        f"Silver pairs in model scope: {len(silver_in_scope):,} of {len(silver):,} "
        f"(modelled rows: {len(modelled):,})"
    )

    merged = preds.merge(
        silver[["record_id_l", "record_id_r", "label", "evidence"]],
        on=["record_id_l", "record_id_r"],
        how="left",
    ).merge(agree_fields(df, preds), on=["record_id_l", "record_id_r"], how="left")

    agree_cols = ["agree_email", "agree_phone", "agree_dob", "agree_name", "agree_city"]
    merged["agree_count"] = merged[agree_cols].fillna(False).sum(axis=1)

    strata: list[tuple[str, pd.DataFrame]] = []
    strata.append(("silver_positive_low_probability", merged[(merged["label"] == 1) & (merged["match_probability"] < 0.5)]))
    strata.append(("silver_negative_high_probability", merged[(merged["label"] == 0) & (merged["match_probability"] >= 0.5)]))
    unlabelled = merged[merged["label"].isna()]
    strata.append(("unlabelled_high_probability", unlabelled[unlabelled["match_probability"] >= 0.5]))
    strata.append(("unlabelled_same_name", unlabelled[unlabelled["agree_name"]]))
    strata.append(("unlabelled_same_phone", unlabelled[~unlabelled["agree_name"] & unlabelled["agree_phone"]]))
    strata.append(("unlabelled_same_email", unlabelled[unlabelled["agree_email"] & ~unlabelled["agree_phone"]]))

    frames = []
    for name, frame in strata:
        if frame.empty:
            print(f"Queue stratum {name}: 0")
            continue
        cap = QUEUE_SAMPLE_LOW_VALUE if name == "unlabelled_same_email" else QUEUE_SAMPLE_PER_STRATUM
        take = frame.sample(
            n=min(cap, len(frame)),
            random_state=42,
        ).copy()
        take["stratum"] = name
        frames.append(take)
        print(f"Queue stratum {name}: {len(take):,} of {len(frame):,} available")

    if not frames:
        return pd.DataFrame()

    queue = pd.concat(frames, ignore_index=True)
    queue = attach_evidence(df, queue)

    queue["label"] = None
    queue["review_status"] = "pending"
    queue["reviewer"] = None
    queue["reviewer_note"] = None

    queue = queue.sort_values(
        ["agree_count", "match_probability"], ascending=[False, False]
    )
    return queue[
        [
            "record_id_l", "record_id_r", "stratum", "agree_count",
            *agree_cols,
            "match_probability",
            *[f"{f}_{side}" for side in ("l", "r") for f in REVIEW_FIELDS],
            "label", "review_status", "reviewer", "reviewer_note",
        ]
    ]


def load_labels(source: str | None = None) -> tuple[pd.DataFrame | None, str]:
    if source in (None, "auto"):
        order = ((GOLD_PATH, "gold"), (SILVER_PATH, "silver"))
    elif source in ("gold", "silver"):
        order = ((GOLD_PATH, "gold"),) if source == "gold" else ((SILVER_PATH, "silver"),)
    else:
        raise ValueError(f"Unknown label source {source!r}; expected 'gold', 'silver' or 'auto'.")

    for path, name in order:
        if not path.exists():
            continue

        raw = pd.read_csv(path, sep=None, engine="python")
        required = {"record_id_l", "record_id_r"}
        if not required.issubset(raw.columns):
            raise ValueError(
                f"{path.name} must contain {sorted(required)}; found {list(raw.columns)}"
            )
        label_col = next(
            (c for c in ("label", "is_match", "match", "is_positive") if c in raw.columns), None
        )
        if label_col is None:
            raise ValueError(
                f"{path.name} needs a truth column named label/is_match/match/is_positive; "
                f"found {list(raw.columns)}"
            )

        pairs = raw[["record_id_l", "record_id_r"]].astype(str)
        normalised = raw[label_col].map(normalise_label)
        if name == "gold" and normalised.isna().any():

            bad = sorted(set(raw[label_col].astype(str)[normalised.isna()]))[:5]
            raise ValueError(
                f"{path.name}: unrecognised label values {bad}. "
                f"Use one of {sorted(LABEL_VALUES)} (hyphens and spaces are accepted)."
            )
        labels = pd.DataFrame(
            {
                "record_id_l": pairs[["record_id_l", "record_id_r"]].min(axis=1),
                "record_id_r": pairs[["record_id_l", "record_id_r"]].max(axis=1),
            }
        )
        labels["is_positive"] = normalised == "match"
        return labels.drop_duplicates(), name

    return None, "none"


def save_silver(df: pd.DataFrame) -> pd.DataFrame:
    silver = build_silver(df)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_csv(silver, SILVER_PATH)
    return silver


def carry_over_reviewed(queue: pd.DataFrame) -> pd.DataFrame:

    if not QUEUE_PATH.exists() or queue.empty:
        return queue

    previous = _read_review(QUEUE_PATH)
    if "label" not in previous.columns:
        return queue
    previous["human_label"] = previous["label"].map(normalise_label)
    reviewed = previous[previous["human_label"].notna()]
    if reviewed.empty:
        return queue

    keys = ["record_id_l", "record_id_r"]
    queue = queue.copy()
    reviewed = reviewed.copy()
    for frame in (queue, reviewed):
        for key in keys:
            frame[key] = frame[key].astype(str).str.strip()
    carried = reviewed[keys + ["label", "reviewer", "reviewer_note"]].drop_duplicates(keys)
    for column in ("label", "reviewer", "reviewer_note"):
        if column not in queue.columns:
            queue[column] = None

    before = queue["label"].notna().sum()
    queue = queue.merge(carried, on=keys, how="left", suffixes=("", "_carried"))
    for column in ("label", "reviewer", "reviewer_note"):
        queue[column] = queue[f"{column}_carried"].where(
            queue[f"{column}_carried"].notna(), queue[column]
        )
        queue = queue.drop(columns=[f"{column}_carried"])
    after = queue["label"].notna().sum()
    if after > before:
        print(
            f"Carried over {after - before:,} existing review(s) for pairs that are in the "
            f"new queue. Labels are never cleared by a rebuild."
        )
    return queue


def save_review_queue(df: pd.DataFrame, full: bool = False) -> pd.DataFrame:
    queue = build_review_queue(df, full=full)
    if not queue.empty:
        LABELS_DIR.mkdir(parents=True, exist_ok=True)
        queue = carry_over_reviewed(queue)
        atomic_write_csv(queue, QUEUE_PATH)
    return queue


def _label_key(value) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def normalise_label(value) -> str | None:

    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    key = _label_key(value)
    if key in TRUTHY:
        return "match"
    if key in FALSY:
        return "no_match"
    return None


def _read_review(path) -> pd.DataFrame:

    raw = path.read_text(encoding="utf-8")
    if ";" in raw.split("\n", 1)[0]:
        return pd.read_csv(path, sep=";")
    return pd.read_csv(path, sep=None, engine="python")


def _backup_gold() -> Path | None:

    if not GOLD_PATH.exists() or GOLD_PATH.stat().st_size == 0:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = LABELS_DIR / f"gold_labels_{stamp}.csv"
    shutil.copy2(GOLD_PATH, backup)
    return backup


def promote_gold() -> int:
    sources = [path for path in (QUEUE_PATH, FP_SAMPLE_PATH) if path.exists()]
    if not sources:
        raise FileNotFoundError(
            f"No review queue at {QUEUE_PATH} and no FP sample at {FP_SAMPLE_PATH}"
        )
    frames = []
    for path in sources:
        frame = _read_review(path)
        # Deteksi kolom angka yang berubah akibat pengaturan desimal berkoma di Excel.
        mangled = {
            c for c in frame.columns
            if frame[c].dtype == object and frame[c].astype(str).str.contains(
                r"[,]\d+E[+-]?\d", regex=True, na=False
            ).any()
        }
        if mangled:
            print(
                f"WARNING: {path.name}: Excel mangled these columns to scientific "
                f"notation with comma decimals: {sorted(mangled)}. They are "
                "cosmetically wrong in gold_labels.csv but threshold_eval reads "
                "the authoritative values from the predictions parquet."
            )
        if "label" not in frame.columns:
            raise ValueError(f"{path.name} has no 'label' column to fill in")
        if "stratum" not in frame.columns:
            frame["stratum"] = path.stem
        frames.append(frame)
        print(f"Reading {path.name}: {len(frame):,} rows")
    queue = pd.concat(frames, ignore_index=True)

    raw = queue["label"].astype(str).str.strip()
    reviewed = queue[queue["label"].map(normalise_label).notna()].copy()
    reviewed["label"] = reviewed["label"].map(normalise_label)
    dropped = len(queue) - len(reviewed)
    if dropped:
        print(
            f"WARNING: {dropped} of {len(queue)} rows left out of gold — label still empty or "
            "unrecognised. A blank label must not become a negative."
        )
    if reviewed.empty:
        print(
            "No newly reviewed rows — gold_labels.csv left untouched. "
            "Fill the 'label' column in the review queue first."
        )
        return 0

    negatives = int((reviewed["label"] == "no_match").sum())
    print(f"Newly reviewed: {len(reviewed):,} ({len(reviewed) - negatives:,} match / {negatives:,} no_match)")

    keep_cols = [
        "record_id_l", "record_id_r", "label", "stratum",
        "agree_email", "agree_phone", "agree_dob", "agree_name", "agree_city",
        "match_probability",
    ]
    new = reviewed[keep_cols]
    n_before = 0
    if GOLD_PATH.exists() and GOLD_PATH.stat().st_size > 0:
        existing = pd.read_csv(GOLD_PATH, sep=None, engine="python")
        n_before = len(existing)
        existing = existing[[c for c in keep_cols if c in existing.columns]]
        for col in keep_cols:
            if col not in existing.columns:
                existing[col] = None
        # Pertahankan pasangan lama yang sudah ditinjau; gunakan label baru
        # untuk pasangan yang ditinjau ulang.
        merged = pd.concat([existing[keep_cols], new], ignore_index=True)
        merged = merged.drop_duplicates(subset=["record_id_l", "record_id_r"], keep="last")
    else:
        merged = new

    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_csv(merged, GOLD_PATH)
    print(f"Gold rows: {len(merged):,} (was {n_before:,}, +{len(merged) - n_before:,} net)")
    return len(merged)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build silver pairs and the human review queue.")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Only: copy reviewed queue rows into gold_labels.csv.",
    )
    parser.add_argument(
        "--feedback",
        action="store_true",
        help="Only: persist reviewed pairs to data/labels/feedback.csv (DESIGN section 12).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Build the review queue from full-run predictions.",
    )
    parser.add_argument(
        "--silver-only",
        action="store_true",
        help="Skip the review queue, which needs predictions that do not exist yet.",
    )
    args = parser.parse_args()

    if args.promote:
        backup = _backup_gold()
        if backup:
            print(f"Previous gold backed up: {backup.name}")
        written = promote_gold()
        print(f"Gold rows written: {written:,} -> {GOLD_PATH}")
        print(f"load_labels() now resolves to: {load_labels()[1]}")
        return

    if args.feedback:
        from .feedback import main as feedback_main

        feedback_main()
        return

    if not active_path(PROCESSED_DATA_PATH).exists():
        raise FileNotFoundError(
            "Standardized parquet belum ada. Jalankan: python -m src.standardize"
        )
    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))

    silver = save_silver(df)
    positives = int((silver["label"] == 1).sum())
    negatives = int((silver["label"] == 0).sum())
    print(f"Silver pairs: {len(silver):,} ({positives:,} positive / {negatives:,} negative)")
    print("Sanity check:", customer_id_agreement(df, silver))
    print(f"Saved: {SILVER_PATH}")

    queue = (
        pd.DataFrame()
        if args.silver_only
        else save_review_queue(df, full=args.full)
    )
    if not queue.empty:
        print(f"Review queue rows: {len(queue):,} -> {QUEUE_PATH}")
        print("Isi kolom 'label' dengan match / no_match, lalu: python -m src.labels --promote")
        print("Isi kolom 'reviewer' dengan nama/kode reviewer.")

    source = load_labels()[1]
    print(f"load_labels() currently resolves to: {source}")


if __name__ == "__main__":
    main()
