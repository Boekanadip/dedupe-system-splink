
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .config import (
    ENTITY_MAP_PATH,
    MATCH_THRESHOLD,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    REVIEW_THRESHOLD,
    SMOKE_SAMPLE_SIZE,
    predictions_path,
    read_meta,
    atomic_write_parquet,
    atomic_write_json,
    active_path,
)
from .eval_truth import (
    device_truth_pairs,
    match_edges,
    records_with_device,
    rule_coverage,
    score,
)

REPORT_PATH = OUTPUT_DIR / "evaluation_report.json"

TRUTH_CAVEAT = (
    "device_ids_std is 1:1 with customer_id on this dataset, so it is the answer "
    "key rather than independent evidence. Agreement proves the pipeline "
    "reproduces the source grouping; it proves nothing about fuzzy duplicates or "
    "any other dataset."
)


def truth_independence(df: pd.DataFrame) -> dict:
    """Hitung apakah kanal acuan benar-benar independen, bukan sekadar klaim.

    Selama ini "device_ids_std 1:1 dengan customer_id" hanya ditulis sebagai
    kalimat di TRUTH_CAVEAT. Kalimat dapat basi setelah data berubah; angka ini
    dihitung ulang tiap run, sehingga laporan tahu sendiri kapan recall-vs-device
    berhenti menjadi bukti dan menjadi penulisan ulang customer_id.

    Status 'answer_key' berarti kanal itu tidak boleh dikutip sebagai akurasi.
    Kanal independen yang tersedia saat ini adalah label hasil tinjauan manusia
    (lihat decision.gold_comparison) — dihasilkan tanpa membaca device_id.
    """
    missing = {"device_ids_std", "customer_id"} - set(df.columns)
    if missing:
        return {
            "status": "unavailable",
            "reason": f"missing columns: {sorted(missing)}",
        }

    ids = (
        df[["record_id", "device_ids_std", "customer_id"]]
        .explode("device_ids_std")
        .dropna(subset=["device_ids_std", "customer_id"])
    )
    ids = ids[ids["device_ids_std"].astype(str).str.len() > 0]
    if ids.empty:
        return {"status": "unavailable", "reason": "no record carries both device and customer id"}

    devices_per_customer = ids.groupby("customer_id")["device_ids_std"].nunique()
    customers_per_device = ids.groupby("device_ids_std")["customer_id"].nunique()
    one_to_one = bool(
        (devices_per_customer <= 1).all() and (customers_per_device <= 1).all()
    )
    return {
        "status": "measured",
        "records_with_device": int(ids["record_id"].nunique()),
        "distinct_customer_id": int(ids["customer_id"].nunique()),
        "distinct_device_id": int(ids["device_ids_std"].nunique()),
        "customers_with_two_devices": int((devices_per_customer > 1).sum()),
        "devices_shared_by_two_customers": int((customers_per_device > 1).sum()),
        "one_to_one": one_to_one,
        "consequence": (
            "ANSWER KEY: the device channel repeats customer_id, so recall/precision "
            "against it measures whether the pipeline reproduces the source grouping. "
            "Cite decision.gold_comparison for an independent accuracy figure."
            if one_to_one
            else "NOT 1:1 with customer_id — the device channel carries information "
            "the source id does not, so it can serve as independent evidence."
        ),
    }


def _unavailable(what: str, why: str) -> dict:
    return {"status": "unavailable", "what": what, "reason": why}


# --------------------------------------------------------------------------
# Lapisan 1 — blocking
# --------------------------------------------------------------------------
def evaluate_blocking(df: pd.DataFrame, truth: pd.DataFrame, full: bool = True) -> dict:
    preds_path = active_path(predictions_path(full=full))
    if truth.empty:
        return _unavailable(
            "blocking coverage of true duplicate pairs",
            "no device_id channel in this dataset",
        )
    if not preds_path.exists():
        return _unavailable("blocking coverage", f"{preds_path.name} not found")

    candidates = pd.read_parquet(preds_path, columns=["record_id_l", "record_id_r"])
    candidate_pairs = len(candidates)
    rule_rows = rule_coverage(df, truth)
    union_covered = len(truth.merge(candidates.drop_duplicates(),
                                    on=["record_id_l", "record_id_r"], how="inner"))

    return {
        "status": "measured",
        "reference_pairs": len(truth),
        "candidate_pairs": candidate_pairs,
        "truth_pairs_generated_as_candidates": union_covered,
        "truth_pairs_never_generated": len(truth) - union_covered,
        "blocking_recall_ceiling": round(union_covered / len(truth), 6) if len(truth) else None,
        "per_rule": rule_rows.to_dict(orient="records"),
        "proves": "candidate generation contains the true duplicate pairs",
        "does_not_prove": (
            "how the model scores them, and whether the pair should be merged — "
            "those are layers 2 and 4"
        ),
    }


