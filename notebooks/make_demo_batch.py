"""Build a demo upload out of rows that already exist in data/raw/.

Why generated this way: a brand new CSV has no known partner, so "did the
pipeline link it correctly" cannot be answered. Every generated row is a copy
of an existing record (same customer_id, same device id), so the correct
outcome is known in advance and can be checked instead of guessed.

100 of the 1,000 rows get documented character-level typos, so fuzzy linking
is exercised rather than assumed.

    python notebooks/make_demo_batch.py
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data" / "raw" / "batch_0002.csv"
DEST = PROJECT_ROOT / "data" / "raw" / "batch_0003.csv"

ROWS = 1000
TYPO_ROWS = 100
SEED = 42
TYPO_COLUMNS = ["first_name", "last_name", "email"]


def typo(value, rng: random.Random) -> str | None:
    """One character-level corruption: swap, drop, or duplicate a letter."""
    if not isinstance(value, str) or len(value) < 4:
        return None
    kind = rng.choice(("swap", "drop", "double"))
    i = rng.randrange(1, len(value) - 1)
    if kind == "swap":
        return value[:i] + value[i + 1] + value[i] + value[i + 2:]
    if kind == "drop":
        return value[:i] + value[i + 1:]
    return value[:i] + value[i] + value[i:]


def main() -> None:
    rng = random.Random(SEED)
    frame = pd.read_csv(SOURCE, sep=";", low_memory=False)
    # One record per customer_id, or the demo itself carries a known duplicate.
    owners = frame.drop_duplicates(subset=["customer_id"])
    sample = owners.sample(n=ROWS, random_state=SEED).reset_index(drop=True)

    damaged = 0
    for index in sample.index[:TYPO_ROWS]:
        for column in TYPO_COLUMNS:
            corrupted = typo(sample.at[index, column], rng)
            if corrupted is not None:
                sample.at[index, column] = corrupted
                damaged += 1

    sample.to_csv(DEST, sep=";", index=False, encoding="utf-8")
    print(f"{SOURCE.name} -> {DEST.name}: {len(sample):,} rows")
    print(f"exact copies: {len(sample) - TYPO_ROWS:,} | rows carrying a typo: {TYPO_ROWS:,}")
    print(f"field values corrupted: {damaged}")
    print(f"rows: {ROWS:,} | seed: {SEED}")


if __name__ == "__main__":
    main()