"""Apply human gold labels to the decision column (FR-09: label -> hasil akhir).

Pipeline standalone hanya memutuskan dari threshold. Setelah manusia promote
label ke gold, pasangan REVIEW yang ditandai match tidak pernah masuk entity —
modul ini menutup jalur itu:

  gold match    + decision != MATCH     -> MATCH     (persetujuan manusia)
  gold no_match + decision == REVIEW    -> NON_MATCH (manusia menutup kasus)
  gold no_match + decision == MATCH     -> TIDAK diturunkan otomatis: itu
      berarti manusia menolak keputusan di atas threshold, yang akan melanggar
      invariant smoke test (P >= threshold => MATCH). Dilaporkan sebagai
      konflik model-manusia untuk retrain / peninjauan threshold.

Guard per pasangan (override manusia DITOLAK, bukan dipaksa):
  * device conflict — kedua sisi punya device id DAN beda. Menambah pasangan
    ini ke satu entity membuat entity mencampur dua device id (jawaban kunci
    dataset ini) dan smoke test gagal. Pasangan seperti ini dilaporkan.
  * Nothing else is silently changed: kolom match_probability TIDAK disentuh.

Setiap penerapan dicatat ke outputs/human_overrides.jsonl (pair, keputusan
lama, label, waktu, model_version) — audit trail untuk halaman riwayat.

Run:
    python -m src.apply_gold                 # dry-run (cetak rencana)
    python -m src.apply_gold --apply         # tulis keputusan
    python -m src.apply_gold --apply --recluster   # lalu clustering+master+evaluate
"""
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


def plan() -> pd.DataFrame:
    """One row per gold pair that would change, with the guard verdict."""
    labels, src = load_labels()
    if labels is None or src != "gold":
        raise SystemExit("No gold labels. Promote first: python -m src.labels --promote")

    preds = pd.read_parquet(
        predictions_path(full=True),
        columns=["record_id_l", "record_id_r", "match_probability", "decision"],
    )
    merged = preds.merge(
        labels.rename(columns={"is_positive": "gold_match"}),
        on=["record_id_l", "record_id_r"],
        how="inner",
    )
    records = pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id", "device_ids_std"])
    dev = device_sets(records)

    rows = []
    for _, r in merged.iterrows():
        want = "MATCH" if r["gold_match"] else "NON_MATCH"
        if r["decision"] == want:
            continue
        reason = ""
        blocked = False
        if not r["gold_match"] and r["match_probability"] >= MATCH_THRESHOLD:
            # Downgrading here would break P >= threshold => MATCH (smoke test).
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
                "decision_now": r["decision"],
                "decision_after": want,
                "match_probability": float(r["match_probability"]),
                "gold": "match" if r["gold_match"] else "no_match",
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
    key = preds.set_index(["record_id_l", "record_id_r"])
    changed = 0
    for _, r in ok.iterrows():
        key.loc[(r["record_id_l"], r["record_id_r"]), "decision"] = r["decision_after"]
        changed += 1
    out = key.reset_index()
    # Preserve column order: set_index/reset_index round-trips, but older
    # artifacts may have carried extra columns — order is not semantically
    # important, only the decision column changes.
    out.to_parquet(path, index=False)

    meta = read_meta(path)
    meta["human_overrides"] = int(meta.get("human_overrides", 0)) + changed
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
    print(f"Applied {changed:,} decision override(s). Audit: {OVERRIDES_PATH.name}")
    return changed


def recluster() -> None:
    """clustering -> master -> evaluate, urutan yang sama dengan run_all."""
    for module, extra in (("clustering", ["--full"]), ("master_record", []), ("evaluate", [])):
        cmd = [sys.executable, "-m", f"src.{module}", *extra]
        print(f"  running: {' '.join(cmd[2:])}")
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode != 0:
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            raise SystemExit(f"Step {module!r} failed")
        tail = [ln for ln in result.stdout.splitlines() if ln.strip()][-3:]
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