# --------------------------------------------------------------------------
# Lapisan 2 — linkage
# --------------------------------------------------------------------------
def _score_distribution(preds: pd.DataFrame) -> dict:
    """Apakah skor model memiliki rentang nilai?

    Sebelum batas bawah m ditetapkan, semua pasangan non-match memiliki skor
    identik (-996.578428, simpangan baku 2.3e-13), sehingga rentang review tidak
    mungkin terbentuk. Satu nilai berbeda di antara 292 ribu pasangan menjadi
    tanda kegagalan tersebut dan merupakan fakta lapisan linkage yang tetap
    dapat dilaporkan tanpa kanal acuan.
    """
    non_match = preds[preds["match_probability"] < MATCH_THRESHOLD]
    return {
        "candidate_pairs": len(preds),
        "distinct_match_weights": int(non_match["match_weight"].nunique())
        if "match_weight" in non_match.columns and len(non_match)
        else 0,
        "non_match_weight_min": round(float(non_match["match_weight"].min()), 3)
        if len(non_match) and "match_weight" in non_match.columns
        else None,
        "non_match_weight_max": round(float(non_match["match_weight"].max()), 3)
        if len(non_match) and "match_weight" in non_match.columns
        else None,
        "pairs_in_review_band": int(
            ((non_match["match_probability"] >= REVIEW_THRESHOLD)
             & (non_match["match_probability"] < MATCH_THRESHOLD)).sum()
        )
        if len(non_match)
        else 0,
        "pairs_at_probability_one": int((preds["match_probability"] >= 1.0).sum()),
    }


def evaluate_linkage(
    truth: pd.DataFrame,
    threshold: float,
    device_records: set[str],
    full: bool = True,
) -> dict:
    preds_path = active_path(predictions_path(full=full))
    if not preds_path.exists():
        return _unavailable("linkage scoring", f"{preds_path.name} not found")

    available = set(pd.read_parquet(preds_path).columns)
    wanted = [
        c
        for c in ("record_id_l", "record_id_r", "match_probability", "match_weight")
        if c in available
    ]
    preds = pd.read_parquet(preds_path, columns=wanted)

    if truth.empty:
        # Tanpa kanal acuan, sebaran skor tetap dapat dilaporkan: ini menunjukkan
        # apakah model mampu menyatakan tingkat ketidakpastian.
        return {
            "status": "unavailable",
            "what": "does the model score true pairs correctly",
            "reason": "no device_id channel in this dataset",
            "score_distribution": _score_distribution(preds),
            "proves": "whether the score distribution has any gradient",
            "does_not_prove": "any accuracy figure",
        }

    edges = match_edges(preds, threshold)
    result = score(truth, edges, threshold, device_records)
    distribution = preds.merge(truth, on=["record_id_l", "record_id_r"], how="inner")
    return {
        "status": "measured",
        "threshold": threshold,
        "truth_pairs": result["truth_pairs"],
        "truth_pairs_scored_above_threshold": result["matched_truth_pairs"],
        "truth_pairs_scored_below_threshold": result["missed_truth_pairs"],
        "match_edges": result["match_edges"],
        "false_merges": result["false_merges"],
        "unverifiable_edges": result["unverifiable_edges"],
        "recall_on_truth": result["recall"],
        "precision_on_truth": result["precision"],
        "truth_probability_min": float(distribution["match_probability"].min())
        if len(distribution)
        else None,
        "score_distribution": _score_distribution(preds),
        "proves": "the model scores true pairs above the threshold and rejects others",
        "does_not_prove": (
            "that true pairs exist beyond those the truth channel can see — the "
            "answer-key caveat applies to every number here"
        ),
    }


