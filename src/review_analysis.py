#!/usr/bin/env python3
"""Analyze a review sample CSV for false negatives using gold labels."""
import argparse
import pandas as pd
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, default="review_sample.csv")
    parser.add_argument("--gold", type=str, default="data/labels/gold_labels.csv")
    args = parser.parse_args()

    sample = pd.read_csv(args.input)
    gold = pd.read_csv(args.gold)

    gt_matches = gold[gold["label"] == "match"].copy()
    gt_matches["pair_id"] = gt_matches["record_id_l"].astype(str).str.cat(gt_matches["record_id_r"].astype(str), sep="_")
    gt_match_ids = set(gt_matches["pair_id"])

    sample["pair_id"] = sample["record_id_l"].str.cat(sample["record_id_r"].astype(str), sep="_")
    sample["is_gt_match"] = sample["pair_id"].isin(gt_match_ids)
    sample["is_gt_match"] = sample["is_gt_match"].fillna(False)

    M_ELSE_LEVEL_FLOOR = 0.05

    sample["else_bucket"] = sample["match_probability"] < M_ELSE_LEVEL_FLOOR

    print(f"Match probability distribution:")
    print(sample["match_probability"].describe())
    print(f"\nPercentiles 0-10%:")
    print(sample["match_probability"].quantile([0.0, 0.01, 0.025, 0.05, 0.1]))
    print(f"\nGT match prob distribution:")
    print(sample[sample["is_gt_match"]]["match_probability"].describe())

if __name__ == "__main__":
    main()
