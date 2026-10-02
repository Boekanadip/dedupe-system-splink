"""Run with: python tests/test_smoke.py

No framework. Every check is an invariant that has actually been broken at least
once during this build, most importantly the scope-mixing bug where a 10k sample
run silently replaced a 50k entity map and still looked complete.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src import model_lifecycle
from src.evaluate import REPORT_PATH as EVALUATION_REPORT_PATH
from src.feedback import FEEDBACK_COLUMNS, FEEDBACK_PATH

from src.config import (
    BENCHMARK_RULES,
    COLUMN_MAP,
    ENTITY_MAP_PATH,
    LABELS_DIR,
    MASTER_PATH,
    MATCH_THRESHOLD,
    PREDICTIONS_FULL_PATH,
    PROCESSED_DATA_PATH,
    REVIEW_THRESHOLD,
    predictions_path,
    read_meta,
)
from src.eval_truth import device_truth_pairs
from src.labels import load_labels, normalise_label
from src.standardize import normalize_date

CHECKS: list = []


def check(fn):
    CHECKS.append(fn)
    return fn


@check
def standardized_data_exists():
    assert PROCESSED_DATA_PATH.exists(), "run: python -m src.standardize"
    return f"{PROCESSED_DATA_PATH.name} exists"


@check
def record_id_is_unique():
    df = pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id"])
    assert df["record_id"].is_unique, "record_id must be unique; it is the row identity"
    return f"{len(df):,} unique record_id"


@check
def blocking_rule_columns_exist():
    df = pd.read_parquet(PROCESSED_DATA_PATH)
    required = {c for _, cols in BENCHMARK_RULES for c in cols}
    missing = required - set(df.columns)
    assert not missing, f"blocking keys missing from standardized data: {sorted(missing)}"
    return f"all {len(required)} blocking keys present"


@check
def entity_map_covers_every_record_exactly_once():
    records = pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id"])
    entities = pd.read_parquet(ENTITY_MAP_PATH)
    assert set(entities["record_id"]) == set(records["record_id"]), (
        "entity_map must cover exactly the same records as the standardized data"
    )
    assert entities["record_id"].is_unique, "entity_map has duplicate record_id rows"
    assert entities["entity_id"].notna().all(), "entity_map has unassigned entity_id"
    return f"{len(entities):,} records all mapped"


@check
def clustering_actually_merged_something():
    entities = pd.read_parquet(ENTITY_MAP_PATH)
    n_records = len(entities)
    n_entities = entities["entity_id"].nunique()
    assert n_entities < n_records, "no records merged: the model found no duplicates at all"
    return f"{n_records:,} records -> {n_entities:,} entities"


@check
def master_has_one_row_per_entity():
    entities = pd.read_parquet(ENTITY_MAP_PATH)
    master = pd.read_parquet(MASTER_PATH)
    n_entities = entities["entity_id"].nunique()
    assert len(master) == n_entities, (
        f"master has {len(master):,} rows but there are {n_entities:,} entities"
    )
    assert master["entity_id"].is_unique, "master has duplicate entity_id rows"
    known = set(entities["entity_id"])
    unknown = set(master["entity_id"]) - known
    assert not unknown, f"master references {len(unknown)} entity_ids absent from entity_map"
    return f"{len(master):,} master rows, all entity_ids known"


@check
def master_record_counts_sum_to_input():
    master = pd.read_parquet(MASTER_PATH, columns=["record_count"])
    total = int(master["record_count"].sum())
    records = len(pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id"]))
    assert total == records, f"master record_count sums to {total:,}, expected {records:,}"
    return f"record_count sums to {total:,}"


@check
def artifacts_share_one_scope():
    metas = {
        "predictions": read_meta(predictions_path(full=True)),
        "entity_map": read_meta(ENTITY_MAP_PATH),
        "master_customers": read_meta(MASTER_PATH),
    }
    missing = [name for name, meta in metas.items() if not meta]
    assert not missing, f"no provenance sidecar for: {missing} (re-run python -m src.run_all)"
    scopes = {name: meta.get("scope") for name, meta in metas.items()}
    assert len(set(scopes.values())) == 1, f"artifacts mix scopes: {scopes}"
    return f"all artifacts scope={scopes['predictions']}"


@check
def clusters_recover_device_truth():
    """Device-truth pairs: two invariants, one reported recall number.

    device_id is neither a blocking key nor a comparison, so agreement cannot
    be satisfied by construction. What is asserted:

      1. a pair decided MATCH is never split across entities
      2. no entity mixes two device ids (that is what a false merge looks like)
      3. a device pair the model rejects outright must land in the REVIEW band,
         not in NON_MATCH — the human decides, the model does not deny it

    What is reported, not asserted: how many device pairs ended in one entity.
    Measured after adding batch_0003 (100 rows with injected typos): 2,867 of
    2,938 = 97.58%, and all 71 unmerged pairs are decided REVIEW with scores in
    5e-6..1.1e-3. The model learned from this dataset that duplicates are
    identical on every field (README caveat 2), so damaged duplicates score
    low on purpose. Asserting split == 0 would encode a threshold as an
    invariant, which is exactly what section 15 forbids. (Under the current
    model version the same pairs score 1.0 and the recall reads 100% — the
    number moves with the model, which is why it is reported, not asserted.)
    """
    records = pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id", "device_ids_std"])
    if records["device_ids_std"].dropna().empty:
        # device_id is an optional channel. Its absence removes one validation
        # number, it does not break the pipeline.
        return "SKIPPED: no device ids to check against (pipeline unaffected)"
    truth = device_truth_pairs(records)
    lookup = (
        pd.read_parquet(ENTITY_MAP_PATH)[["record_id", "entity_id"]]
        .set_index("record_id")["entity_id"]
    )
    joined = truth.assign(
        entity_l=truth["record_id_l"].map(lookup),
        entity_r=truth["record_id_r"].map(lookup),
    )
    assert joined["entity_l"].notna().all(), "entity_map does not cover every truth record"
    joined["same_entity"] = joined["entity_l"] == joined["entity_r"]

    decisions = pd.read_parquet(predictions_path(full=True))[
        ["record_id_l", "record_id_r", "decision"]
    ]
    scored = joined.merge(decisions, on=["record_id_l", "record_id_r"], how="left")
    assert scored["decision"].notna().all(), "a device-truth pair is missing from predictions"

    matched = scored[scored["decision"] == "MATCH"]
    assert (matched["same_entity"]).all(), "a pair decided MATCH was split across entities"

    rejected = scored[scored["decision"] != "MATCH"]
    assert not (rejected["decision"] == "NON_MATCH").any(), (
        f"{int((rejected['decision'] == 'NON_MATCH').sum())} device-truth pair(s) were "
        "rejected as NON_MATCH; a known duplicate must reach REVIEW at worst"
    )

    # The other direction: no entity may mix two different device ids, which is
    # what a false merge would look like here.
    ids = records.explode("device_ids_std").dropna(subset=["device_ids_std"])
    per_entity = ids.assign(entity_id=ids["record_id"].map(lookup)).groupby("entity_id")["device_ids_std"].nunique()
    mixed = int((per_entity > 1).sum())
    assert mixed == 0, f"{mixed} entities mix two different device ids (false merges)"

    clustered = int(joined["same_entity"].sum())
    recall = 100.0 * clustered / len(joined)
    return (
        f"{len(truth):,} device pairs: {clustered:,} clustered = {recall:.2f}% "
        f"({len(rejected):,} left in REVIEW for a human), 0 mixed entities"
    )


@check
def normalize_dates_handles_iso_and_ambiguity():
    """Regression: '1988-04-11' silently parsed as 1988-11-04 by pandas dayfirst.

    Every case here has already produced a wrong date at least once.
    """
    assert normalize_date("11/04/1988", True) == "1988-04-11", "d/m/Y with day>12"
    assert normalize_date("1988-04-11", True) == "1988-04-11", "ISO dashes must not swap"
    assert normalize_date("1988/04/11", True) == "1988-04-11", "ISO slashes must not swap"
    assert normalize_date("11-Apr-1988", True) == "1988-04-11", "named month needs no decision"
    # Ambiguous values can only differ by the recorded answer.
    assert normalize_date("04/11/1988", True) == "1988-11-04", "ambiguous under day-first"
    assert normalize_date("04/11/1988", False) == "1988-04-11", "ambiguous under month-first"
    assert normalize_date("31/02/1988", True) is None, "impossible date must be null, not coerced"
    return "ISO, named months, both ambiguous readings, invalid dates"


@check
def dob_column_fully_parsed():
    df = pd.read_parquet(PROCESSED_DATA_PATH, columns=["dob", "dob_std"])
    raw_null = int(df["dob"].isna().sum())
    parsed_null = int(df["dob_std"].isna().sum())
    assert parsed_null == raw_null, (
        f"{parsed_null:,} dob values failed to parse but only {raw_null:,} are empty in the "
        "source: the parser is dropping real dates, which silently kills dob blocking"
    )
    # A wrong day/month swap produces plausible strings, so shape is the only cheap
    # guard available here; the strict parse cases above cover the swap itself.
    bad_shape = int((df["dob_std"].dropna().str.len() != 10).sum())
    assert bad_shape == 0, f"{bad_shape} dob_std values are not ISO YYYY-MM-DD"
    return f"{len(df):,} rows, {parsed_null} unparseable, all ISO"


@check
def model_versions_are_reproducible():
    """A saved model must carry the policy and provenance it was judged under.

    MASTER_CONTEXT section 16 names four files per version. A version missing any
    of them cannot be compared against another one, and thresholds stored apart
    from the model let a score be reviewed under a different MATCH definition.
    """
    versions = model_lifecycle.list_versions()
    if not versions:
        return "SKIPPED: no model version saved yet (run src.splink_model --full)"
    for row in versions:
        assert row["complete"], (
            f"model version {row['version']} is missing one of "
            f"{model_lifecycle.REQUIRED_FILES}"
        )

    target = model_lifecycle.latest()
    assert target is not None, "latest.json points at a missing version directory"
    thresholds = json.loads((target / "thresholds.json").read_text(encoding="utf-8"))
    assert thresholds["match_threshold"] == MATCH_THRESHOLD, (
        f"saved threshold {thresholds['match_threshold']} != config "
        f"{MATCH_THRESHOLD}: the model was judged under a different policy"
    )
    meta = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
    for field in ("created_at", "pairs_scored", "random_seed", "lambda_recall_assumption"):
        assert field in meta, f"metadata.json missing {field}"
    assert len(versions) >= 1
    return f"{len(versions)} version(s), latest {target.name}, all 4 artifacts present"


@check
def evaluation_separates_all_four_layers():
    """DESIGN section 17 requires four distinct evaluations.

    A single accuracy number cannot say which layer failed: full blocking
    coverage with zero recall scores identically to full coverage with perfect
    recall. Each layer must also state what it does not prove, so a reader does
    not carry a blocking number into a linkage claim.
    """
    if not EVALUATION_REPORT_PATH.exists():
        return "SKIPPED: no evaluation_report.json yet (run python -m src.evaluate)"
    report = json.loads(EVALUATION_REPORT_PATH.read_text(encoding="utf-8"))

    for layer in ("blocking", "linkage", "decision", "entity"):
        assert layer in report, f"evaluation report has no '{layer}' layer (DESIGN section 17)"
        body = report[layer]
        assert body.get("status") in ("measured", "unavailable"), (
            f"layer '{layer}' has no status; an unmeasured layer must say so"
        )
        if body.get("status") == "measured":
            assert "does_not_prove" in body, (
                f"layer '{layer}' reports a result but not what it does not prove"
            )

    # MASTER_CONTEXT section 20: FACT and ASSUMPTION must not be mixed. An
    # unavailable truth channel must never be rendered as a zero.
    truth = report["truth_channel"]
    assert isinstance(truth["available"], bool)
    if not truth["available"]:
        for layer in ("blocking", "linkage", "entity"):
            assert report[layer].get("status") == "unavailable", (
                f"layer '{layer}' reports numbers with no truth channel available"
            )

    decision = report["decision"]
    if decision.get("status") == "measured":
        rates = decision.get("rates") or {}
        total = sum(rates.values()) if rates else 0
        # 6 dp rounding across 3 terms accumulates up to 1.5e-6.
        assert abs(total - 1.0) < 1e-4, f"decision rates do not sum to 1: {rates}"
        counts = decision.get("counts") or {}
        if counts:
            assert sum(counts.values()) == decision.get("candidate_pairs"), (
                f"decision counts {counts} do not add up to "
                f"{decision.get('candidate_pairs')} candidate pairs"
            )

    counts = {k: report[k].get("status") for k in ("blocking", "linkage", "decision", "entity")}
    return f"4 layers present: {counts}"


@check
def upload_validator_agrees_with_the_blocking_rules():
    """The validator must demand exactly what standardize() will accept.

    Two failure modes seen in one build: standardize() skipped an absent source
    column without complaint, so a batch missing `dob` was registered and only
    failed later inside Splink with MISSING COLUMN; and the validator warned
    about `dob` while standardize rejected the same file. A batch that passes
    validation and then fails at run time is worse than one refused up front.
    """
    import pandas as pd

    from src.validate_upload import blocking_source_columns, validate

    required = blocking_source_columns()
    assert required, "no blocking source columns derived from BENCHMARK_RULES"
    assert required <= set(COLUMN_MAP.values()), (
        f"derived columns not in COLUMN_MAP: {sorted(required - set(COLUMN_MAP.values()))}"
    )

    source = pd.read_parquet(PROCESSED_DATA_PATH)
    dropped = "dob"
    report = validate(source.drop(columns=[dropped]))
    assert report["status"] == "rejected", (
        f"a batch without '{dropped}' was accepted, but that column backs a blocking rule"
    )

    # And the full current dataset must pass, so the check is not just always-red.
    assert validate(source)["status"] == "accepted", (
        "the standardized dataset should validate cleanly"
    )
    return f"{len(required)} blocking source columns enforced; current dataset accepted"


@check
def batch_registry_covers_the_standardized_data():
    """Every stored record_id must belong to exactly one registered batch.

    The original trap: `standardize --input new.csv` rebuilt the parquet from
    that file alone, so record_ids restarted at rec_000001 and collided with rows
    already stored. The registry derives the start index, and this check is what
    would catch the collision if that logic ever broke.
    """
    from src import registry

    batches = registry.load()["batches"]
    if not batches:
        return "SKIPPED: no batch registry yet"

    total = sum(b["rows"] for b in batches)
    assert total == int(registry.load()["next_start_index"]), (
        "registry next_start_index does not match the sum of batch rows"
    )

    # Ranges must be contiguous: a gap or overlap would mean two batches claim
    # the same record_id, or one is silently missing.
    expected_start = 0
    for batch in batches:
        assert batch["start_index"] == expected_start, (
            f"batch {batch['batch_id']} ({batch['file']}) starts at "
            f"{batch['start_index']} but the previous batch ends at "
            f"{expected_start - 1}: the record_id ranges are not contiguous"
        )
        expected_start += batch["rows"]

    digests = [b["sha256"] for b in batches]
    assert len(digests) == len(set(digests)), (
        "two batches share a content hash — the same file was registered twice"
    )

    if not PROCESSED_DATA_PATH.exists():
        return f"{len(batches)} batch(es), {total:,} rows registered (no parquet yet)"

    stored = pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id"])
    assert len(stored) == total, (
        f"standardized data has {len(stored):,} rows but the registry accounts for "
        f"{total:,}. A batch was registered without being standardized, or a "
        "standardize run replaced the parquet with a subset of the batches."
    )
    stored_ids = set(stored["record_id"])
    boundaries = set()
    for batch in batches:
        boundaries.update(batch["record_id_range"])
    missing = sorted(r for r in boundaries if r not in stored_ids)
    assert not missing, f"registry range boundaries absent from the parquet: {missing}"
    return f"{len(batches)} batch(es), {total:,} rows, contiguous, all boundaries present"


@check
def match_edges_are_independently_verifiable():
    """Every MATCH edge must be checkable, not just asserted correct.

    "0 false merges" is a claim in a report. This turns it into something the
    test suite fails on: each MATCH edge is checked against device_id, which the
    model never reads, and against the entity it was actually clustered into.
    """
    preds = pd.read_parquet(PREDICTIONS_FULL_PATH)
    if "decision" not in preds.columns:
        return "SKIPPED: no decision column"
    matches = preds[preds["decision"] == "MATCH"]
    assert not matches.empty, "no MATCH decisions at all"

    records = pd.read_parquet(
        PROCESSED_DATA_PATH, columns=["record_id", "device_ids_std"]
    )
    if records["device_ids_std"].dropna().empty:
        return "SKIPPED: no device ids to verify against"

    lookup = (
        pd.read_parquet(ENTITY_MAP_PATH)[["record_id", "entity_id"]]
        .set_index("record_id")["entity_id"]
    )
    ids = records.explode("device_ids_std").dropna(subset=["device_ids_std"])
    devices = ids.groupby("record_id")["device_ids_std"].apply(frozenset)

    joined = matches[["record_id_l", "record_id_r"]].assign(
        device_l=matches["record_id_l"].map(devices),
        device_r=matches["record_id_r"].map(devices),
        entity_l=matches["record_id_l"].map(lookup),
        entity_r=matches["record_id_r"].map(lookup),
    )
    # A record with no device data maps to NaN (batch_0005 rows come from a file
    # without device_id(s)), and len(NaN) raises. Empty set = unverifiable, which
    # is counted and reported below instead of crashing the check.
    joined["device_l"] = joined["device_l"].map(
        lambda v: v if isinstance(v, frozenset) else frozenset()
    )
    joined["device_r"] = joined["device_r"].map(
        lambda v: v if isinstance(v, frozenset) else frozenset()
    )
    unchecked = int(
        (joined["device_l"].map(len).eq(0) | joined["device_r"].map(len).eq(0)).sum()
    )
    disagree = int(
        (
            joined["device_l"].ne(joined["device_r"])
            & joined["device_l"].map(len).gt(0)
            & joined["device_r"].map(len).gt(0)
        ).sum()
    )
    split = int((joined["entity_l"] != joined["entity_r"]).sum())
    assert disagree == 0, (
        f"{disagree} MATCH edges do NOT share a device id — these are the false merges"
    )
    assert split == 0, f"{split} MATCH edges were not clustered into one entity"
    return (
        f"{len(matches):,} MATCH edges verified: 0 without a shared device id, "
        f"0 split across entities, {unchecked} unverifiable (no device data)"
    )


@check
def feedback_captures_every_required_field():
    """DESIGN section 12 lists the fields feedback must retain.

    A reviewer's label is only reusable for evaluation and retraining if it can
    be tied to the score and the model version it judged. Without model_version
    there is no way to tell which model a case belongs to, which is exactly what
    MASTER_CONTEXT section 15 needs to decide when to retrain.
    """
    if not FEEDBACK_PATH.exists():
        return "SKIPPED: no feedback.csv yet (run python -m src.feedback)"
    frame = pd.read_csv(FEEDBACK_PATH)
    missing = set(FEEDBACK_COLUMNS) - set(frame.columns)
    assert not missing, f"feedback.csv missing DESIGN section 12 fields: {sorted(missing)}"
    assert frame["pair_id"].notna().all(), "feedback rows without a pair_id"
    assert frame["human_label"].isin(["match", "no_match"]).all(), (
        f"unexpected human_label values {sorted(set(frame['human_label'].dropna()))}"
    )
    versions = {v for v in frame["model_version"].dropna()}
    assert versions, "no feedback row records which model version produced it"
    unknown = versions - {v["version"] for v in model_lifecycle.list_versions()}
    assert not unknown, f"feedback references unknown model versions: {sorted(unknown)}"
    assert frame["score"].notna().all(), "feedback rows without the score that was reviewed"
    return (
        f"{len(frame):,} rows, labels {frame['human_label'].value_counts().to_dict()}, "
        f"model {sorted(versions)}"
    )


@check
def gold_label_vocabulary_keeps_negatives():
    """Regression: 'no_match' was dropped silently, so gold had no negatives.

    promote_gold() filtered on TRUTHY only. Every reviewed 'no_match' row was
    discarded without an error, which makes precision look perfect and the gold
    set useless. Both classes must survive, and a blank must survive as missing.
    """
    assert normalise_label("match") == "match", "positive label"
    assert normalise_label("no_match") == "no_match", "negative label was being dropped"
    assert normalise_label("0") == "no_match", "numeric negative"
    assert normalise_label("bukan") is None, "unknown vocabulary must not become a negative"
    assert normalise_label("") is None, "blank must stay missing, never a negative"
    assert normalise_label(None) is None

    _, source = load_labels()
    assert source in ("none", "silver", "gold"), f"unexpected label source {source!r}"
    gold = LABELS_DIR / "gold_labels.csv"
    if gold.exists():
        frame = pd.read_csv(gold, sep=None, engine="python")
        assert "label" in frame.columns, f"{gold.name} has no label column"
        classes = set(frame["label"].astype(str).str.strip().str.lower())
        assert classes <= {"match", "no_match"}, f"gold has raw vocabulary {classes}"
    return f"vocabulary OK; current label source: {source}"


@check
def decision_column_is_present_and_ordered():
    """Every pair has exactly one decision, and it agrees with the probabilities.

    Without this the three-way policy can silently collapse back to two values,
    or REVIEW can be built from a threshold that disagrees with its own label.
    """
    preds = pd.read_parquet(PREDICTIONS_FULL_PATH)
    assert "decision" in preds.columns, "predictions have no 'decision' column (PRD section 7)"
    allowed = {"MATCH", "REVIEW", "NON_MATCH"}
    found = set(preds["decision"].unique())
    assert found <= allowed, f"unexpected decision values {found - allowed}"

    p = preds["match_probability"]
    assert (preds.loc[p >= MATCH_THRESHOLD, "decision"] == "MATCH").all(), (
        "a pair above MATCH_THRESHOLD is not labelled MATCH"
    )
    review = preds[preds["decision"] == "REVIEW"]
    assert (review["match_probability"] < MATCH_THRESHOLD).all(), (
        "a REVIEW pair is at or above MATCH_THRESHOLD"
    )
    assert (review["match_probability"] >= REVIEW_THRESHOLD).all(), (
        "a REVIEW pair is below REVIEW_THRESHOLD"
    )
    counts = preds["decision"].value_counts().to_dict()
    return f"{len(preds):,} pairs -> {counts}"


@check
def review_pairs_are_not_merged():
    """A REVIEW pair must not have been clustered into one entity.

    The whole point of the review band is that a human decides. If clustering
    merges it anyway, the band is decoration.
    """
    preds = pd.read_parquet(PREDICTIONS_FULL_PATH)
    if "decision" not in preds.columns:
        return "SKIPPED: no decision column"
    review = preds[preds["decision"] == "REVIEW"]
    if review.empty:
        return "SKIPPED: REVIEW band is empty on this dataset (0 pairs need a human)"
    lookup = (
        pd.read_parquet(ENTITY_MAP_PATH)[["record_id", "entity_id"]]
        .set_index("record_id")["entity_id"]
    )
    joined = review[["record_id_l", "record_id_r"]].assign(
        entity_l=review["record_id_l"].map(lookup),
        entity_r=review["record_id_r"].map(lookup),
    )
    merged = int((joined["entity_l"] == joined["entity_r"]).sum())
    assert merged == 0, f"{merged} REVIEW pairs were merged into one entity anyway"
    return f"{len(review):,} REVIEW pairs, none merged"


def main() -> int:
    failures = 0
    for fn in CHECKS:
        try:
            detail = fn()
            print(f"PASS  {fn.__name__}: {detail}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # missing file, bad parquet, etc.
            failures += 1
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
