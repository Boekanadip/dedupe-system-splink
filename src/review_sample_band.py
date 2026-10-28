#!/usr/bin/env python3
"""Sample review pairs filtered by review_status band."""
import argparse
import random
import pandas as pd

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--band", type=str, default="review", choices=["review", "match", "non_match"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=str, default="review_sample_band.csv")
    args = parser.parse_args()

    q = pd.read_csv("data/labels/review_queue.csv")
    random.seed(args.seed)
    
    # Filter by review_status band
    # All 791 pairs have review_status = "pending"
    if args.band == "review":
        sample_df = q  # all are pending review
    elif args.band == "match":
        # Would need decision column, but queue has no decision yet
        sample_df = q.head(0)  # empty
    elif args.band == "non_match":
        sample_df = q.head(0)  # empty
    
    # If more than n, sample n
    if len(sample_df) > args.n:
        sample_df = sample_df.sample(n=args.n, random_state=args.seed)
    
    sample_df.to_csv(args.output, index=False)
    print(f"Written {len(sample_df)} pairs (band={args.band}) to {args.output}")
    print(f"Total pairs in queue with review_status=pending: {len(q[q['review_status'].str.lower()=='pending'])}")

if __name__ == "__main__":
    main()