# --------------------------------------------------------------------------
# Lapisan 3 — keputusan
# --------------------------------------------------------------------------
def evaluate_decision(full: bool) -> dict:
    preds_path = active_path(predictions_path(full=full))
    if not preds_path.exists():
        return _unavailable("decision rates", f"{preds_path.name} not found")

    preds = pd.read_parquet(preds_path)
    total = len(preds)
    if "decision" not in preds.columns:
        return _unavailable(
            "decision rates",
            "predictions have no 'decision' column; re-run src.splink_model",
        )

    counts = preds["decision"].value_counts().to_dict()
    rates = {
        "auto_match_rate": round(counts.get("MATCH", 0) / total, 6) if total else None,
        "review_rate": round(counts.get("REVIEW", 0) / total, 6) if total else None,
        "non_match_rate": round(counts.get("NON_MATCH", 0) / total, 6) if total else None,
    }

    report = {
        "status": "measured",
        "thresholds": {
            "match": MATCH_THRESHOLD,
            "review": REVIEW_THRESHOLD,
            "policy": "P >= match -> MATCH; review <= P < match -> REVIEW; P < review -> NON_MATCH",
        },
        "candidate_pairs": total,
        "counts": counts,
        "rates": rates,
        "review_volume_per_run": counts.get("REVIEW", 0),
        "proves": "how much human review this policy would actually generate",
        "does_not_prove": "that the MATCH ones are right — see the gold section",
        "gold_comparison": _gold_section(),
    }
    return report


def _gold_section() -> dict:
    from .labels import GOLD_PATH, load_labels

    labels, source = load_labels()
    if labels is None or source != "gold":
        return {"status": "unavailable", "reason": "no gold labels yet"}

    positives = int(labels["is_positive"].sum())
    negatives = len(labels) - positives
    section = {
        "status": "measured",
        "source": "gold (human reviewed)",
        "reviewed_pairs": len(labels),
        "positives": positives,
        "negatives": negatives,
        "note": (
            "The review sample is stratified by the model's own behaviour, so a "
            "rate from it does not extrapolate to the whole candidate population."
        ),
    }
    if negatives == 0 or positives == 0:
        section["usable_for"] = "one-sided only"
        section["caveat"] = (
            "One class only. With no negatives, precision cannot be estimated; "
            "with no positives, recall cannot. Report n, not a rate."
        )
    else:
        section["usable_for"] = "precision and recall"
    return section


# --------------------------------------------------------------------------
# Lapisan 4 — entity
# --------------------------------------------------------------------------
def evaluate_entity(
    truth: pd.DataFrame,
    record_ids: set[str] | None = None,
) -> dict:
    if not active_path(ENTITY_MAP_PATH).exists():
        return _unavailable("entity evaluation", "entity_map.parquet not found")

    entities = pd.read_parquet(active_path(ENTITY_MAP_PATH))[["record_id", "entity_id"]]
    if record_ids is not None:
        entities = entities[entities["record_id"].isin(record_ids)]
    lookup = entities.set_index("record_id")["entity_id"]
    sizes = entities.groupby("entity_id").size()

    base = {
        "status": "measured",
        "records": len(entities),
        "entities": int(sizes.size),
        "records_merged_away": int(len(entities) - sizes.size),
        "cluster_size_distribution": {
            str(int(k)): int(v) for k, v in sizes.value_counts().sort_index().items()
        },
        "multi_record_entities": int((sizes > 1).sum()),
        "largest_entity": int(sizes.max()),
    }

    if truth.empty:
        base["truth_pairs_in_one_entity"] = None
        base["does_not_prove"] = "cluster correctness: no truth channel in this dataset"
        return base

    joined = truth.assign(
        entity_l=truth["record_id_l"].map(lookup),
        entity_r=truth["record_id_r"].map(lookup),
    )
    together = int((joined["entity_l"] == joined["entity_r"]).sum())

    # Pemeriksaan arah sebaliknya: entity yang memuat dua device id berbeda
    # merupakan salah gabung, yang tidak terdeteksi oleh pemeriksaan apakah
    # pasangan sejati berada dalam kelompok yang sama.
    records = pd.read_parquet(
        active_path(PROCESSED_DATA_PATH), columns=["record_id", "device_ids_std"]
    )
    if record_ids is not None:
        records = records[records["record_id"].isin(record_ids)]
    if records["device_ids_std"].dropna().empty:
        mixed = None
    else:
        ids = records.explode("device_ids_std").dropna(subset=["device_ids_std"])
        per_entity = ids.assign(entity_id=ids["record_id"].map(lookup)).groupby("entity_id")[
            "device_ids_std"
        ].nunique()
        mixed = int((per_entity > 1).sum())

    base.update(
        {
            "truth_pairs_in_one_entity": together,
            "truth_pairs_split_across_entities": len(truth) - together,
            "entities_mixing_two_device_ids": mixed,
            "proves": "records of one real entity ended up in one entity_id",
            "does_not_prove": (
                "that no two different people were merged — only that no entity "
                "holds two known identities"
            ),
        }
    )
    return base


