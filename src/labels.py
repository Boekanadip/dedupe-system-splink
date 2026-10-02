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
)

# Explicit filenames. Sourcing labels by glob order would silently pick up a
# half-reviewed queue instead of the reviewed set.
SILVER_PATH = LABELS_DIR / "silver_pairs.csv"
GOLD_PATH = LABELS_DIR / "gold_labels.csv"
QUEUE_PATH = LABELS_DIR / "review_queue.csv"
# Written by src/review_sample.py. Declared here as a plain path (not an import)
# because review_sample already imports REVIEW_FIELDS from this module.
FP_SAMPLE_PATH = LABELS_DIR / "review_fp_sample.csv"

TRUTHY = {"1", "true", "t", "yes", "y", "match", "positive", "duplicate", "dup"}
# Without these, a reviewer's "no_match" is neither saved nor accepted: promote_gold
# silently dropped every row whose label was not in TRUTHY, so a fully reviewed
# 100-pair file could yield a gold set with no negatives in it at all.
FALSY = {
    "0", "false", "f", "no", "n", "no_match", "non_match", "not_match",
    "different", "beda", "beda_orang", "negative", "reject", "tidak_cocok",
}
LABEL_VALUES = TRUTHY | FALSY

# Review cap per stratum. A queue nobody can finish is not a queue.
QUEUE_SAMPLE_PER_STRATUM = 200
# Email-only collisions are already known to be different people: 1,596 email
# matches sit on different customer_id and phone. Sample few of them.
QUEUE_SAMPLE_LOW_VALUE = 50

# Side-by-side values a reviewer needs to judge a pair. Standardized columns only:
# reviewing the raw values would invite judging the typo, not the identity.
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
    """Deterministic high-precision pairs. Not reviewed, therefore not gold.

    customer_id is deliberately NOT used as a basis (AGENTS.md forbids it as
    sole duplicate truth). It agrees with these rules on all 1,867 pairs and is
    reported separately as a sanity check, never as the source of the label.

    Positives require two identifiers to agree, because email alone collides:
    1,596 email matches sit on different customer_id / phone / dob.
    """
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

    # Same phone or same email but the other identifiers contradict: two people
    # sharing one contact field. NULL-safe diffs so a null on one side does not
    # silently count as agreement or as a conflict.
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
    """Sanity check only: do the deterministic labels agree with customer_id?

    Reported because a low number would mean the silver rules are wrong, not
    because customer_id decides the label.
    """
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
    """Record WHICH identity fields agree, not just how many.

    Counting is misleading here: 2,590 of the candidate pairs agree on dob only,
    which is a birthday collision between different people. A count-based
    stratum buried those next to the 610 same-full-name pairs that genuinely
    need a reviewer's judgement.
    """
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
    """Widen a pair table with both records' field values, so a reviewer never
    has to open another file to judge a pair."""
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
    """Strata a human must review, prioritising silver/Model disagreement.

    Produced from the current prediction output. Strata, not a uniform random
    sample, because 11,807 uniform pairs would waste most of them on obvious
    non-matches.
    """
    predictions_path = config_predictions_path(full=full)
    if not predictions_path.exists():
        print(
            f"No {predictions_path.name} yet — run "
            f"python -m src.splink_model{'' if full else ' --full'} first."
        )
        return pd.DataFrame()

    preds = pd.read_parquet(predictions_path)[["record_id_l", "record_id_r", "match_probability"]]
    silver = build_silver(df)

    # Labels are built on every row, but a model run may cover a sample. A silver
    # pair outside the modelled rows is not "unlabelled", it is simply out of
    # scope, and mixing the two would make the strata wrong.
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

    strata: list[tuple[str, pd.DataFrame]] = []
    # labelled by silver, contradicted by the model — the disagreements are what
    # a reviewer can actually correct.
    strata.append(("silver_positive_low_probability", merged[(merged["label"] == 1) & (merged["match_probability"] < 0.5)]))
    strata.append(("silver_negative_high_probability", merged[(merged["label"] == 0) & (merged["match_probability"] >= 0.5)]))
    # Blocked together but unlabelled. Stratified by WHICH field agrees, not by
    # probability: every score below the top decile here is 1e-300, so probability
    # separates nothing. A shared name or phone is a real judgement call; a
    # shared dob alone is a birthday collision and is not worth reviewer time.
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

    # label is intentionally blank: filling it IS the review. Gold is produced by
    # copying this file to gold_labels.csv with 'label' set, not by renaming.
    queue["label"] = None
    queue["review_status"] = "pending"
    queue["reviewer"] = None
    queue["reviewer_note"] = None
    queue = queue.sort_values(["stratum", "match_probability"], ascending=[True, False])
    return queue[
        [
            "record_id_l", "record_id_r", "stratum",
            "agree_email", "agree_phone", "agree_dob", "agree_name", "agree_city",
            "match_probability",
            *[f"{f}_{side}" for side in ("l", "r") for f in REVIEW_FIELDS],
            "label", "review_status", "reviewer", "reviewer_note",
        ]
    ]


