from __future__ import annotations

import argparse
import time

import duckdb
import pandas as pd

from .config import BENCHMARK_RULES, OUTPUT_DIR, PROCESSED_DATA_PATH, SMOKE_SAMPLE_SIZE
from .eval_truth import device_truth_pairs, pairs_sql
from .labels import load_labels

OUTPUT_PATH = OUTPUT_DIR / "blocking_benchmark.csv"

# Starter rules only. Equi-join keys: fuzzy similarity belongs after candidate
# generation (DESIGN.md), so it is never used here for blocking.
RULES = BENCHMARK_RULES


def load_data(full: bool = False) -> pd.DataFrame:
    if not PROCESSED_DATA_PATH.exists():
        raise FileNotFoundError(
            "Standardized parquet belum ada. Jalankan: python -m src.standardize"
        )
    df = pd.read_parquet(PROCESSED_DATA_PATH)
    if not full and len(df) > SMOKE_SAMPLE_SIZE:
        df = df.head(SMOKE_SAMPLE_SIZE).copy()
    return df


def block_stats(con: duckdb.DuckDBPyConnection, cols: list[str]) -> dict:
    """Skew: how big is the largest block, and which value created it.

    Null keys are excluded because an equi-join never matches them, so they
    would not generate candidates either.
    """
    keys = ", ".join(f'"{c}"' for c in cols)
    not_null = " AND ".join(f'"{c}" IS NOT NULL' for c in cols)
    block_count, largest_rows = con.execute(
        f"""
        SELECT COUNT(*), COALESCE(MAX(n), 0)
        FROM (SELECT COUNT(*) AS n FROM src WHERE {not_null} GROUP BY {keys})
        """
    ).fetchone()
    top = con.execute(
        f"""
        SELECT {keys}, COUNT(*) AS n
        FROM src
        WHERE {not_null}
        GROUP BY ALL
        ORDER BY n DESC
        LIMIT 1
        """
    ).fetchone()
    return {
        "block_count": int(block_count),
        "largest_block_rows": int(largest_rows),
        "largest_block_value": "" if top is None else " | ".join(str(v) for v in top[:-1]),
    }


