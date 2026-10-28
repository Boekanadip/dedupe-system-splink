#!/usr/bin/env python3
"""Sample review pairs from review queue with optional filtering."""
import argparse
import random
import pandas as pd
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=str, default="review_sample.csv")
    args = parser.parse_args()

    q = pd.read_csv("data/labels/review_queue.csv")
    random.seed(args.seed)
    if len(q) <= args.n:
        sample = q
    else:
        sample = q.sample(n=args.n, random_state=args.seed)
    sample.to_csv(args.output, index=False)
    print(f"Written {len(sample)} pairs to {args.output}")

if __name__ == "__main__":
    main()
