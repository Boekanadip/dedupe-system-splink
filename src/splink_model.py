from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import splink
from splink import DuckDBAPI, Linker, SettingsCreator, block_on
import splink.comparison_library as cl

from . import model_lifecycle
from .config import (
    BENCHMARK_RULES,
    LAMBDA_RECALL_ASSUMPTION,
    MATCH_THRESHOLD,
    M_ELSE_LEVEL_FLOOR,
    PROCESSED_DATA_PATH,
    RANDOM_SEED,
    REVIEW_THRESHOLD,
    SMOKE_SAMPLE_SIZE,
    predictions_path,
    scope_of,
    write_meta,
)

DETERMINISTIC_RULES = [
    block_on("email_std"),
    block_on("phone_std"),
]

TRAINING_RULES = [(name, block_on(*cols)) for name, cols in BENCHMARK_RULES]


def load_data(full: bool = False) -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DATA_PATH)
    if not full and len(df) > SMOKE_SAMPLE_SIZE:
        df = df.head(SMOKE_SAMPLE_SIZE).copy()
    return df


def pin_else_level(comparison, output_column_name: str, floor: float):
    """Rebuild a comparison with its "all other" level's m pinned to `floor`.

    Without this the level is trained to ~0 and clamped by Splink, which is what
    collapsed every non-match onto one identical score. Rebuilt through
    CustomComparison because mutating the objects returned by
    `create_comparison_levels()` has no effect — they are rebuilt per call.
    """
    levels = comparison.create_comparison_levels()
    levels[-1].configure(m_probability=floor, fix_m_probability=True)
    return cl.CustomComparison(comparison_levels=levels, output_column_name=output_column_name)


def build_settings():
    # (creator, output column, term-frequency adjustment?)
    specs = [
        (cl.NameComparison("first_name_std"), "gamma_first_name_std", False),
        (cl.NameComparison("last_name_std"), "gamma_last_name_std", False),
        (cl.EmailComparison("email_std"), "gamma_email_std", False),
        (
            cl.JaroWinklerAtThresholds("address_std", [0.95, 0.90, 0.80]),
            "gamma_address_std",
            False,
        ),
        (cl.ExactMatch("city_std"), "gamma_city_std", True),
        (cl.ExactMatch("state_std"), "gamma_state_std", True),
        (cl.ExactMatch("country_std"), "gamma_country_std", True),
        (
            cl.DateOfBirthComparison("dob_std", input_is_string=True),
            "gamma_dob_std",
            False,
        ),
        (cl.ExactMatch("phone_std"), "gamma_phone_std", False),
    ]

    comparisons = []
    for creator, output_column, term_frequency in specs:
        if M_ELSE_LEVEL_FLOOR is None:
            comparison = creator
        else:
            comparison = pin_else_level(creator, output_column, M_ELSE_LEVEL_FLOOR)
        # TF adjustments must be re-applied after the rebuild, so this branch is
        # written once for both paths rather than duplicated.
        if term_frequency:
            comparison = comparison.configure(term_frequency_adjustments=True)
        comparisons.append(comparison)

    if M_ELSE_LEVEL_FLOOR is not None:
        print(f"Pinned 'all other' level m = {M_ELSE_LEVEL_FLOOR} on {len(comparisons)} comparisons")

    # Prediction blocking is the benchmarked union: a rule set chosen without
    # measurement would mean scoring pairs nobody has costed.
    prediction_blocks = [block_on(*cols) for _, cols in BENCHMARK_RULES]

    return SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name="record_id",
        comparisons=comparisons,
        blocking_rules_to_generate_predictions=prediction_blocks,
    )


def add_decision(pred_df: pd.DataFrame) -> pd.DataFrame:
    """Three-way policy (PRD §7). One column, one place to read it.

    MATCH above the evaluated threshold, REVIEW in between, NON_MATCH below. The
    clustering step takes MATCH only, so everything in the REVIEW band is a pair a
    human must look at — it is deliberately NOT merged.
    """
    out = pred_df.copy()
    out["decision"] = "NON_MATCH"
    out.loc[out["match_probability"] >= REVIEW_THRESHOLD, "decision"] = "REVIEW"
    out.loc[out["match_probability"] >= MATCH_THRESHOLD, "decision"] = "MATCH"
    return out


