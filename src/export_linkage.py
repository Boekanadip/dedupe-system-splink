"""Export the evidence behind a decision band, one row per pair.

Explainability (PRD, Non-Functional Requirements): "The system should retain
enough evidence to explain why a pair/entity relationship received its score and
decision." The predictions parquet keeps that, but it is a binary blob nobody
can read in a review meeting. This writes the same evidence as a spreadsheet.

`device_match` is per-row on purpose. "0 false merges" is a claim; putting the
check in the file makes it filterable instead of something a report asserts.

Splink 4.0.17 names the comparison levels `gamma_gamma_<column>` — the prefix is
applied twice. Renamed to `cmp_<column>` here so the exported file reads as
intended rather than looking like a bug.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .config import ENTITY_MAP_PATH, OUTPUT_DIR, PROCESSED_DATA_PATH, predictions_path

DEFAULT_OUT = OUTPUT_DIR / "linkage_matches.csv"

BANDS = ("match", "review", "non_match", "all")
DECISION_OF = {"match": "MATCH", "review": "REVIEW", "non_match": "NON_MATCH"}

# Both sides, so a reader can see the actual values without opening another file.
PAIR_FIELDS = [
    "first_name_std",
    "last_name_std",
    "email_std",
    "phone_std",
    "dob_std",
    "address_std",
    "city_std",
    "state_std",
    "country_std",
]


def device_sets() -> dict[str, frozenset]:
    """record_id -> its device ids, for the per-row truth check."""
    records = pd.read_parquet(
        PROCESSED_DATA_PATH, columns=["record_id", "device_ids_std"]
    )
    exploded = records.explode("device_ids_std").dropna(subset=["device_ids_std"])
    out: dict[str, frozenset] = {}
    for record_id, group in exploded.groupby("record_id"):
        out[record_id] = frozenset(
            str(v) for v in group["device_ids_std"] if str(v).strip()
        )
    return out


def build(band: str = "match") -> pd.DataFrame:
    preds_path = predictions_path(full=True)
    if not preds_path.exists():
        raise FileNotFoundError(
            f"{preds_path.name} not found. Run: python -m src.splink_model --full"
        )

    available = list(pd.read_parquet(preds_path).columns)
    if "decision" not in available:
        raise SystemExit(
            "Predictions have no 'decision' column. Re-run: python -m src.splink_model --full"
        )

    wanted = [
        "record_id_l",
        "record_id_r",
        "match_probability",
        "match_weight",
        "decision",
        *[c for c in available if c.startswith("gamma_")],
        *[f"{f}_{side}" for f in PAIR_FIELDS for side in ("l", "r")],
    ]
    preds = pd.read_parquet(preds_path, columns=[c for c in wanted if c in available])

    if band == "all":
        frame = preds
    else:
        frame = preds[preds["decision"] == DECISION_OF[band]]
    if frame.empty:
        raise SystemExit(f"No pairs with decision {DECISION_OF.get(band, band)} in this run.")

    frame = frame.rename(
        columns={c: c.replace("gamma_gamma_", "cmp_") for c in frame.columns if c.startswith("gamma_")}
    )

    records = pd.read_parquet(
        PROCESSED_DATA_PATH, columns=["record_id", "device_ids_std", "customer_id"]
    )
    devices = device_sets()
    for side in ("l", "r"):
        ids = frame[f"record_id_{side}"]
        frame[f"device_ids_std_{side}"] = [
            ";".join(sorted(devices.get(r, ()))) if r in devices else None for r in ids
        ]
        frame[f"customer_id_{side}"] = ids.map(records.set_index("record_id")["customer_id"])

    # None, not False: a record with no device id cannot be checked, and calling
    # that "no match" would read as evidence of a false merge.
    left_devices = frame["record_id_l"].map(devices)
    right_devices = frame["record_id_r"].map(devices)
    frame["device_match"] = [
        None if not a or not b else bool(a == b)
        for a, b in zip(left_devices, right_devices)
    ]

    if ENTITY_MAP_PATH.exists():
        lookup = pd.read_parquet(ENTITY_MAP_PATH).set_index("record_id")["entity_id"]
        for side in ("l", "r"):
            frame[f"entity_id_{side}"] = frame[f"record_id_{side}"].map(lookup)
        frame["same_entity"] = frame["entity_id_l"] == frame["entity_id_r"]
    else:
        for side in ("l", "r"):
            frame[f"entity_id_{side}"] = None
        frame["same_entity"] = None

    left, right = frame["record_id_l"].astype(str), frame["record_id_r"].astype(str)
    frame.insert(0, "pair_id", [f"{a}__{b}" for a, b in zip(map(min, zip(left, right)), map(max, zip(left, right)))])

    order = (
        [
            "pair_id", "record_id_l", "record_id_r",
            "match_probability", "match_weight", "decision",
        ]
        + [c for c in frame.columns if c.startswith("cmp_")]
        + [f"{f}_{side}" for f in PAIR_FIELDS for side in ("l", "r")]
        + [
            "device_ids_std_l", "device_ids_std_r", "device_match",
            "entity_id_l", "entity_id_r", "same_entity",
            "customer_id_l", "customer_id_r",
        ]
    )
    return frame[order].sort_values("match_probability", ascending=False).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export per-pair linkage evidence for a decision band."
    )
    parser.add_argument("--band", choices=list(BANDS), default="match")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    frame = build(args.band)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out, index=False)

    print(f"Band: {args.band} -> {len(frame):,} pairs")
    print(f"Decisions: {frame['decision'].value_counts().to_dict()}")
    if frame["device_match"].notna().any():
        checked = frame["device_match"].notna().sum()
        agree = int(frame["device_match"].fillna(False).sum())
        print(f"device_match: {agree:,}/{checked:,} checked pairs share a device id")
    if frame["same_entity"].notna().any():
        print(f"same_entity : {int(frame['same_entity'].sum()):,}/{len(frame):,} in one entity")
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
