from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import model_lifecycle
from .config import (
    ENTITY_MAP_PATH,
    MATCH_THRESHOLD,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    predictions_path,
    read_meta,
    write_meta,
)
from .labels import GOLD_PATH, load_labels

OVERRIDES_PATH = OUTPUT_DIR / "human_overrides.jsonl"


def device_sets(records: pd.DataFrame) -> dict[str, frozenset]:
    ids = (
        records[["record_id", "device_ids_std"]]
        .explode("device_ids_std")
        .dropna(subset=["device_ids_std"])
    )
    return ids.groupby("record_id")["device_ids_std"].apply(frozenset).to_dict()

def _pair_keys(frame: pd.DataFrame) -> pd.Series:
    """Unordered pair key so (a,b) and (b,a) map to the same label."""
    left = frame["record_id_l"].astype(str)
    right = frame["record_id_r"].astype(str)
    return left.where(left <= right, right) + "|" + right.where(left <= right, left)


def plan() -> pd.DataFrame:
    labels, src = load_labels()
    if labels is None or src != "gold":
        raise SystemExit("No gold labels. Promote first: python -m src.labels --promote")

    preds = pd.read_parquet(
        predictions_path(full=True),
        columns=["record_id_l", "record_id_r", "match_probability", "decision"],
    )
    preds = preds.assign(_key=_pair_keys(preds)).drop_duplicates("_key", keep="first")
    lookup = preds.set_index("_key")[["record_id_l", "record_id_r", "match_probability", "decision"]]

    labels = labels.rename(columns={"is_positive": "gold_match"}).assign(
        _key=_pair_keys(labels)
    )
    records = pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id", "device_ids_std"])
    available = set(records["record_id"].astype(str))
    before = len(labels)
    labels = labels[
        labels["record_id_l"].astype(str).isin(available)
        & labels["record_id_r"].astype(str).isin(available)
    ].copy()
    skipped = before - len(labels)
    if skipped:
        print(
            f"Melewati {skipped:,} label gold yang record-nya tidak ada di data standar "
            f"({len(available):,} record tersedia)."
        )

    # Load manual override pairs (optional)
    OVERRIDE_PATH = OUTPUT_DIR / "override_pairs.csv"
    overrides = {}
    if OVERRIDE_PATH.exists():
        ov = pd.read_csv(OVERRIDE_PATH, dtype=str).dropna()
        if {"record_id_l", "record_id_r", "decision"}.issubset(ov.columns):
            for _, row in ov.iterrows():
                key = (row["record_id_l"].strip(), row["record_id_r"].strip())
                overrides[key] = row["decision"].strip().upper()
            print(f"Loaded {len(overrides)} manual override pair(s) from {OVERRIDE_PATH.name}")

    dev = device_sets(records)

    rows = []
    for _, r in labels.iterrows():
        want = "MATCH" if r["gold_match"] else "NON_MATCH"
        if r["_key"] in lookup.index:
            hit = lookup.loc[r["_key"]]
            current = hit["decision"]
            probability = float(hit["match_probability"])
            exists = True
        else:
            current = "ABSENT"
            probability = float("nan")
            exists = False

        if exists and current == want:
            continue
        if not exists and want == "NON_MATCH":
            # Pasangan non-match yang tidak pernah jadi kandidat tidak menambah edge.
            continue

        reason = ""
        blocked = False
        # Check manual override
        pair_key = (str(r["record_id_l"]), str(r["record_id_r"]))
        if pair_key in overrides:
            blocked = False
            want = overrides[pair_key]  # Force decision from override
        else:
            if exists and not r["gold_match"] and probability >= MATCH_THRESHOLD:
                # P >= threshold => MATCH (uji asap).
                blocked = True
                reason = "konflik: gold no_match tapi P >= threshold — perlu retrain/threshold review"
            elif r["gold_match"]:
                dl, dr = dev.get(r["record_id_l"], frozenset()), dev.get(r["record_id_r"], frozenset())
                if dl and dr and dl != dr:
                    blocked = True
                    reason = "device conflict: kedua sisi punya device id berbeda (jawaban kunci dataset)"

        rows.append(
            {
                "record_id_l": r["record_id_l"],
                "record_id_r": r["record_id_r"],
                "decision_now": current,
                "decision_after": want,
                "match_probability": probability,
                "gold": "match" if r["gold_match"] else "no_match",
                "exists": exists,
                "blocked": blocked,
                "blocked_reason": reason,
            }
        )
    return pd.DataFrame(rows)


