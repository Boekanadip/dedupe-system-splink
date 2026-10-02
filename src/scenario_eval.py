"""Scenario-based evaluation: the cases a reviewer/mentor actually asks about.

The four-layer report (src/evaluate) answers "is the pipeline correct overall".
It does not answer case questions like "what does the system do when the email
is identical but the name differs?". This module answers those with measured
decision counts from the full predictions, plus the two external references that
already exist (blocking coverage of known duplicates, stress-test typo recovery).

Every scenario reports decision counts (MATCH/REVIEW/NON_MATCH) and states what
it does NOT prove. Numbers are counts, not accuracy claims: without a truth
label per pair, a decision distribution shows BEHAVIOUR, not correctness.

Run: python -m src.scenario_eval
Output: outputs/scenario_evaluation.json (+ printed table)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import OUTPUT_DIR, PROCESSED_DATA_PATH, predictions_path, read_meta
from .eval_truth import device_truth_pairs
from .labels import agree_fields

REPORT_PATH = OUTPUT_DIR / "scenario_evaluation.json"


def decision_counts(frame: pd.DataFrame) -> dict:
    counts = frame["decision"].value_counts().to_dict()
    total = len(frame)
    return {
        "pairs": total,
        "MATCH": int(counts.get("MATCH", 0)),
        "REVIEW": int(counts.get("REVIEW", 0)),
        "NON_MATCH": int(counts.get("NON_MATCH", 0)),
    }


def build() -> dict:
    preds = pd.read_parquet(predictions_path(full=True))
    records = pd.read_parquet(PROCESSED_DATA_PATH)
    agree = agree_fields(records, preds[["record_id_l", "record_id_r"]])
    preds = preds.merge(agree, on=["record_id_l", "record_id_r"], how="left")

    # Splink's predict() already carries the side-by-side values (dob_std_l/r).
    dob_both = preds["dob_std_l"].notna() & preds["dob_std_r"].notna()

    scenarios: dict[str, dict] = {}

    # S1 — identical email, different name: shared inbox, nicknames, data entry
    # by a spouse/assistant. The risky direction is auto-MATCH.
    s1 = preds[preds["agree_email"] & ~preds["agree_name"]]
    scenarios["email_sama_nama_beda"] = {
        "question": "email sama tapi nama beda — apakah dianggap match?",
        "result": decision_counts(s1),
        "does_not_prove": "whether each decision is correct; needs human labels (review pack stratum)",
    }

    # S2 — records with no email AND no phone can never be blocked on those two
    # keys: a structural recall ceiling, not a model decision.
    no_contact = records["email_std"].isna() & records["phone_std"].isna()
    ids_no_contact = set(records.loc[no_contact, "record_id"])
    entities = pd.read_parquet("outputs/entity_map.parquet")
    sizes = entities.groupby("entity_id")["record_id"].transform("size")
    single = set(entities.loc[sizes == 1, "record_id"])
    scenarios["tanpa_email_dan_telepon"] = {
        "question": "record tanpa email & telepon — bisa dicari duplikatnya?",
        "result": {
            "records": int(no_contact.sum()),
            "of_which_singletons": len(ids_no_contact & single),
        },
        "does_not_prove": "that they ARE unique — blocking never generates them as candidates",
    }

    # S3 — same full name but a real dob conflict: the classic "different people"
    # case. Auto-MATCH here would be a false merge signal.
    s3 = preds[preds["agree_name"] & dob_both & ~preds["agree_dob"]]
    scenarios["nama_sama_tanggal_lahir_beda"] = {
        "question": "nama sama tapi dob beda — sistem tetap merge?",
        "result": decision_counts(s3),
        "does_not_prove": "correctness per pair; a shared dob alone is also a collision risk (see evaluation_report blocking layer)",
    }

    # S4 — known duplicates (device answer key) that never became candidates:
    # the hard recall ceiling of blocking.
    truth = device_truth_pairs(records)
    if truth.empty:
        scenarios["duplikat_lolos_blocking"] = {
            "question": "pasangan duplikat pasti tidak pernah jadi kandidat?",
            "result": {"status": "unavailable", "reason": "no device_id channel"},
            "does_not_prove": "n/a",
        }
    else:
        keys = pd.MultiIndex.from_frame(preds[["record_id_l", "record_id_r"]])
        missed = int((~pd.MultiIndex.from_frame(truth).isin(keys)).sum())
        scenarios["duplikat_lolos_blocking"] = {
            "question": "pasangan duplikat pasti tidak pernah jadi kandidat?",
            "result": {"truth_pairs": len(truth), "never_candidates": missed},
            "does_not_prove": "fuzzy duplicates beyond the device answer key",
        }

    # S5 — typo recovery is measured by the stress test, not re-derived here.
    stress_path = OUTPUT_DIR / "stress_test.json"
    if stress_path.exists():
        stress = json.loads(stress_path.read_text(encoding="utf-8"))
        scenarios["typo_ternyata"] = {
            "question": "duplikat yang sengaja dirusak typo — ketemu?",
            "result": stress.get("summary", stress),
            "does_not_prove": "recovery on real client data; corruption is synthetic and documented",
        }
    else:
        scenarios["typo_ternyata"] = {
            "question": "duplikat yang sengaja dirusak typo — ketemu?",
            "result": {"status": "unavailable", "reason": "run python -m src.stress_test --pairs 200"},
            "does_not_prove": "n/a",
        }

    # S6 — all four strong identifiers agree: sanity direction of the policy.
    s6 = preds[preds["agree_name"] & preds["agree_email"] & preds["agree_dob"] & preds["agree_phone"]]
    scenarios["nama_email_dob_telepon_sama"] = {
        "question": "4 identitas kuat sama — seharusnya MATCH?",
        "result": decision_counts(s6),
        "does_not_prove": "precision of those MATCH decisions (see the 100-pair precision sample)",
    }

    meta = read_meta(predictions_path(full=True))
    return {
        "generated_at": pd.Timestamp.utcnow().isoformat(timespec="seconds"),
        "model_version": meta.get("model_version"),
        "scenarios": scenarios,
        "note": (
            "Decision counts measure behaviour, not accuracy. Accuracy claims come "
            "from gold labels (threshold_evaluation_gold.json) and the review pack."
        ),
    }


def main() -> None:
    # Windows consoles default to cp1252, which mangles UTF-8 question strings.
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = build()
    print(f"Model: {report.get('model_version') or 'n/a'}")
    print(f"{'scenario':38s} {'pairs':>8s} {'MATCH':>8s} {'REVIEW':>8s} {'NON_MATCH':>10s}")
    for name, body in report["scenarios"].items():
        r = body["result"]
        if "pairs" in r:
            print(f"{name:38s} {r['pairs']:8,d} {r['MATCH']:8,d} {r['REVIEW']:8,d} {r['NON_MATCH']:10,d}")
        else:
            print(f"{name:38s} {r}")
        print(f"  -> {body['question']}")
        print(f"  not proven: {body['does_not_prove']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
