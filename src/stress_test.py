"""Measure recovery on deliberately corrupted duplicates.

WHY
On the clean file every duplicate group agrees on email, phone, dob, address and
device id, so match probability is bimodal (1.0 or 1e-300), the REVIEW band is
empty and device-truth recall is 100%. That is a property of the data, not proof
that the linker handles corruption. README says so; this module produces the
number that is missing.

WHAT IT DOES
Take pairs that share a device id, corrupt ONE side of each with documented
errors, re-run the production model unchanged, and report how many corrupted
copies are still linked to their original partner, plus how many pairs land in
the review band instead of being confidently wrong.

HONESTY
The corruption is synthetic and written in memory only — no dataset file is
created or modified. These numbers describe the model on deliberately damaged
records, not on a client's dirty data.
"""

from __future__ import annotations

import argparse
import json
import random
import time

import pandas as pd

from .config import MATCH_THRESHOLD, OUTPUT_DIR, PROCESSED_DATA_PATH, RANDOM_SEED
from .eval_truth import device_truth_pairs
from .splink_model import train_and_predict

STRESS_PATH = OUTPUT_DIR / "stress_test.json"

# 9xxxxx keeps corrupted rows after every real record_id, so entity numbering of
# the untouched records cannot shift under them.
CORRUPTED_PREFIX = "rec_9"

# Corrupted rows must not be able to merge two genuine duplicates with each
# other: they keep the original device id, so they can only join the cluster they
# were copied from.
CORRUPT_FIELDS = [
    "first_name_std",
    "last_name_std",
    "email_std",
    "phone_std",
    "dob_std",
    "address_std",
]


def _corrupt_value(rng: random.Random, value: str, kind: str) -> str:
    text = "" if value is None or pd.isna(value) else str(value)
    if not text:
        return text

    if kind == "double_letter":
        # Profiling measured 10,666 records with a repeated adjacent character.
        i = rng.randrange(1, len(text))
        return text[:i] + text[i - 1] + text[i:]
    if kind == "drop_letter":
        if len(text) < 3:
            return text
        i = rng.randrange(1, len(text))
        return text[:i] + text[i + 1:]
    if kind == "swap_letters":
        if len(text) < 3:
            return text
        i = rng.randrange(1, len(text) - 1)
        return text[:i] + text[i + 1] + text[i] + text[i + 2:]
    if kind == "uppercase":
        # Profiling measured 48,473 records with mixed case.
        return text.upper()
    if kind == "phone_drop_digit":
        if len(text) < 7:
            return text
        i = rng.randrange(0, len(text))
        return text[:i] + text[i + 1:]
    if kind == "dob_year_shift":
        try:
            parts = text.split("-")
            if len(parts) != 3:
                return text
            year = int(parts[0]) + rng.choice([-1, 1])
            return f"{year:04d}-{parts[1]}-{parts[2]}"
        except ValueError:
            return text
    if kind == "dob_swap_day_month":
        try:
            year, month, day = (int(p) for p in text.split("-"))
        except ValueError:
            return text
        # Only the ambiguous subset can be swapped into a different valid date.
        if month > 12 or day > 12:
            return text
        return f"{year:04d}-{day:02d}-{month:02d}"
    return text


# Corrupt one side across the identity fields, each with its own probability.
# Corrupting a single field proved nothing: measured on the clean file, one broken
# field still leaves city/address/state agreeing exactly and every copy came back
# at p=1.0 with an empty review band. The informative case is a duplicate that
# looks different in SEVERAL fields at once, so recovery is reported per number
# of corrupted fields.
#
# dob is not always corrupted: it is the strongest surviving signal, and if it
# survives every time the test cannot fail.
FIELD_OPS: list[tuple[str, list[str], float]] = [
    ("last_name_std", ["double_letter", "drop_letter", "swap_letters"], 1.0),
    ("first_name_std", ["uppercase", "drop_letter"], 1.0),
    ("email_std", ["drop_letter", "swap_letters"], 1.0),
    ("phone_std", ["phone_drop_digit"], 1.0),
    ("address_std", ["drop_letter", "swap_letters"], 0.75),
    ("dob_std", ["dob_year_shift", "dob_swap_day_month"], 0.5),
]