def apply_changes(plan_df: pd.DataFrame) -> int:
    ok = plan_df[~plan_df["blocked"]]
    if ok.empty:
        print("Nothing to apply.")
        return 0

    path = predictions_path(full=True)
    preds = pd.read_parquet(path)
    preds = preds.assign(_key=_pair_keys(preds))

    existing = ok[ok["exists"]]
    if not existing.empty:
        decisions = existing.set_index("_key")["decision_after"]
        mask = preds["_key"].isin(decisions.index)
        preds.loc[mask, "decision"] = preds.loc[mask, "_key"].map(decisions)

    missing = ok[~ok["exists"]]
    if not missing.empty:
        fresh = pd.DataFrame(
            {
                "record_id_l": missing["record_id_l"].values,
                "record_id_r": missing["record_id_r"].values,
                "_key": missing["_key"].values if "_key" in missing.columns else _pair_keys(missing).values,
                "decision": missing["decision_after"].values,
                "match_probability": [
                    1.0 if d == "MATCH" else 0.0 for d in missing["decision_after"]
                ],
            }
        )
        for column in preds.columns:
            if column not in fresh.columns:
                fresh[column] = None
        fresh = fresh[preds.columns]
        preds = pd.concat([preds, fresh], ignore_index=True)

    preds = preds.drop(columns=["_key"], errors="ignore")
    preds.to_parquet(path, index=False)

    meta = read_meta(path)
    meta["human_overrides"] = int(meta.get("human_overrides", 0)) + len(ok)
    meta["human_overrides_last_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_meta(path, **meta)

    version = model_lifecycle.latest()
    with open(OVERRIDES_PATH, "a", encoding="utf-8") as handle:
        for _, r in ok.iterrows():
            handle.write(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "record_id_l": r["record_id_l"],
                        "record_id_r": r["record_id_r"],
                        "decision_before": r["decision_now"],
                        "decision_after": r["decision_after"],
                        "match_probability": r["match_probability"],
                        "gold_label": r["gold"],
                        "model_version": version.name if version else None,
                        "source": "apply_gold",
                    }
                )
                + "\n"
            )
    print(
        f"Applied {len(ok):,} gold override(s) "
        f"({len(existing):,} existing pair, {len(missing):,} added). "
        f"Audit: {OVERRIDES_PATH.name}"
    )
    return len(ok)


def recluster() -> None:
    """clustering -> master -> evaluate, urutan yang sama dengan run_all."""
    for module, extra in (("clustering", ["--full"]), ("master_record", []), ("evaluate", [])):
        cmd = [sys.executable, "-m", f"src.{module}", *extra]
        print(f"  running: {' '.join(cmd[2:])}")
        result = subprocess.run(
            cmd, text=True, capture_output=True, encoding="utf-8", errors="replace"
        )
        if result.returncode != 0:
            sys.stdout.write(result.stdout or "")
            sys.stderr.write(result.stderr or "")
            raise SystemExit(f"Step {module!r} failed")
        tail = [ln for ln in (result.stdout or "").splitlines() if ln.strip()][-3:]
        for line in tail:
            print(f"    {line}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply reviewed gold labels to decisions.")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run).")
    parser.add_argument("--recluster", action="store_true", help="Re-run clustering/master/evaluate after --apply.")
    args = parser.parse_args()

    plan_df = plan()
    if plan_df.empty:
        print("Gold labels already agree with every decision. Nothing to do.")
        return

    applyable = plan_df[~plan_df["blocked"]]
    blocked = plan_df[plan_df["blocked"]]
    print(f"Gold-vs-decision differences: {len(plan_df):,}")
    print(f"  applyable : {len(applyable):,}")
    print(f"  blocked   : {len(blocked):,}")
    if not blocked.empty:
        print("\nBLOCKED (needs a human decision, not auto-applied):")
        for _, r in blocked.iterrows():
            print(
                f"  {r['record_id_l']} x {r['record_id_r']}  {r['decision_now']} -> "
                f"{r['decision_after']}  gold={r['gold']}  {r['blocked_reason']}"
            )
    if not applyable.empty:
        print("\nAPPLYABLE:")
        print(
            applyable[["record_id_l", "record_id_r", "decision_now", "decision_after", "gold"]]
            .to_string(index=False)
        )

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write.")
        return

    changed = apply_changes(plan_df)
    if changed and args.recluster:
        print("Re-clustering with human decisions...")
        recluster()
        print("Done. Refresh evaluation numbers: python -m src.evaluate")
    elif changed:
        print("Next: python -m src.clustering --full && python -m src.master_record && python -m src.evaluate")


if __name__ == "__main__":
    main()