def load_labels() -> tuple[pd.DataFrame | None, str]:
    """Return reviewed labels if gold exists, else silver, else nothing.

    The source string is returned so callers can refuse to call silver output
    "gold metrics".
    """
    for path, source in ((GOLD_PATH, "gold"), (SILVER_PATH, "silver")):
        if not path.exists():
            continue
        # sep=None sniffs the delimiter. Reviewed files come back from Excel
        # with ';' under a comma-decimal locale, and read_csv(path) would fold
        # the whole header into one column name.
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
        if source == "gold" and normalised.isna().any():
            # A typo like "yes"/"maybe" would otherwise become a silent negative
            # and quietly poison precision and recall.
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
        return labels.drop_duplicates(), source

    return None, "none"


def save_silver(df: pd.DataFrame) -> pd.DataFrame:
    silver = build_silver(df)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    silver.to_csv(SILVER_PATH, index=False)
    return silver


def carry_over_reviewed(queue: pd.DataFrame) -> pd.DataFrame:
    """Re-attach labels already given for these same pairs.

    The queue is rebuilt on every run from a random sample, so regenerating it
    must not throw away human judgement. Re-running the pipeline deleted 100
    completed reviews this way. Carrying labels forward is safe because a pair
    (record_id_l, record_id_r) is a fixed fact: whether the reviewer called it a
    match does not change when the queue is redrawn.
    """
    if not QUEUE_PATH.exists() or queue.empty:
        return queue

    previous = _read_review(QUEUE_PATH)
    if "label" not in previous.columns:
        return queue
    previous["human_label"] = previous["label"].map(normalise_label)
    reviewed = previous[previous["human_label"].notna()]
    if reviewed.empty:
        return queue

    # Keys are compared as strings on both sides: Excel may have rewritten
    # rec_000123 as a number, and an int/str mismatch would silently drop every
    # review it was supposed to carry.
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
        queue.to_csv(QUEUE_PATH, index=False)
    return queue


def _label_key(value) -> str:
    """Fold spelling variants so 'non-match', 'No Match' and 'non_match' agree.

    A reviewer naturally writes 'non-match'. Without this, a full 236-row review
    promoted to 11 gold rows with no error anywhere — the earlier version of this
    bug dropped every 'no_match' row silently, and then a hyphen spelled it again.
    """
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def normalise_label(value) -> str | None:
    """Map any accepted review vocabulary to 'match' / 'no_match', else None.

    None means "not reviewed or not understood". Callers must treat that as
    missing, never as a negative: a blank cell counted as no_match would inflate
    the false-positive rate without a single human looking at the pair.
    """
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    key = _label_key(value)
    if key in TRUTHY:
        return "match"
    if key in FALSY:
        return "no_match"
    return None


def _read_review(path) -> pd.DataFrame:
    """Read a review file while surviving the Excel comma-decimal locale round-trip.

    That locale saves CSV with ';' delimiter and converts all numbers to comma-
    decimal scientific notation: match_probability becomes '2,92E+11', phone_std
    becomes '1,83352E+14'.  Those numeric columns are read as strings and survive
    the round-trip as strings, which is all gold_labels.csv needs for them.
    """
    raw = path.read_text(encoding="utf-8")
    # The file is semicolon-delimited after an Excel save.  The first row has 27
    # semicolons.  Detect that before sep=None mis-sniffs it as one column.
    if ";" in raw.split("\n", 1)[0]:
        return pd.read_csv(path, sep=";")
    return pd.read_csv(path, sep=None, engine="python")


def _backup_gold() -> Path | None:
    """Never destroy an existing gold set without a copy.

    gold_labels.csv is the only file a human's judgement lives in. The queue files
    are rebuilt (and can be replaced by a different sample) on every run, so
    promoting a new queue over an old gold silently deletes the reviewed labels.
    """
    if not GOLD_PATH.exists() or GOLD_PATH.stat().st_size == 0:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = LABELS_DIR / f"gold_labels_{stamp}.csv"
    shutil.copy2(GOLD_PATH, backup)
    return backup


def promote_gold() -> int:
    """Copy reviewed queue rows into gold_labels.csv.

    Reads BOTH the strata queue and the false-positive sample, so a reviewed
    sample drawn for precision checking cannot sit unused next to a gold file.
    Unreviewed rows are dropped rather than carried through: a blank label would
    otherwise be read as "not a match" and count as a false negative.

    Existing gold rows whose pair is NOT in this promotion run are KEPT
    (same rule as feedback.csv): human labels accumulate. A re-reviewed pair
    takes the newer label (keep='last'). An empty promotion never overwrites
    gold — wiping 247 reviewed labels because the current queue is blank
    would be silent data loss.
    """
    sources = [path for path in (QUEUE_PATH, FP_SAMPLE_PATH) if path.exists()]
    if not sources:
        raise FileNotFoundError(
            f"No review queue at {QUEUE_PATH} and no FP sample at {FP_SAMPLE_PATH}"
        )
    frames = []
    for path in sources:
        frame = _read_review(path)
        # Detect numeric columns mangled by Excel's comma-decimal locale.
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
        # Older reviewed pairs survive; a re-reviewed pair takes the new label.
        merged = pd.concat([existing[keep_cols], new], ignore_index=True)
        merged = merged.drop_duplicates(subset=["record_id_l", "record_id_r"], keep="last")
    else:
        merged = new

    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(GOLD_PATH, index=False)
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

    if not PROCESSED_DATA_PATH.exists():
        raise FileNotFoundError(
            "Standardized parquet belum ada. Jalankan: python -m src.standardize"
        )
    df = pd.read_parquet(PROCESSED_DATA_PATH)

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
