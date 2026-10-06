"""Cross-check human labels against the device_id channel.

Nothing in the pipeline ever compared a human label against the one channel the
model never sees. MEASURED on the current state: 8 of 114 human `match`
decisions share a name and an email but carry a different `customer_id`, a
different `device_id`, and a different date of birth, phone, address, city and
state. Those are two different customers who happen to share an email, not one
person who moved - labelling them `match` understated recall and, worse, taught
the next reviewer that a shared email is enough.

`device_id` is a reference channel and not real-world truth (see AGENTS.md 11),
so this module never rewrites a label on its own: it reports, it files the
evidence, and it only corrects gold once a human has ruled, via --apply.

Run:
    python -m src.label_audit                 # report only, writes nothing
    python -m src.label_audit --apply         # correct contradicted rows in gold
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .apply_gold import device_sets
from .config import OUTPUT_DIR, PROCESSED_DATA_PATH
from .labels import GOLD_PATH, LABELS_DIR, _backup_gold, _read_review, normalise_label

AUDIT_PATH = OUTPUT_DIR / "label_audit.json"
DISPUTED_PATH = LABELS_DIR / "disputed_pairs.csv"

REASON = (
    "device_id and customer_id both differ while name and email match; "
    "email alone is not evidence of the same customer"
)

DISPUTED_COLUMNS = [
    "record_id_l",
    "record_id_r",
    "original_label",
    "corrected_label",
    "stratum",
    "device_ids_l",
    "device_ids_r",
    "match_probability",
    "reason",
    "decided_by",
    "decided_at",
]


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left <= right else (right, left)


def audit() -> pd.DataFrame:
    """One row per labelled pair, with a verdict against the device channel.

    Verdict is one of:
      agrees        - the label matches what the device channel says
      contradicted  - the label says match, the device channel says different
      unverifiable  - at least one side carries no device id, so nothing to check
    """
    if not GOLD_PATH.exists():
        raise SystemExit(f"No gold labels at {GOLD_PATH}")

    labels = _read_review(GOLD_PATH)
    labels["human_label"] = labels["label"].map(normalise_label)
    labels = labels[labels["human_label"].notna()].copy()
    if labels.empty:
        raise SystemExit("gold_labels.csv has no recognisable labels to audit")

    devices = device_sets(
        pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id", "device_ids_std"])
    )

    rows = []
    for row in labels.itertuples():
        left, right = _pair_key(str(row.record_id_l), str(row.record_id_r))
        dl, dr = devices.get(left), devices.get(right)
        same_person = bool(dl) and bool(dr) and dl == dr
        is_match = row.human_label == "match"
        if not dl or not dr:
            verdict = "unverifiable"
        elif is_match == same_person:
            verdict = "agrees"
        else:
            verdict = "contradicted"
        rows.append(
            {
                "record_id_l": left,
                "record_id_r": right,
                "human_label": row.human_label,
                "stratum": getattr(row, "stratum", ""),
                "match_probability": getattr(row, "match_probability", None),
                "device_ids_l": ";".join(sorted(dl)) if dl else "",
                "device_ids_r": ";".join(sorted(dr)) if dr else "",
                "verdict": verdict,
            }
        )
    return pd.DataFrame(rows)


def _report(frame: pd.DataFrame) -> dict:
    per_stratum = (
        frame.groupby(["stratum", "verdict"]).size().unstack(fill_value=0).to_dict("index")
    )
    counts = frame["verdict"].value_counts().to_dict()
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "gold_source": str(GOLD_PATH),
        "labelled_pairs": len(frame),
        "counts": counts,
        "per_stratum": {str(k): v for k, v in per_stratum.items()},
        "note": (
            "device_id is a reference channel, not real-world truth. A 'contradicted' "
            "verdict means a human needs to rule, not that the label is automatically wrong."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare human labels against the device_id channel."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Correct contradicted rows in gold_labels.csv after a human has ruled.",
    )
    parser.add_argument(
        "--decided-by",
        default="business_owner",
        help="Who ruled on the contradicted rows; recorded in disputed_pairs.csv.",
    )
    args = parser.parse_args()

    frame = audit()
    report = _report(frame)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    counts = report["counts"]
    print(f"Labelled pairs audited : {len(frame):,}")
    print(f"  agrees               : {counts.get('agrees', 0):,}")
    print(f"  contradicted        : {counts.get('contradicted', 0):,}")
    print(f"  unverifiable        : {counts.get('unverifiable', 0):,}")

    disputed = frame[frame["verdict"] == "contradicted"].copy()
    stamp = datetime.now().isoformat(timespec="seconds")
    out = pd.DataFrame(
        {
            "original_label": disputed["human_label"],
            "corrected_label": "no_match" if args.apply else disputed["human_label"],
            "reason": REASON,
            "decided_by": args.decided_by if args.apply else "",
            "decided_at": stamp if args.apply else "",
        },
        index=disputed.index,
    )
    disputed = pd.concat([disputed, out], axis=1)[DISPUTED_COLUMNS]
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    disputed.to_csv(DISPUTED_PATH, index=False)
    print(f"Disputed pairs filed   : {len(disputed):,} -> {DISPUTED_PATH}")
    print(f"Audit report           : {AUDIT_PATH}")

    if not args.apply:
        if not disputed.empty:
            print("\n--dry-run: gold_labels.csv untouched. Re-run with --apply to correct.")
        return

    if disputed.empty:
        print("Nothing to correct.")
        return

    backup = _backup_gold()
    if backup:
        print(f"Backup                 : {backup.name}")

    gold = _read_review(GOLD_PATH)
    key = list(zip(gold["record_id_l"].astype(str), gold["record_id_r"].astype(str)))
    fixed = {_pair_key(a, b) for a, b in zip(disputed["record_id_l"], disputed["record_id_r"])}
    normalised = [(_pair_key(a, b)) for a, b in key]
    gold["label"] = [
        "no_match" if pair in fixed else old for pair, old in zip(normalised, gold["label"])
    ]
    gold.to_csv(GOLD_PATH, index=False)
    print(f"Corrected in gold      : {len(disputed)} row(s) match -> no_match")
    print("Next: python -m src.feedback   (feedback.csv is derived from gold)")
    print("Then: python -m src.threshold_eval --source gold")


if __name__ == "__main__":
    raise SystemExit(main())