def train_and_predict(
    df: pd.DataFrame,
    verbose: bool = True,
    model: dict | None = None,
) -> tuple[pd.DataFrame, object]:
    """Score every benchmarked candidate pair, training first unless a model is given.

    Returns (predictions, linker) so the caller can persist a freshly trained
    model without a second training pass.

    `model` is a saved Splink model dict. Passing one skips all EM training
    (MASTER_CONTEXT section 15: the model is not retrained every time a new CSV
    arrives). The returned linker has no trained parameters of its own, so
    save_model_to_json on it would write an untrained model — callers must only
    persist the linker from a training run.

    Extracted so src/stress_test.py scores corrupted data through the exact same
    model configuration. A second, hand-written training path there could
    silently drift from the production one and report a recovery rate for a
    pipeline that does not exist.
    """
    if model is not None:
        linker = Linker(df, model, db_api=DuckDBAPI())
        if verbose:
            print("Loaded saved model — skipping EM training (MC section 15).")
        return add_decision(linker.inference.predict().as_pandas_dataframe()), linker

    linker = Linker(df, build_settings(), db_api=DuckDBAPI())

    # NOTE: Splink 4.0.17's EM signature has no max_pairs; the training sample
    # size is determined by the training blocking rule itself.
    # max_pairs=1e8 is Splink's own recommendation to avoid a too-small u sample.
    # On a 10k sample it clamps to a full census, i.e. exact u probabilities.
    if verbose:
        print("Estimating model parameters with EM...")
    # Left at the default 1e-4, which is far too low for this data: it made every
    # non-match collapse to probability 1e-300. Estimate it from the deterministic
    # rules instead. The recall divisor is an assumption, see LAMBDA_RECALL_ASSUMPTION.
    linker.training.estimate_probability_two_random_records_match(
        DETERMINISTIC_RULES, recall=LAMBDA_RECALL_ASSUMPTION
    )
    linker.training.estimate_u_using_random_sampling(max_pairs=100_000_000, seed=RANDOM_SEED)

    # EM does not estimate the comparisons used in its own blocking rule, so a
    # single rule leaves those m values untrained. Run every benchmarked rule so
    # each comparison is trained by all the others.
    for name, rule in TRAINING_RULES:
        if verbose:
            print(f"EM on {name}")
        linker.training.estimate_parameters_using_expectation_maximisation(rule)

    pred_df = add_decision(linker.inference.predict().as_pandas_dataframe())
    return pred_df, linker


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Splink and score candidate pairs.")
    parser.add_argument(
        "--full",
        action="store_true",
        help=f"Train and predict on every row, not the {SMOKE_SAMPLE_SIZE} sample.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Explicitly run on the smoke sample. This is the default.",
    )
    parser.add_argument(
        "--reuse-model",
        metavar="PATH",
        default=None,
        help=(
            "Score using a saved model version instead of retraining (MASTER_CONTEXT "
            "section 15). Accepts a models/v... directory, a model.json path, or "
            "'latest' for the newest saved version."
        ),
    )
    args = parser.parse_args()

    started = time.perf_counter()
    df = load_data(full=args.full)

    saved = None
    reused_from = None
    if args.reuse_model == "latest":
        latest = model_lifecycle.latest()
        if latest is None:
            raise SystemExit(
                "No saved model version found. Train one first, or drop --reuse-model."
            )
        saved = model_lifecycle.load_model_json(latest)
        reused_from = latest.name
        print(f"Reusing model version: {latest.name}")
    elif args.reuse_model:
        saved = model_lifecycle.load_model_json(args.reuse_model)
        given = Path(args.reuse_model)
        # A reuse run must still say WHICH model scored it: a null model_version
        # made evaluate/dashboard report "n/a" for the artifact that produced the
        # current entity_map.
        reused_from = given.name if given.is_dir() else given.parent.name

    pred_df, linker = train_and_predict(df, model=saved)
    out_path = predictions_path(full=args.full)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pred_df.to_parquet(out_path, index=False)

    runtime = round(time.perf_counter() - started, 2)
    meta_extra = {
        "input_rows": len(df),
        "splink_version": splink.__version__,
        "training_rules": [name for name, _ in TRAINING_RULES],
        "trained": saved is None,
        "runtime_seconds": runtime,
    }

    # Every training run gets an immutable version directory (MASTER_CONTEXT
    # section 16). A reuse run has nothing new to persist: saving the untrained
    # linker would overwrite the lineage with a model that has no parameters.
    version = None
    if saved is None:
        version = model_lifecycle.save_version(
            linker, pred_df, scope_of(args.full), runtime, meta_extra
        )
        meta_extra["model_version"] = version.name

    write_meta(
        out_path,
        artifact="splink_predictions",
        scope=scope_of(args.full),
        input_rows=len(df),
        pairs_scored=len(pred_df),
        blocking_rules=[name for name, _ in BENCHMARK_RULES],
        training_rules=[name for name, _ in TRAINING_RULES],
        lambda_recall_assumption=LAMBDA_RECALL_ASSUMPTION,
        m_else_level_floor=M_ELSE_LEVEL_FLOOR,
        match_threshold=MATCH_THRESHOLD,
        review_threshold=REVIEW_THRESHOLD,
        random_seed=RANDOM_SEED,
        splink_version=splink.__version__,
        model_version=version.name if version else reused_from,
        trained=saved is None,
        runtime_seconds=runtime,
    )

    print(f"Input rows: {len(df):,}")
    print(f"Pairs scored: {len(pred_df):,}")
    if version is not None:
        print(f"Model version saved: {version}")
    else:
        print("Reused a saved model — no new version written.")
    if "decision" in pred_df.columns:
        counts = pred_df["decision"].value_counts().to_dict()
        total = len(pred_df)
        print(f"Decisions: {counts}")
        print(
            f"  auto-match rate {counts.get('MATCH', 0) / total:.4%} | "
            f"review rate {counts.get('REVIEW', 0) / total:.4%} | "
            f"non-match rate {counts.get('NON_MATCH', 0) / total:.4%}"
        )
    print(f"Saved: {out_path}")
    print(pred_df[[c for c in ["record_id_l", "record_id_r", "match_probability", "match_weight", "decision"] if c in pred_df.columns]].head(20))


if __name__ == "__main__":
    main()
