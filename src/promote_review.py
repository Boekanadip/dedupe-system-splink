#!/usr/bin/env python3
"""Promote review pairs to gold labels."""
import pandas as pd
from pathlib import Path

def main():
    # Load sample and gold labels
    sample = pd.read_csv("review_sample_band.csv")
    existing_gold = pd.read_csv("data/labels/gold_labels.csv")

    # Ground truth matches from existing gold
    gt_matches = existing_gold[existing_gold["label"] == "match"].copy()
    gt_matches["pair_id"] = gt_matches["record_id_l"].astype(str).str.cat(
        gt_matches["record_id_r"].astype(str), sep="_"
    )
    gt_match_ids = set(gt_matches["pair_id"])

    # Check which sample pairs are GT matches
    sample["pair_id"] = sample["record_id_l"].astype(str).str.cat(
        sample["record_id_r"].astype(str), sep="_"
    )
    sample["is_gt_match"] = sample["pair_id"].isin(gt_match_ids)
    sample["is_gt_match"] = sample["is_gt_match"].fillna(False)

    n_gt_match = int(sample["is_gt_match"].sum())
    n_gt_nonmatch = len(sample) - n_gt_match

    print(f"Sample: {len(sample)} pairs")
    print(f"GT matches in sample: {n_gt_match}")
    print(f"GT non-matches in sample: {n_gt_nonmatch}")

    # Show match probability stats
    gt_match_probs = sample[sample["is_gt_match"]]["match_probability"]
    gt_nonmatch_probs = sample[~sample["is_gt_match"]]["match_probability"]

    print(f"\nGT match prob stats: mean={gt_match_probs.mean():.4f}, min={gt_match_probs.min():.4f}")
    print(f"GT non-match prob stats: mean={gt_nonmatch_probs.mean():.4f}, min={gt_nonmatch_probs.min():.4f}")

    # Promote GT matches from review queue to gold_labels
    promoted_matches = sample[sample["is_gt_match"]].copy()
    promoted_matches["label"] = "match"
    promoted_matches["stratum"] = "promoted_from_review"

    # Also add GT non-matches for balance
    promoted_nonmatches = sample[~sample["is_gt_match"]].copy()
    promoted_nonmatches["label"] = "no_match"
    promoted_nonmatches["stratum"] = "promoted_from_review"

    # Load existing gold and append
    new_gold = pd.concat([existing_gold, promoted_matches, promoted_nonmatches], ignore_index=True)

    # Remove duplicates based on pair
    new_gold["pair_id"] = new_gold["record_id_l"].astype(str).str.cat(
        new_gold["record_id_r"].astype(str), sep="_"
    )
    new_gold = new_gold.drop_duplicates(subset="pair_id", keep="first")

    # Save updated gold labels
    output_path = "data/labels/gold_labels_upgraded.csv"
    new_gold.to_csv(output_path, index=False)

    # Also remove promoted pairs from review queue
    queue = pd.read_csv("data/labels/review_queue.csv")
    queue["pair_id"] = queue["record_id_l"].astype(str).str.cat(
        queue["record_id_r"].astype(str), sep="_"
    )
    remaining_queue = queue[~queue["pair_id"].isin(new_gold["pair_id"])]
    remaining_queue.to_csv("data/labels/review_queue.csv", index=False)

    print(f"\nNew gold labels saved: {output_path}")
    print(f"Total gold pairs now: {len(new_gold)} (was {len(existing_gold)})")
    print(f"  Positive: {len(new_gold[new_gold['label'] == 'match'])} (was {len(existing_gold[existing_gold['label'] == 'match'])})")
    print(f"  Negative: {len(new_gold[new_gold['label'] == 'no_match'])} (was {len(existing_gold[existing_gold['label'] == 'no_match'])})")

    print(f"\nReview queue now: {len(remaining_queue)} pairs (was {len(queue)})")

    print(f"\nPromoted from review:")
    print(f"  Matches promoted: {len(promoted_matches)}")
    print(f"  Non-matches promoted: {len(promoted_nonmatches)}")

    print("\n--- Ready to re-run threshold evaluation ---")
    print("Run: python -m src.threshold_eval --source gold --full")

if __name__ == "__main__":
    main()