def corrupt(df: pd.DataFrame, n_pairs: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (frame_with_corrupted_copies, manifest)."""
    truth = device_truth_pairs(df)
    if truth.empty:
        raise SystemExit("No device-truth pairs: nothing to corrupt.")

    rng = random.Random(seed)
    take = truth.sample(n=min(n_pairs, len(truth)), random_state=seed).sort_values(
        ["record_id_l", "record_id_r"]
    )
    by_id = df.set_index("record_id")
    corrupted_rows = []
    manifest = []

    for i, (left, right) in enumerate(zip(take["record_id_l"], take["record_id_r"]), start=1):
        # Corrupt the right-hand side only: the left stays clean so recovery means
        # "still linked to an untouched record", not "linked to another typo".
        original = right
        row = by_id.loc[original].copy()
        record_id = f"{CORRUPTED_PREFIX}{i:05d}"
        applied: list[str] = []

        for field, kinds, probability in FIELD_OPS:
            if rng.random() > probability:
                continue
            kind = rng.choice(kinds)
            new_value = _corrupt_value(rng, row.get(field), kind)
            if new_value and new_value != row.get(field):
                row[field] = new_value
                applied.append(f"{field}:{kind}")
            elif field == "dob_std" and kind == "dob_swap_day_month":
                # Unambiguous date: not corruptible by that rule, and saying so is
                # part of the measurement.
                applied.append("dob_std:swap_skipped_unambiguous")

        row["record_id"] = record_id
        corrupted_rows.append(row)
        manifest.append(
            {
                "corrupted_record_id": record_id,
                "original_record_id": original,
                "partner_record_id": left,
                "corruptions": ";".join(applied) or "none",
                "corruption_count": len([a for a in applied if "skipped" not in a]),
            }
        )

    corrupted = pd.DataFrame(corrupted_rows)
    frame = pd.concat([df, corrupted], ignore_index=True)
    return frame, pd.DataFrame(manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure recovery on corrupted duplicates.")
    parser.add_argument("--pairs", type=int, default=200, help="How many duplicates to corrupt.")
    parser.add_argument(
        "--threshold", type=float, default=MATCH_THRESHOLD, help="Match threshold to test against."
    )
    args = parser.parse_args()

    started = time.perf_counter()
    df = pd.read_parquet(PROCESSED_DATA_PATH)
    frame, manifest = corrupt(df, args.pairs, RANDOM_SEED)
    n = len(frame)
    print(f"Clean rows: {len(df):,} | corrupted copies: {len(manifest)} | modelling rows: {n:,}")
    print("Corruption is synthetic and in memory only; no dataset file is written.")

    # The corrupted frame gets its own trained model on purpose: the corrupted
    # rows are extra observations, and reusing the production model would
    # measure how a model trained without corruption copes with it.
    pred_df, _ = train_and_predict(frame)

    key = ["record_id_l", "record_id_r"]

    wanted = manifest.copy()
    lo = wanted[["corrupted_record_id", "partner_record_id"]].min(axis=1)
    hi = wanted[["corrupted_record_id", "partner_record_id"]].max(axis=1)
    wanted["record_id_l"] = lo
    wanted["record_id_r"] = hi

    joined = wanted.merge(pred_df[[*key, "match_probability", "match_weight"]], on=key, how="left")
    # A pair the blocking rules never produced is not a low score, it is no score.
    joined["scored"] = joined["match_probability"].notna()
    joined["recovered"] = joined["match_probability"] >= args.threshold

    total = len(joined)
    scored = int(joined["scored"].sum())
    recovered = int(joined["recovered"].sum())
    never_scored = total - scored
    scored_but_missed = scored - recovered
    recall = round(recovered / total, 4)

    per_count = []
    for count, rows in joined.groupby("corruption_count"):
        per_count.append(
            {
                "corrupted_fields": int(count),
                "pairs": len(rows),
                "recovered": int(rows["recovered"].sum()),
                "never_generated_as_candidate": int((~rows["scored"]).sum()),
                "recovery_pct": round(100.0 * rows["recovered"].sum() / len(rows), 2),
            }
        )

    per_op = []
    for op in sorted({o for s in manifest["corruptions"] for o in s.split(";") if o != "none"}):
        rows = joined[joined["corruptions"].str.contains(op, regex=False)]
        if rows.empty:
            continue
        per_op.append(
            {
                "operation": op,
                "pairs": len(rows),
                "recovered": int(rows["recovered"].sum()),
                "recovery_pct": round(100.0 * rows["recovered"].sum() / len(rows), 2),
            }
        )

    band = pred_df[
        (pred_df["match_probability"] > 1e-10) & (pred_df["match_probability"] < args.threshold)
    ]
    result = {
        "caveat": (
            "Synthetic corruption applied in memory to device-truth duplicates. Measures the "
            "model on deliberately damaged records, NOT another dataset. No dataset file "
            "written."
        ),
        "corrupted_pairs": total,
        "seed": RANDOM_SEED,
        "threshold": args.threshold,
        "modelled_rows": n,
        "candidate_pairs": len(pred_df),
        "recovered": recovered,
        "never_generated_as_candidate": never_scored,
        "scored_but_below_threshold": scored_but_missed,
        "recall_on_corrupted": recall,
        "review_band_pairs": len(band),
        "review_band_match_weight_min": round(float(band["match_weight"].min()), 3) if len(band) else None,
        "review_band_match_weight_max": round(float(band["match_weight"].max()), 3) if len(band) else None,
        "by_corrupted_field_count": per_count,
        "per_operation": per_op,
        "runtime_seconds": round(time.perf_counter() - started, 2),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STRESS_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    manifest.to_csv(OUTPUT_DIR / "stress_test_pairs.csv", index=False)

    print()
    print(f"Corrupted pairs        : {total}")
    print(f"Recovered (p >= {args.threshold}) : {recovered} ({100 * recall:.2f}%)")
    print(f"Never even a candidate : {never_scored}")
    print(f"Scored but below thresh: {scored_but_missed}")
    print(f"Review band pairs      : {len(band)}")
    print("Recovery by number of corrupted fields:")
    for row in per_count:
        print(
            f"  {row['corrupted_fields']} fields  {row['recovered']:4d}/{row['pairs']:<4d}"
            f" {row['recovery_pct']:6.2f}%  never-candidate {row['never_generated_as_candidate']}"
        )
    print("Per operation:")
    for row in per_op:
        print(f"  {row['operation']:34s} {row['recovered']:4d}/{row['pairs']:<4d} {row['recovery_pct']:6.2f}%")
    print(f"Runtime: {result['runtime_seconds']}s")
    print(f"Saved: {STRESS_PATH}")


if __name__ == "__main__":
    main()