def build(full: bool = True) -> dict:
    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    if not full and len(df) > SMOKE_SAMPLE_SIZE:
        df = df.head(SMOKE_SAMPLE_SIZE).copy()
    truth = device_truth_pairs(df)

    meta = read_meta(predictions_path(full=full))
    report = {
        "generated_at": pd.Timestamp.utcnow().isoformat(timespec="seconds"),
        "scope": "full" if full else "sample",
        "model_version": meta.get("model_version"),
        "trained": meta.get("trained"),
        "truth_channel": {
            "source": "device_ids_std",
            "available": not truth.empty,
            "truth_pairs": len(truth),
            "independence": (
                truth_independence(df)
                | (
                    {"scope_note": "checked on the smoke subset, not the full dataset"}
                    if not full
                    else {}
                )
            ),
            "independent_channel": (
                "gold_labels (human reviewed) — see decision.gold_comparison"
            ),
            "caveat": TRUTH_CAVEAT,
        },
        "blocking": evaluate_blocking(df, truth, full=full),
        "linkage": evaluate_linkage(
            truth, MATCH_THRESHOLD, records_with_device(df), full=full
        ),
        "decision": evaluate_decision(full),
        "entity": evaluate_entity(truth, set(df["record_id"])),
    }

    runtime = read_meta(ENTITY_MAP_PATH)
    report["runtime"] = {
        "entity_map_training_seconds": runtime.get("runtime_seconds"),
        "note": "per-step timings for the full run are in outputs/run_summary.json",
    }
    return report


def _show(value, width: int = 38) -> str:
    """Tampilkan nilai dalam satu baris agar dict bertingkat tidak terbungkus."""
    if isinstance(value, dict):
        return ", ".join(f"{k}={v}" for k, v in list(value.items())[:4]) + (
            f", +{len(value) - 4} more" if len(value) > 4 else ""
        )
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _print_layer(name: str, layer: dict) -> None:
    print(f"\n{'=' * 70}\n{name.upper()}\n{'=' * 70}")
    if layer.get("status") != "measured":
        print(f"  status    : {layer.get('status')} — {layer.get('reason') or layer.get('what')}")
        if "score_distribution" in layer:
            for key, value in layer["score_distribution"].items():
                print(f"  {key:38s} {_show(value)}")
        return

    for key, value in layer.items():
        if key in ("proves", "does_not_prove", "per_rule", "gold_comparison"):
            continue
        text = _show(value)
        if len(text) > 120:
            text = text[:117] + "..."
        print(f"  {key:38s} {text}")

    gold = layer.get("gold_comparison")
    if gold and gold.get("status") == "measured":
        print(f"  {'gold':38s} {_show(gold)}")
        if gold.get("caveat"):
            print(f"  {'gold caveat':38s} {gold['caveat']}")
    elif gold:
        print(f"  {'gold':38s} {gold.get('reason', gold.get('status'))}")
    print(f"  proves    : {layer.get('proves', '-')}")
    print(f"  NOT prove : {layer.get('does_not_prove', '-')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate blocking, linkage, decision and entity separately (DESIGN section 17)."
    )
    parser.add_argument("--sample", action="store_true", help="Evaluate the sample scope.")
    args = parser.parse_args()

    report = build(full=not args.sample)

    truth = report["truth_channel"]
    print(f"Model version : {report.get('model_version') or 'n/a'} (trained={report.get('trained')})")
    print(
        f"Truth channel : {truth['source']} — "
        f"{'available, ' + format(truth['truth_pairs'], ',') + ' pairs' if truth['available'] else 'UNAVAILABLE'}"
    )
    if truth["available"]:
        print(f"  caveat: {truth['caveat']}")
    indep = truth.get("independence") or {}
    if indep.get("status") == "measured":
        print(
            "  independence: one_to_one={one} ({dev:,} devices / {cid:,} customers) "
            "-> {verdict}".format(
                one=indep["one_to_one"],
                dev=indep["distinct_device_id"],
                cid=indep["distinct_customer_id"],
                verdict=(
                    "ANSWER KEY — do not cite as accuracy"
                    if indep["one_to_one"]
                    else "independent of customer_id"
                ),
            )
        )
        print(f"  independent channel: {truth.get('independent_channel')}")

    for name in ("blocking", "linkage", "decision", "entity"):
        _print_layer(name, report[name])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report, REPORT_PATH)
    print(f"\nSaved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
