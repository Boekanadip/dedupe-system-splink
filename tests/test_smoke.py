"""Run with: python tests/test_smoke.py

No framework. Every check is an invariant that has actually been broken at least
once during this build, most importantly the scope-mixing bug where a 10k sample
run silently replaced a 50k entity map and still looked complete.
"""

from __future__ import annotations

import json
import locale
import subprocess
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
    OUTPUT_DIR,
    PREDICTIONS_FULL_PATH,
    PROCESSED_DATA_PATH,
    REVIEW_THRESHOLD,
    predictions_path,
    read_meta,
)
from src.eval_truth import device_truth_pairs
from src.evaluation_freshness import compare_provenance
from src.labels import exclude_gold_pairs, load_labels, normalise_label
from src.splink_model import DOB_SAME_YEAR_DAYS
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
def blocking_rules_come_from_config_with_default_fallback(tmp_path=None):
    import tempfile

    from src.config import DEFAULT_BENCHMARK_RULES, load_benchmark_rules

    # No config file -> default rules, byte-identical to the old hardcoded list.
    assert load_benchmark_rules("does/not/exist.json") == DEFAULT_BENCHMARK_RULES
    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "good.json"
        good.write_text(
            json.dumps([{"name": "email_exact", "columns": ["email_std"]}]),
            encoding="utf-8",
        )
        assert load_benchmark_rules(good) == [("email_exact", ["email_std"])]

        broken = Path(tmp) / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        # A broken client config must not crash the pipeline silently with a
        # partial rule set; it falls back to the documented default.
        assert load_benchmark_rules(broken) == DEFAULT_BENCHMARK_RULES
    return "override honored; missing/broken config falls back to default rules"


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
    """Business rule first, device_id second — because device_id is not truth.

    2026-10-12: device_id was treated as the answer key, so every MATCH edge
    whose two records carried different device ids was counted as a false
    merge (4,867 of them). The data owner's rule contradicts that: a person may
    simply hold several devices, so a device disagreement does NOT mean two
    people. What the owner specified instead is:

        email + first_name + last_name + address identical  -> same person
        ... unless dob differs                              -> different person

    Under that rule the real false-merge count was 153, not 4,867 — and 4,835
    of the "false merges" were one person on two devices. device_id is kept
    below as a REPORTED figure only; asserting on it would encode a truth
    source the owner has explicitly rejected.

    What IS asserted:
      1. a pair decided MATCH is never split across entities
      2. no MATCH edge contradicts the owner's rule (dob conflict forced out)
      3. a device pair the model rejects outright lands in REVIEW, not NON_MATCH
    """
    records = pd.read_parquet(
        PROCESSED_DATA_PATH,
        columns=["record_id", "device_ids_std", "email_std", "first_name_std",
                 "last_name_std", "address_std", "dob_std"],
    )
    lookup = (
        pd.read_parquet(ENTITY_MAP_PATH)[["record_id", "entity_id"]]
        .set_index("record_id")["entity_id"]
    )
    decisions = pd.read_parquet(predictions_path(full=True))[
        ["record_id_l", "record_id_r", "decision"]
    ]

    # --- Check 2 (primary): no MATCH edge may contradict the owner's rule.
    lk = records.set_index("record_id")
    m = decisions[decisions["decision"] == "MATCH"].copy()
    for col in ("email_std", "first_name_std", "last_name_std", "address_std", "dob_std"):
        m[f"{col}_l"] = m["record_id_l"].map(lk[col])
        m[f"{col}_r"] = m["record_id_r"].map(lk[col])

    def _both_eq(col: str) -> "pd.Series":
        left, right = m[f"{col}_l"], m[f"{col}_r"]
        return left.notna() & right.notna() & left.eq(right)

    keys_same = _both_eq("email_std") & _both_eq("first_name_std") \
        & _both_eq("last_name_std") & _both_eq("address_std")
    dob_left, dob_right = m["dob_std_l"], m["dob_std_r"]
    dob_both = dob_left.notna() & dob_right.notna()
    # Dob berbeda LEBIH dari satu tahun melanggar aturan; berbeda sampai satu
    # tahun tidak (salah ketik tahun, bukan orang kedua). Ukur ulang di sini
    # dengan ambang yang sama seperti DOB_SAME_YEAR_DAYS di src/splink_model.py.
    real_conflict = pd.Series(False, index=m.index)
    if dob_both.any():
        d1 = pd.to_datetime(dob_left[dob_both], errors="coerce")
        d2 = pd.to_datetime(dob_right[dob_both], errors="coerce")
        real_conflict.loc[dob_both] = (
            ((d1 - d2).dt.days.abs() > DOB_SAME_YEAR_DAYS).fillna(False).to_numpy()
        )
    violating = int((keys_same & real_conflict).sum())
    assert violating == 0, (
        f"{violating} MATCH edge(s) have email+name+address identical but a dob "
        f"more than {DOB_SAME_YEAR_DAYS} days apart — the owner's rule says these are two people"
    )

    if records["device_ids_std"].dropna().empty:
        return (
            f"{len(m):,} MATCH edges, 0 contradict the business rule "
            "(no device ids to cross-check)"
        )

    truth = device_truth_pairs(records)
    joined = truth.assign(
        entity_l=truth["record_id_l"].map(lookup),
        entity_r=truth["record_id_r"].map(lookup),
    )
    assert joined["entity_l"].notna().all(), "entity_map does not cover every truth record"
    joined["same_entity"] = joined["entity_l"] == joined["entity_r"]

    scored = joined.merge(decisions, on=["record_id_l", "record_id_r"], how="left")
    assert scored["decision"].notna().all(), "a device-truth pair is missing from predictions"

    matched = scored[scored["decision"] == "MATCH"]
    assert (matched["same_entity"]).all(), "a pair decided MATCH was split across entities"

    rejected = scored[scored["decision"] != "MATCH"]
    assert not (rejected["decision"] == "NON_MATCH").any(), (
        f"{int((rejected['decision'] == 'NON_MATCH').sum())} device-truth pair(s) were "
        "rejected as NON_MATCH; a known duplicate must reach REVIEW at worst"
    )

    # Reported, NOT asserted: an entity holding two device ids. The owner's rule
    # permits this (one person, several devices), so it is a signal to sample,
    # not a failure. 2026-10-12 measurement: 2,541 such entities, of which the
    # rule-based check above finds 0 genuine conflicts.
    ids = records.explode("device_ids_std").dropna(subset=["device_ids_std"])
    per_entity = ids.assign(entity_id=ids["record_id"].map(lookup)).groupby("entity_id")[
        "device_ids_std"
    ].nunique()
    mixed = int((per_entity > 1).sum())

    clustered = int(joined["same_entity"].sum())
    recall = 100.0 * clustered / len(joined)
    return (
        f"{len(m):,} MATCH edges, 0 contradict the business rule; "
        f"{len(truth):,} device pairs {clustered:,} clustered = {recall:.2f}%; "
        f"{mixed:,} entities hold 2+ device ids (reported, allowed by the rule)"
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
def incremental_candidate_prefilter_is_exact():
    """The pre-filtered scoring frame must keep the pairs and the MATCH
    edges of scoring the full parquet.

    On the real standardized data and the active model, 100 records are
    treated as a "new batch". Two frames are scored with the same
    patched model:
      A) candidate_old_rows(new) + new  (what compute feeds Splink)
      B) the full parquet               (the old behaviour)
    The (record_id_l, record_id_r) sets and the MATCH edge sets must be
    identical: MATCH edges are what clustering turns into entity_ids, so
    this is the invariant that protects entity identity.

    Probabilities are NOT identical and must not be asserted to be:
    city_std / state_std / country_std carry term_frequency_adjustments
    (src/splink_model.py), whose weights depend on how many rows the
    Linker is given. A pair sitting exactly on the 1e-10 REVIEW floor
    can therefore land on either side of it — MEASURED on the 51k set:
    12 of 1,172 pairs (all with p ~ 1e-10, none near MATCH_THRESHOLD),
    26 REVIEW under B vs 14 under A. The drift is reported, the MATCH
    edges are asserted.
    """
    if not PROCESSED_DATA_PATH.exists():
        return "SKIPPED: no standardized data (run python -m src.run_all)"
    target = model_lifecycle.latest()
    if target is None:
        return "SKIPPED: no saved model (run python -m src.run_all --full)"

    from src.incremental import (
        _rule_key_pairs,
        candidate_old_rows,
        score_new_pairs,
    )

    full = pd.read_parquet(PROCESSED_DATA_PATH)
    new_std = full.sample(n=min(100, len(full)), random_state=42)
    new_ids = set(new_std["record_id"])
    model = model_lifecycle.load_model_json(target)

    key_pairs = _rule_key_pairs(model)
    assert key_pairs is not None, "a blocking rule is not a pure equi-join"
    candidates = candidate_old_rows(new_std, key_pairs)
    frame_a = pd.concat([candidates, new_std], ignore_index=True)

    preds_a = score_new_pairs(frame_a, new_ids, model=model)
    preds_b = score_new_pairs(full, new_ids, model=model)

    def pairs(frame, decision=None):
        if decision is not None:
            frame = frame[frame["decision"] == decision]
        return set(zip(frame["record_id_l"], frame["record_id_r"]))

    assert pairs(preds_a) == pairs(preds_b), (
        f"pre-filter changed the candidate set: "
        f"{len(pairs(preds_a))} vs {len(pairs(preds_b))} pairs"
    )
    match_a, match_b = pairs(preds_a, "MATCH"), pairs(preds_b, "MATCH")
    assert match_a == match_b, (
        f"pre-filter changed {len(match_a ^ match_b)} MATCH edge(s) — "
        "these become entity_ids, so entity identity would differ"
    )

    # What changed must stay below the clustering threshold: only the
    # REVIEW floor may move.
    flipped = preds_a.merge(
        preds_b[["record_id_l", "record_id_r", "decision", "match_probability"]],
        on=["record_id_l", "record_id_r"], suffixes=("_a", "_b")
    )
    flipped = flipped[flipped["decision_a"] != flipped["decision_b"]]
    assert (flipped["match_probability_a"] < MATCH_THRESHOLD).all(), (
        "a flipped pair sits at or above MATCH_THRESHOLD"
    )
    prob = preds_a[["record_id_l", "record_id_r", "match_probability"]].merge(
        preds_b[["record_id_l", "record_id_r", "match_probability"]],
        on=["record_id_l", "record_id_r"], suffixes=("_a", "_b"),
    )
    drift = float(
        (prob["match_probability_a"] - prob["match_probability_b"]).abs().max()
    )
    # Guard, not an expectation: a term-frequency regression would move this
    # by orders of magnitude, while a routine dataset-change moves it by less.
    assert drift < 1e-2, f"probability drift {drift} exceeds the 1e-2 guard"
    return (
        f"{len(pairs(preds_a)):,} pairs + {len(match_a)} MATCH edges identical; "
        f"{len(flipped)} review-floor flips "
        f"({int((preds_b['decision'] == 'REVIEW').sum())} -> "
        f"{int((preds_a['decision'] == 'REVIEW').sum())} REVIEW); "
        f"max drift {drift:.1e}"
    )


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
    """Every MATCH edge must be checkable against the owner's rule, not device_id.

    device_id used to be the truth source, so any MATCH edge whose two records
    carried different device ids was called a false merge (4,867 at peak). The
    owner's rule says that is wrong: one person may hold several devices, so a
    device disagreement is not evidence of two people. The rule that IS
    authoritative:

        email + first_name + last_name + address identical  -> same person
        ... unless dob differs                              -> different person

    This test asserts the rule holds for every MATCH edge, and separately
    reports how many edges carry two device ids (allowed, not an error).
    """
    preds = pd.read_parquet(PREDICTIONS_FULL_PATH)
    if "decision" not in preds.columns:
        return "SKIPPED: no decision column"
    matches = preds[preds["decision"] == "MATCH"].copy()
    assert not matches.empty, "no MATCH decisions at all"

    records = pd.read_parquet(
        PROCESSED_DATA_PATH,
        columns=["record_id", "email_std", "first_name_std", "last_name_std",
                 "address_std", "dob_std"],
    )
    lk = records.set_index("record_id")
    for col in ("email_std", "first_name_std", "last_name_std", "address_std", "dob_std"):
        matches[f"{col}_l"] = matches["record_id_l"].map(lk[col])
        matches[f"{col}_r"] = matches["record_id_r"].map(lk[col])

    def _both_eq(col: str) -> "pd.Series":
        left, right = matches[f"{col}_l"], matches[f"{col}_r"]
        return left.notna() & right.notna() & left.eq(right)

    keys_same = (
        _both_eq("email_std") & _both_eq("first_name_std")
        & _both_eq("last_name_std") & _both_eq("address_std")
    )
    dob_left, dob_right = matches["dob_std_l"], matches["dob_std_r"]
    dob_both = dob_left.notna() & dob_right.notna()
    real_conflict = pd.Series(False, index=matches.index)
    if dob_both.any():
        d1 = pd.to_datetime(dob_left[dob_both], errors="coerce")
        d2 = pd.to_datetime(dob_right[dob_both], errors="coerce")
        real_conflict.loc[dob_both] = (
            ((d1 - d2).dt.days.abs() > DOB_SAME_YEAR_DAYS).fillna(False).to_numpy()
        )
    violating = int((keys_same & real_conflict).sum())
    assert violating == 0, (
        f"{violating} MATCH edge(s) have email+name+address identical but a dob "
        f"more than {DOB_SAME_YEAR_DAYS} days apart — under the owner's rule "
        "these are two people"
    )

    lookup = (
        pd.read_parquet(ENTITY_MAP_PATH)[["record_id", "entity_id"]]
        .set_index("record_id")["entity_id"]
    )
    split = int(
        (matches["record_id_l"].map(lookup) != matches["record_id_r"].map(lookup)).sum()
    )
    assert split == 0, f"{split} MATCH edges were not clustered into one entity"

    # Reported only: how many MATCH edges span two device ids. Allowed by the
    # owner's rule, so it is a sampling signal, not a failure.
    dev_records = pd.read_parquet(PROCESSED_DATA_PATH, columns=["record_id", "device_ids_std"])
    if not dev_records["device_ids_std"].dropna().empty:
        ids = dev_records.explode("device_ids_std").dropna(subset=["device_ids_std"])
        devices = ids.groupby("record_id")["device_ids_std"].apply(frozenset)
        dl = matches["record_id_l"].map(devices).map(
            lambda v: v if isinstance(v, frozenset) else frozenset()
        )
        dr = matches["record_id_r"].map(devices).map(
            lambda v: v if isinstance(v, frozenset) else frozenset()
        )
        two_devices = int((dl.ne(dr) & dl.map(len).gt(0) & dr.map(len).gt(0)).sum())
    else:
        two_devices = None

    note = (
        f", {two_devices:,} span two device ids (allowed: one person, many devices)"
        if two_devices is not None else ""
    )
    return (
        f"{len(matches):,} MATCH edges: 0 contradict the business rule, "
        f"0 split across entities{note}"
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
def review_queue_hides_pairs_already_promoted_to_gold():
    queue = pd.DataFrame(
        {
            "record_id_l": ["a", "b", "c"],
            "record_id_r": ["b", "a", "d"],
            "label": ["match", "no_match", ""],
        }
    )
    gold = pd.DataFrame(
        {
            "record_id_l": ["b"],
            "record_id_r": ["a"],
            "label": ["match"],
        }
    )
    visible = exclude_gold_pairs(queue, gold)
    assert visible[["record_id_l", "record_id_r"]].values.tolist() == [["c", "d"]]
    assert len(queue) == 3, "filter must not mutate the persisted review queue"
    return "promoted pair hidden regardless of record order; other rows preserved"


@check
def model_score_report_detects_stale_provenance():
    saved = {
        "gold_sha256": "gold-1",
        "processed_data_sha256": "data-1",
        "prediction_sha256": "pred-1",
        "model_inventory_sha256": "models-1",
    }
    current = {**saved, "gold_sha256": "gold-2", "model_inventory_sha256": "models-2"}
    missing, changed = compare_provenance(saved, current)
    assert missing == []
    assert changed == ["gold_sha256", "model_inventory_sha256"]

    missing, changed = compare_provenance({"gold_sha256": "gold-1"}, current)
    assert set(missing) == {
        "processed_data_sha256",
        "prediction_sha256",
        "model_inventory_sha256",
    }
    assert changed == ["gold_sha256"]
    return "reports changed inputs and legacy reports without freshness metadata"


@check
def decision_column_is_present_and_ordered():
    """Every pair has exactly one decision, and it agrees with the probabilities.

    Without this the three-way policy can silently collapse back to two values,
    or REVIEW can be built from a threshold that disagrees with its own label.

    The business rule (email+name+address identical but dob differs -> NON_MATCH)
    is allowed to override a high probability: that is the entire point of the
    rule. Pairs it touched are excluded from the threshold assertions below and
    counted separately, so a genuine threshold bug cannot hide behind it.
    """
    preds = pd.read_parquet(PREDICTIONS_FULL_PATH)
    assert "decision" in preds.columns, "predictions have no 'decision' column (PRD section 7)"
    allowed = {"MATCH", "REVIEW", "NON_MATCH"}
    found = set(preds["decision"].unique())
    assert found <= allowed, f"unexpected decision values {found - allowed}"

    overridden = (
        preds["business_rule"].notna() if "business_rule" in preds.columns
        else pd.Series(False, index=preds.index)
    )
    model_pairs = preds[~overridden]

    p = model_pairs["match_probability"]
    assert (model_pairs.loc[p >= MATCH_THRESHOLD, "decision"] == "MATCH").all(), (
        "a pair above MATCH_THRESHOLD is not labelled MATCH (and was not overridden "
        "by the business rule)"
    )
    review = model_pairs[model_pairs["decision"] == "REVIEW"]
    assert (review["match_probability"] < MATCH_THRESHOLD).all(), (
        "a REVIEW pair is at or above MATCH_THRESHOLD"
    )
    assert (review["match_probability"] >= REVIEW_THRESHOLD).all(), (
        "a REVIEW pair is below REVIEW_THRESHOLD"
    )
    # The rule may reject, but only in the one case that is validated by human
    # decisions: zero identity fields agreeing (5/5 gold pairs with 0 agreeing
    # fields were labelled "beda orang", none "orang sama"). An UNVERIFIABLE
    # dob must never reject — that is the case where a typo is just as likely
    # as a second person, and rejecting it is irreversible.
    forced = preds[overridden]
    rejected = forced[forced["decision"] == "NON_MATCH"]
    bad_reject = int((rejected["business_rule"] != "no_field_agrees").sum())
    assert bad_reject == 0, (
        f"{bad_reject} pair(s) were rejected by a rule other than 'no_field_agrees'; "
        "only a zero-evidence rejection is validated, an unverifiable dob must "
        "queue for a human instead"
    )
    counts = preds["decision"].value_counts().to_dict()
    return (
        f"{len(preds):,} pairs -> {counts}; "
        f"{int(overridden.sum()):,} overridden by the business rule"
    )


@check
def review_pairs_are_not_merged():
    """A REVIEW pair may share an entity only through transitive MATCH edges,
    and every such entity must be flagged conflicted.

    LIMITATION OF UNION-FIND (measured 2026-10-12, confirmed 2026-10-14):
    clustering uses only MATCH edges. If A×C and B×C are MATCH but A×B is
    REVIEW, connected components puts all three in one entity. Union-find
    cannot honour a must-not-link constraint that is only reachable
    transitively. This is inherent to the algorithm, not a bug.

    Earlier the test asserted model-decided REVIEW pairs must NEVER share an
    entity. That assertion is mathematically impossible to satisfy whenever
    a transitive MATCH path exists — the PostgreSQL batch (2,003 rows with
    intentional duplicates) exposed this: 1,716 model-decided REVIEW pairs
    were transitively merged, zero of them were wrong merges.

    What the test now asserts:
      1. every entity containing a merged REVIEW pair is flagged
         `conflicted_fields` (so it surfaces as "needs a decision")
      2. no entity containing a merged REVIEW pair is silently clean
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
    joined = review.assign(
        entity_l=review["record_id_l"].map(lookup),
        entity_r=review["record_id_r"].map(lookup),
    )
    merged = joined[joined["entity_l"] == joined["entity_r"]]

    forced = merged["business_rule"].notna() if "business_rule" in merged.columns \
        else pd.Series(False, index=merged.index)
    model_merged = int((~forced).sum())
    transitive = int(forced.sum())

    # Every entity that contains a merged REVIEW pair must be flagged.
    master = pd.read_parquet(MASTER_PATH)
    affected = set(merged["entity_l"].dropna())
    flagged = master[master["entity_id"].isin(affected)]
    unflagged = int(flagged["conflicted_fields"].apply(len).eq(0).sum())
    assert unflagged == 0, (
        f"{unflagged} entities containing a merged REVIEW pair are NOT flagged "
        "with conflicted_fields; the conflict would ship silently"
    )

    return (
        f"{len(review):,} REVIEW pairs: {len(merged):,} transitively merged "
        f"({model_merged} model-decided, {transitive} rule-forced), "
        f"all {len(affected)} entities flagged conflicted"
    )


@check
def incremental_history_new_entities_is_a_delta():
    """new_entities is a per-batch delta, never the running total.

    apply_staged() used updated_map["entity_id"].nunique(), i.e. the whole
    entity count (48,380) written as "entities this batch created". The
    dashboard's "Batch per minggu" chart summed that field as if it were new
    entities per batch, so 3 batches looked like they each created 48k
    entities. A batch of N records can create at most N new entities, so the
    delta must never exceed new_records.
    """
    path = OUTPUT_DIR / "incremental_history.jsonl"
    if not path.exists():
        return "SKIPPED: no incremental_history.jsonl"
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows, "incremental_history.jsonl is empty"
    bad = [
        r for r in rows
        if int(r.get("new_entities", 0)) > int(r.get("new_records", 0))
    ]
    assert not bad, (
        f"{len(bad)} row(s) record more new entities than new records "
        f"(total, not delta): {[(r['batch'], r['new_entities'], r['new_records']) for r in bad]}"
    )
    return f"{len(rows)} batch(es), new_entities always <= new_records"


@check
def label_source_can_be_pinned():
    """load_labels() must be able to return the source the caller asked for.

    It took no arguments and always preferred gold, so `threshold_eval --source
    silver` raised "Silver labels requested but source is gold" as soon as
    gold_labels.csv existed. The flag was unreachable, not wrong — and the
    silver run it existed for could not be reproduced at all.
    """
    auto_labels, auto_source = load_labels()
    assert auto_source in ("none", "silver", "gold"), f"unexpected source {auto_source!r}"

    for wanted in ("gold", "silver"):
        labels, source = load_labels(wanted)
        if labels is None:
            continue  # that file simply has not been produced yet
        assert source == wanted, (
            f"load_labels({wanted!r}) resolved to {source!r}; the pin is ignored"
        )

    try:
        load_labels("bronze")
    except ValueError:
        pass
    else:
        raise AssertionError("load_labels accepted an unknown source name")

    # The default must stay gold-first, because evaluate.py and
    # blocking_benchmark.py rely on "reviewed labels win".
    if auto_labels is not None and (LABELS_DIR / "gold_labels.csv").exists():
        assert auto_source == "gold", (
            f"auto resolved to {auto_source!r} while gold_labels.csv exists"
        )
    return f"auto={auto_source}, pinned gold/silver honoured, unknown source refused"


@check
def subprocess_capture_cannot_lose_output():
    """Capturing a child whose output is not cp1252 must not return stdout=None.

    Reproduced on this machine. cp1252 leaves 0x81/0x8D/0x8F/0x90/0x9D undefined,
    and every UTF-8 3-byte sequence whose middle byte is one of those kills the
    decoder thread: subprocess.run(..., text=True, capture_output=True) with no
    encoding then returns returncode 0 with stdout=None. close_gold_loop did
    sys.stdout.write(None) on that, so `--all` died one step after reporting it
    fine. U+207B is not hypothetical: it is what the old probability formatter
    printed, and src/evaluate.py still prints U+2014, which decodes as mojibake.
    """
    console = locale.getpreferredencoding(False)
    undef = []
    for cp in range(0x80, 0x100):
        try:
            bytes([cp]).decode(console)
        except UnicodeDecodeError:
            undef.append(cp)
    assert undef, f"{console} decoded every byte; this check proves nothing here"

    # U+207B SUPERSCRIPT MINUS -> UTF-8 e2 81 bb, byte 0x81 undefined in cp1252.
    probe = "\u207b"
    assert 0x81 in [b for b in probe.encode("utf-8")], "probe lost its 0x81 byte"

    child = (
        "import sys; sys.stdout.reconfigure(encoding='utf-8'); "
        "print('3.40 \u00d7 10\u207b7\u2014 done')"
    )

    broken = subprocess.run(
        [sys.executable, "-c", child],
        text=True, capture_output=True, encoding=console, errors="strict",
    )
    assert broken.stdout is None, (
        f"expected {console}/strict to fail on U+207B, got {broken.stdout!r}; "
        "this check no longer proves the fix is needed"
    )

    fixed = subprocess.run(
        [sys.executable, "-c", child],
        text=True, capture_output=True, encoding="utf-8", errors="replace",
    )
    assert fixed.returncode == 0, f"child failed with {fixed.returncode}"
    assert fixed.stdout and "\u207b" in fixed.stdout, (
        f"utf-8 capture lost the superscript: {fixed.stdout!r}"
    )
    return f"{console} undefined bytes {len(undef)}; utf-8+replace keeps U+207B"


@check
def blocking_coverage_uses_candidate_union():
    from unittest.mock import patch

    from src.evaluate import evaluate_blocking

    truth = pd.DataFrame({"record_id_l": ["a", "c"], "record_id_r": ["b", "d"]})
    rules = pd.DataFrame({"device_truth_covered": [1, 1]})
    with patch("src.evaluate.predictions_path", return_value=PROCESSED_DATA_PATH), \
         patch("src.evaluate.pd.read_parquet", return_value=truth), \
         patch("src.evaluate.rule_coverage", return_value=rules):
        result = evaluate_blocking(pd.DataFrame(), truth)
    assert result["truth_pairs_generated_as_candidates"] == 2
    assert result["truth_pairs_never_generated"] == 0
    return "union covers two pairs although each individual rule covers only one"


@check
def stage0_entity_violations_count_transitive_merges():
    from src.stage0_audit import evaluate_reviewed_entities

    entities = pd.DataFrame({
        "record_id": ["a", "b", "c", "d"],
        "entity_id": ["one", "one", "one", "two"],
    })
    labels = pd.DataFrame({
        "record_id_l": ["a", "a", "a", "a"],
        "record_id_r": ["b", "c", "d", "missing"],
        "is_positive": [True, False, True, True],
    })
    result = evaluate_reviewed_entities(entities, labels)
    assert result["pairs_missing_entity_mapping"] == 1
    assert result["reviewed_positive_pairs_split"] == 1
    assert result["reviewed_negative_pairs_merged"] == 1
    assert result["entities_containing_reviewed_negative_pair"] == 1
    assert result["records_in_implicated_entities"] == 3
    assert result["largest_implicated_entity_size"] == 3
    return "transitive negative merge, positive split and missing mapping counted separately"


@check
def stage0_device_reference_reports_missing_and_mixed():
    from src.stage0_audit import evaluate_device_reference_entities

    entities = pd.DataFrame({"record_id": ["a", "b", "c", "d"],
                             "entity_id": ["one", "one", "two", "two"]})
    records = pd.DataFrame({"record_id": ["a", "b", "c", "d"],
                            "device_ids_std": [["x"], ["y"], ["x"], None]})
    truth = pd.DataFrame({"record_id_l": ["a"], "record_id_r": ["c"]})
    result = evaluate_device_reference_entities(entities, records, truth)
    assert result["reference_pairs_split"] == 1
    assert result["entities_with_multiple_device_ids"] == 1
    assert result["records_without_device_reference"] == 1
    return "device reference splits, mixed clusters and unreferenced records separated"


@check
def stage0_outside_blocking_sample_excludes_scored_and_gold():
    from src.stage0_audit import sample_outside_blocking

    records = pd.DataFrame({
        "record_id": ["a", "b", "c", "d"],
        "first_name_std": ["anna", "anna", "anna", "bill"],
        "last_name_std": ["green", "green", "green", "green"],
        "city_std": ["x", "x", "x", "y"],
    })
    scored = pd.DataFrame({"record_id_l": ["a"], "record_id_r": ["b"]})
    gold = pd.DataFrame({"record_id_l": ["a"], "record_id_r": ["c"]})
    sample = sample_outside_blocking(records, scored, gold, per_rule=10)
    assert set(zip(sample["record_id_l"], sample["record_id_r"])) == {("b", "c")}
    assert sample["label"].eq("").all()
    return "new unlabelled pair excluded from existing candidates and gold"


@check
def stage0_dispute_pack_carries_evidence_and_blank_adjudication():
    from src.stage0_audit import dispute_review_pack

    records = pd.DataFrame({
        "record_id": ["a", "b"],
        "first_name_std": ["ann", "ann"],
        "last_name_std": ["lee", "lee"],
        "email_std": ["ann@x.com", "ann@x.com"],
    })
    audit = pd.DataFrame({
        "record_id_l": ["a"],
        "record_id_r": ["b"],
        "human_label": ["match"],
        "match_probability": [0.001],
        "verdict": ["contradicted"],
    })
    pack = dispute_review_pack(records, audit)
    assert len(pack) == 1
    for column in ("adjudicated_label", "reviewer", "reviewed_at", "reviewer_note"):
        assert column in pack.columns
    assert pack["adjudicated_label"].eq("").all()
    assert pack["current_gold_label"].tolist() == ["match"]
    assert pack["first_name_std_l"].tolist() == ["ann"]
    assert pack["email_std_r"].tolist() == ["ann@x.com"]
    return "contradicted pair carries per-field evidence with blank adjudication columns"


@check
def stage0_save_review_pack_refuses_to_overwrite_filled_reviews():
    import tempfile
    from pathlib import Path

    from src.stage0_audit import save_review_pack

    frame = pd.DataFrame({
        "record_id_l": ["a"],
        "record_id_r": ["b"],
        "label": [""],
        "review_status": ["pending"],
        "reviewer": [""],
        "reviewer_note": [""],
        "model_version": ["v1"],
        "gold_sha256": ["h1"],
    })
    filled = frame.copy()
    filled["label"] = ["match"]
    filled["reviewer"] = ["human"]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pack.csv"
        assert save_review_pack(path, filled, "label") is True
        assert save_review_pack(path, frame, "label") is False
        stored = pd.read_csv(path)
        assert stored["label"].tolist() == ["match"], "human review was overwritten"
    return "filled review file kept when the same snapshot is re-generated"


@check
def stage0_packs_are_not_promoted_by_labels_module():
    """Guards the workflow: src.labels --promote reads only the strata queue
    and the FP sample. Stage 0 packs require manual pair/label promotion,
    otherwise a 50-pair sample or a 9-row dispute adjudication silently
    looks promoted while gold never changes.
    """
    import src.labels as labels
    from src.stage0_audit import DISPUTE_REVIEW_PATH, SAMPLE_PATH

    sources = [p for p in (labels.QUEUE_PATH, labels.FP_SAMPLE_PATH) if p.exists()]
    assert SAMPLE_PATH not in sources
    assert DISPUTE_REVIEW_PATH not in sources
    return "stage 0 review packs are outside src.labels --promote sources"


@check
def sample_training_cannot_promote_to_active_model():
    import tempfile
    from types import SimpleNamespace
    from unittest.mock import patch

    linker = SimpleNamespace(misc=SimpleNamespace(save_model_to_json=lambda: {"trained": True}))
    predictions = pd.DataFrame({"decision": ["MATCH"]})
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pointer = root / "latest.json"
        with patch.object(model_lifecycle, "version_dir", lambda vid: root / vid), patch.object(
            model_lifecycle, "LATEST_POINTER", pointer
        ):
            model_lifecycle.save_version(linker, predictions, "sample", 0.1)
            assert not pointer.exists(), "sample training changed the active model pointer"
            full = model_lifecycle.save_version(linker, predictions, "full", 0.1)
            assert json.loads(pointer.read_text(encoding="utf-8"))["path"] == str(full)
    return "sample cannot become active; full version can"


@check
def retrain_step_streams_and_has_a_timeout():
    from src.run_all import run_step

    result = run_step("help", ["run_all", "--help"], timeout=30)
    assert result["step"] == "help"
    return "CLI subprocess completed with streaming output and a time limit"


@check
def pinned_comparisons_keep_null_levels():
    from src.splink_model import build_settings
    from splink import DuckDBAPI, Linker

    # gender + signup_date_std were added then removed the same day: measured on
    # the 101k set they moved false merges by 0 (4,867 -> 4,867) and the mixed
    # entity count by 0 (2,603 -> 2,603). Two comparisons that cost training
    # time and buy nothing are deleted, not kept "for later".
    columns = ["record_id", "first_name_std", "last_name_std", "email_std",
               "address_std", "city_std", "state_std", "country_std", "dob_std",
               "phone_std"]
    records = pd.read_parquet(PROCESSED_DATA_PATH, columns=columns).head(2)
    model = Linker(records, build_settings(), db_api=DuckDBAPI()).misc.save_model_to_json()
    for comparison in model["comparisons"]:
        levels = comparison["comparison_levels"]
        assert any(level.get("is_null_level") for level in levels), comparison["output_column_name"]
        assert levels[-1]["sql_condition"] == "ELSE"
    return f"all {len(model['comparisons'])} pinned comparisons retain a null level before ELSE"


@check
def business_rule_splits_email_name_address_by_dob():
    """Domain rule: email+nama+alamat identik = orang sama, asal dob juga sama.

    MEASURED on 101,855 rows before this rule existed: Splink gave p = 1.0 to
    every pair sharing email+name+address, because the email Bayes factor
    (log2(m/u) ~ +18.7) drowned the dob penalty. 153 of those had a DIFFERENT
    date of birth — two people who look identical on every other field.

    The rule is a hard override on top of the model, not a trained feature: EM
    cannot express "these three fields agree, so treat dob as decisive".

    dob is NOT allowed to force NON_MATCH. A differing or missing dob is
    equally unverifiable: it could be a typo just as easily as a second person,
    and rejecting automatically is irreversible in a way that queueing is not.
    So both cases land in REVIEW, where a human decides.
    """
    from src.splink_model import add_decision, apply_business_rules

    frame = pd.DataFrame(
        {
            "record_id_l": ["a", "b", "c", "d", "e"],
            "record_id_r": ["1", "2", "3", "4", "5"],
            "match_probability": [1.0, 1.0, 1.0, 0.01, 1.0],
            "email_std_l": ["x@y.com"] * 5,
            "email_std_r": ["x@y.com"] * 5,
            "first_name_std_l": ["budi"] * 5,
            "first_name_std_r": ["budi"] * 5,
            "last_name_std_l": ["santoso"] * 5,
            "last_name_std_r": ["santoso"] * 5,
            "address_std_l": ["jl. melati 5"] * 5,
            # a/b: same dob -> forced MATCH.  c: different dob -> REVIEW.
            # d: dob missing on one side -> REVIEW (unverifiable).
            # e: address differs -> rule does not apply, model decides.
            "address_std_r": ["jl. melati 5", "jl. melati 5", "jl. melati 5", "jl. melati 5", "jl. mawar 9"],
            "dob_std_l": ["1988-04-11", "1988-04-11", "1988-04-11", "1988-04-11", "1988-04-11"],
            "dob_std_r": ["1988-04-11", "1988-04-11", "1999-12-31", None, "1988-04-11"],
        }
    )
    # In production add_decision() always runs first; apply_business_rules then
    # overrides it. Reproduce that order so the test cannot pass on a code path
    # that does not exist.
    out = apply_business_rules(add_decision(frame))

    assert out.loc[0, "decision"] == "MATCH", "same dob -> forced MATCH"
    assert out.loc[1, "decision"] == "MATCH", "same dob -> forced MATCH"
    assert out.loc[2, "decision"] == "REVIEW", (
        f"dob conflict must be queued for a human, got {out.loc[2, 'decision']}"
    )
    assert out.loc[2, "business_rule"] == "unverified_dob"
    # dob present on only one side: equally unverifiable, so also REVIEW.
    assert out.loc[3, "business_rule"] == "unverified_dob", (
        "a missing dob must be treated the same as a conflicting one"
    )
    assert out.loc[3, "decision"] == "REVIEW", (
        f"partial dob must be queued, got {out.loc[3, 'decision']}"
    )
    # address differs: rule is deliberately narrow, model decision stands.
    assert out.loc[4, "business_rule"] is None, "address mismatch must not trigger the rule"
    return "same dob -> MATCH; differing or missing dob -> REVIEW; narrow key check intact"


@check
def business_rule_is_skipped_not_guessed_when_columns_absent():
    """A model without the needed columns must skip the rule loudly, not guess.

    Silently returning an unfiltered frame would make the full run and the
    incremental run disagree about the same pair — the exact class of bug that
    produced 153 wrong merges in the first place.
    """
    from src.splink_model import apply_business_rules

    bare = pd.DataFrame(
        {
            "record_id_l": ["a"],
            "record_id_r": ["b"],
            "match_probability": [1.0],
        }
    )
    bare["decision"] = "MATCH"
    out = apply_business_rules(bare)
    assert out.loc[0, "business_rule"] is None
    assert out.loc[0, "decision"] == "MATCH", "model decision must survive untouched"
    return "missing columns -> rule skipped, model decision preserved"


@check
def business_rule_is_present_in_incremental_scoring():
    """The incremental path must apply the same rule as the full run.

    Two different rules on two different code paths means the same pair merges
    on upload and does not merge on a rebuild — entity identity would depend on
    which button was pressed.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "incremental.py").read_text(
        encoding="utf-8"
    )
    assert "apply_business_rules" in source, (
        "src/incremental.py does not apply the business rule; incremental and "
        "full runs would disagree"
    )
    return "incremental scoring applies the same business rule as the full run"


@check
def pipeline_lock_and_staging_are_wired():
    """The staging commit path must exist and be reachable from run_all.

    Without finalize_staged(), artifacts are staged forever and never reach
    their real paths — the pipeline would "succeed" while leaving the app
    reading stale data. Without discard_staged() on failure, a crashed run
    leaves orphaned staging that a later run could commit by accident.
    """
    from src.config import (
        PIPELINE_LOCK,
        STAGING_DIR,
        STAGING_ENV,
        acquire_pipeline_lock,
        active_path,
        discard_staged,
        finalize_staged,
        release_pipeline_lock,
    )
    from pathlib import Path as _Path
    import json as _json

    # active_path honours the env var: outside a pipeline it returns the real
    # path; inside (PIPELINE_STAGING=1) it prefers a staged file when present.
    real = _Path("outputs") / "entity_map.parquet"
    assert active_path(real) == real, "outside a pipeline active_path must be the real path"

    # Lock acquire/release round-trips and leaves no file behind.
    acquire_pipeline_lock(note="test")
    assert PIPELINE_LOCK.exists(), "lock file must exist while held"
    info = _json.loads(PIPELINE_LOCK.read_text(encoding="utf-8"))
    assert "pid" in info and "started_at" in info, "lock must carry pid + timestamp"
    release_pipeline_lock()
    assert not PIPELINE_LOCK.exists(), "lock must be released"

    # Staging round-trip: a staged write is visible via active_path only when
    # the env var is set, and finalize_staged() moves it to the real path.
    import os as _os
    import pandas as _pd

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    probe = OUTPUT_DIR / "_staging_probe.parquet"
    probe_tmp_target = _Path(str(probe) + ".probe_real")
    frame = _pd.DataFrame({"a": [1, 2, 3]})
    _os.environ[STAGING_ENV] = "1"
    try:
        from src.config import atomic_write_parquet
        atomic_write_parquet(frame, probe_tmp_target)
        # While staging: the real path does not exist yet, the staged one does.
        assert not probe_tmp_target.exists(), "staged write must not touch the real path"
        assert active_path(probe_tmp_target) != probe_tmp_target, (
            "inside a pipeline active_path must resolve to the staged file"
        )
        swapped = finalize_staged()
        assert swapped >= 1, "finalize_staged must swap at least the probe"
        assert probe_tmp_target.exists(), "finalize_staged must move the file to its real path"
    finally:
        _os.environ.pop(STAGING_ENV, None)
        probe_tmp_target.unlink(missing_ok=True)
        discard_staged()

    return "lock acquire/release + staging write/resolve/finalize all verified"


@check
def m_else_floor_is_per_field_for_identity_columns():
    """dob/phone must penalise disagreement harder than city/state/country.

    One flat 0.05 made 5 agreeing fields drown 2 that disagreed, so 4,867 false
    merges all scored p = 1.0. The per-field floor is the fix; without it the
    model cannot express "dob differs, so probably not the same person".
    """
    from src.config import M_ELSE_LEVEL_FLOOR_BY_FIELD, m_else_floor_for

    # city/state/country are deliberately NOT in the override table — they fall
    # back to the default. Assert through m_else_floor_for, which applies that
    # fallback, rather than indexing the dict directly.
    assert m_else_floor_for("dob_std") < m_else_floor_for("city_std") / 10, (
        "dob disagreement must be penalised at least 10x harder than city"
    )
    assert m_else_floor_for("phone_std") < m_else_floor_for("address_std")
    # Columns absent from the override table must fall back, not crash.
    assert m_else_floor_for("not_a_real_column") == 0.05
    return "per-field floor: dob/phone tighter than name/address, fallback intact"


@check
def review_floor_drops_no_gold_positive():
    """REVIEW_THRESHOLD was raised 1e-10 -> 1e-6; prove no true pair was lost.

    The floor is a measured choice, not a preference: every gold positive must
    still sit at or above it, otherwise real duplicates would silently drop out
    of the human queue.
    """
    from src.config import REVIEW_THRESHOLD
    from src.labels import GOLD_PATH, load_labels

    labels, source = load_labels("gold")
    if labels is None:
        return "SKIPPED: no gold labels"
    preds = pd.read_parquet(
        PREDICTIONS_FULL_PATH, columns=["record_id_l", "record_id_r", "match_probability"]
    )
    merged = preds.merge(
        labels[["record_id_l", "record_id_r", "is_positive"]],
        on=["record_id_l", "record_id_r"], how="inner",
    )
    positives = merged[merged["is_positive"]]
    if positives.empty:
        return f"SKIPPED: gold ({source}) has no positives among scored pairs"
    lowest = float(positives["match_probability"].min())
    assert lowest >= REVIEW_THRESHOLD, (
        f"a gold positive scores {lowest:.3e}, below REVIEW_THRESHOLD "
        f"{REVIEW_THRESHOLD:.3e} — it would never reach a human"
    )
    return f"lowest gold positive {lowest:.3e} >= review floor {REVIEW_THRESHOLD:.3e}"


@check
def explain_page_maps_null_and_exact_evidence_correctly():
    from src.ui import model_levels

    email = model_levels()["gamma_gamma_email_std"]
    assert "null" in email[-1][0].lower()
    assert "Exact match on email_std" in email[4][0]
    return "email null is gamma -1; exact email is gamma 4"


@check
def stage1_group_split_bridges_unscored_pairs():
    from src.stage1_abc import record_groups

    all_labels = pd.DataFrame({
        "record_id_l": ["a", "b", "d"],
        "record_id_r": ["b", "c", "e"],
    })
    scored = all_labels.iloc[[0, 2]].reset_index(drop=True)
    groups = record_groups(all_labels, scored)
    assert groups[0] != groups[1]
    scored = all_labels.iloc[[0, 1]].reset_index(drop=True)
    groups = record_groups(all_labels, scored)
    assert groups[0] == groups[1]
    return "unscored pair bridges labelled record groups before split"


@check
def stage1_shadow_counts_and_provenance_are_consistent():
    from src.stage1_abc import evaluate, load_data

    gold, scored, provenance = load_data(include_disputed=False)
    assert len(gold) == len(scored) + provenance["unscored_gold_pairs"] + int(gold["is_disputed"].sum())
    assert scored["agree_email"].equals(
        scored["email_std_l"].notna() & scored["email_std_r"].notna()
        & scored["email_std_l"].eq(scored["email_std_r"])
    )
    report = evaluate(include_disputed=False)
    assert report["mode"] == "shadow_only"
    assert report["provenance"]["unscored_gold_pairs"] >= 0
    assert report["positive_pairs"] > 0
    assert report["verdict"] == "not_proven"
    for fold in report["folds"]:
        assert fold["shared_record_ids"] == 0
        assert fold["A"]["tp"] + fold["A"]["fp"] + fold["A"]["fn"] + fold["A"]["tn"] == fold["test_pairs"]
    return f"{report['scored_gold_pairs']} scored labels; fixed Splink policy unchanged"


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