def coverage(
    pairs: pd.DataFrame, positives: pd.DataFrame, frame: pd.DataFrame
) -> tuple[int | None, float | None]:
    if positives.empty:
        return None, None
    # Labels are built on the full dataset but this run may benchmark a sample.
    # Dividing by positives outside the sample would report fake low coverage.
    present = set(frame["record_id"])
    in_scope = positives[
        positives["record_id_l"].isin(present) & positives["record_id_r"].isin(present)
    ]
    if in_scope.empty:
        return None, None
    kept = pairs.merge(in_scope, on=["record_id_l", "record_id_r"], how="inner")
    return len(kept), round(len(kept) / len(in_scope) * 100, 3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark blocking rules.")
    parser.add_argument(
        "--full",
        action="store_true",
        help=f"Use all rows instead of the {SMOKE_SAMPLE_SIZE} sample.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Explicitly run on the smoke sample. This is the default.",
    )
    args = parser.parse_args()

    started = time.perf_counter()
    df = load_data(args.full)
    print(f"Input rows: {len(df):,}")

    labels, label_source = load_labels()
    positives = (
        pd.DataFrame(columns=["record_id_l", "record_id_r"])
        if labels is None
        else labels[labels["is_positive"]]
    )
    if labels is None:
        print("Labels: none found -> coverage TIDAK dihitung")
    else:
        # Never let silver read as gold: gold is measured, silver is not reviewed.
        tag = "GOLD" if label_source == "gold" else "SILVER (belum direview)"
        print(f"Labels: {label_source} [{tag}] {len(labels):,} pasang, {len(positives):,} positif")
        present = set(df["record_id"])
        in_scope = int(
            (positives["record_id_l"].isin(present) & positives["record_id_r"].isin(present)).sum()
        )
        print(
            f"Coverage denominator: {in_scope:,} of {len(positives):,} positives "
            f"both records inside this run's {len(df):,} rows"
        )

    con = duckdb.connect()
    con.register("src", df)

    # Device-truth coverage is the non-tautological counterpart of `coverage_pct`.
    # `coverage_pct` divides by silver positives, which are defined on phone+dob —
    # the same fields phone_exact and dob_exact block on, so 100% there is
    # guaranteed arithmetic. No rule blocks on device_id, so this column carries
    # real information about what each rule actually reaches.
    con.register("truth", device_truth_pairs(df))
    truth_total = con.execute("SELECT COUNT(*) FROM truth").fetchone()[0]

    def device_truth_coverage(pairs: pd.DataFrame) -> tuple[int, float | None]:
        if not truth_total:
            return 0, None
        con.register("pairs_temp", pairs)
        kept = con.execute(
            """
            SELECT COUNT(*) FROM truth t
            WHERE EXISTS (
                SELECT 1 FROM pairs_temp p
                WHERE p.record_id_l = t.record_id_l AND p.record_id_r = t.record_id_r
            )
            """
        ).fetchone()[0]
        con.unregister("pairs_temp")
        return kept, round(100.0 * kept / truth_total, 3)

    print(f"Device-truth pairs (denominator for the non-tautological column): {truth_total:,}")

    rows: list[dict] = []
    rule_pairs: dict[str, pd.DataFrame] = {}
    for name, cols in RULES:
        rule_start = time.perf_counter()
        pairs = con.execute(pairs_sql(cols)).fetchdf()
        stats = block_stats(con, cols)
        seconds = time.perf_counter() - rule_start

        largest = stats["largest_block_rows"]
        largest_pairs = largest * (largest - 1) // 2
        share = round(largest_pairs / len(pairs) * 100, 3) if len(pairs) else 0.0
        covered, cov_pct = coverage(pairs, positives, df)
        truth_kept, truth_pct = device_truth_coverage(pairs)

        rule_pairs[name] = pairs
        rows.append(
            {
                "rule": name,
                "key_columns": "+".join(cols),
                "candidate_pairs": len(pairs),
                "runtime_seconds": round(seconds, 3),
                "block_count": stats["block_count"],
                "largest_block_rows": largest,
                "largest_block_pairs": largest_pairs,
                "largest_block_share_pct": share,
                "largest_block_value": stats["largest_block_value"],
                "covered_positives": covered,
                "coverage_pct": cov_pct,
                "device_truth_covered": truth_kept,
                "device_truth_coverage_pct": truth_pct,
            }
        )
        print(
            f"{name:14s} pairs={len(pairs):8,d} runtime={seconds:6.2f}s "
            f"blocks={stats['block_count']:7,d} largest={largest:6,d} ({share:6.2f}%)"
            + (f" coverage={cov_pct}%" if cov_pct is not None else "")
        )

    union_start = time.perf_counter()
    union_pairs = (
        pd.concat(list(rule_pairs.values()), ignore_index=True)
        .drop_duplicates()
        .reset_index(drop=True)
    )
    union_seconds = time.perf_counter() - union_start
    covered, cov_pct = coverage(union_pairs, positives, df)
    truth_kept, truth_pct = device_truth_coverage(union_pairs)
    print(
        f"{'UNION':14s} pairs={len(union_pairs):8,d} runtime={union_seconds:6.2f}s "
        "candidate set = union of all rules, deduplicated"
        + (f" coverage={cov_pct}%" if cov_pct is not None else "")
    )
    rows.append(
        {
            "rule": "__union__",
            "key_columns": "all",
            "candidate_pairs": len(union_pairs),
            "runtime_seconds": round(union_seconds, 3),
            "block_count": None,
            "largest_block_rows": None,
            "largest_block_pairs": None,
            "largest_block_share_pct": None,
            "largest_block_value": None,
            "covered_positives": covered,
            "coverage_pct": cov_pct,
            "device_truth_covered": truth_kept,
            "device_truth_coverage_pct": truth_pct,
        }
    )

    out = pd.DataFrame(rows)
    # Record which labels coverage was measured against, so the CSV cannot be
    # re-read later as if it came from a reviewed gold set.
    out["label_source"] = label_source
    # Both denominators in one file, so a reader cannot mistake the tautological
    # coverage_pct (silver positives == blocking key fields) for a real recall.
    out["truth_source"] = "device_ids_std (1:1 with customer_id on this dataset — upper bound)"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_PATH, index=False)

    print(f"Output rows: {len(out):,}")
    print(f"Union candidate pairs: {len(union_pairs):,}")
    print(f"Total runtime: {time.perf_counter() - started:.2f}s")
    print(f"Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
