from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_fscore_support
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import MATCH_THRESHOLD, OUTPUT_DIR, RANDOM_SEED, predictions_path, read_meta
from .label_audit import audit as audit_gold_against_device
from .labels import GOLD_PATH, normalise_label
from .registry import sha256_of

GAMMAS = [
    f"gamma_gamma_{field}" for field in (
        "first_name_std", "last_name_std", "email_std", "phone_std", "dob_std",
        "address_std", "city_std", "state_std", "country_std",
    )
]
AGREEMENTS = ["agree_email", "agree_phone", "agree_dob", "agree_name", "agree_city"]
FEATURES = {
    "A": ["match_probability"],
    "B": ["log10_match_probability", "match_weight"],
    "C": ["log10_match_probability", "match_weight", *GAMMAS, *AGREEMENTS],
}


class Components:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def root(self, value: str) -> str:
        self.parent.setdefault(value, value)
        node = value
        while node != self.parent[node]:
            node = self.parent[node]
        while value != node:
            self.parent[value], value = node, self.parent[value]
        return node

    def add_pair(self, left: str, right: str) -> None:
        left, right = self.root(left), self.root(right)
        if left != right:
            self.parent[right] = left


def record_groups(all_labels: pd.DataFrame, scored_labels: pd.DataFrame) -> np.ndarray:
    graph = Components()
    for left, right in all_labels[["record_id_l", "record_id_r"]].itertuples(index=False, name=None):
        graph.add_pair(str(left), str(right))
    return np.array([graph.root(str(left)) for left in scored_labels["record_id_l"]])


def features_for(pairs: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(index=pairs.index)
    frame["log10_match_probability"] = np.log10(pairs["match_probability"].clip(lower=1e-300))
    frame["match_weight"] = pairs["match_weight"]
    for col in GAMMAS:
        frame[col] = pd.to_numeric(pairs[col], errors="raise").fillna(-1)
    for col in AGREEMENTS:
        frame[col] = pairs[col].astype("string").str.lower().map({"true": 1, "false": 0}).fillna(-1).astype(int)
    return frame


def counts(y: np.ndarray, pred: np.ndarray) -> dict:
    return {
        "tp": int(((y == 1) & (pred == 1)).sum()),
        "fp": int(((y == 0) & (pred == 1)).sum()),
        "fn": int(((y == 1) & (pred == 0)).sum()),
        "tn": int(((y == 0) & (pred == 0)).sum()),
    }


def metrics(y: np.ndarray, score: np.ndarray, threshold: float) -> dict:
    pred = (score >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y, pred, average="binary", zero_division=0
    )
    return {
        **counts(y, pred),
        "threshold": float(threshold),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "pr_auc": round(float(average_precision_score(y, score)), 4) if y.any() else None,
    }


def train_threshold(y: np.ndarray, scores: np.ndarray) -> float:
    candidates = np.unique(scores)
    best_threshold = 0.5
    best_f1 = -1.0
    for threshold in candidates:
        _, _, f1, _ = precision_recall_fscore_support(
            y, scores >= threshold, average="binary", zero_division=0
        )
        if f1 > best_f1:
            best_threshold, best_f1 = float(threshold), float(f1)
    return best_threshold


def load_data(include_disputed: bool) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    pred_path = predictions_path(full=True)
    meta = read_meta(pred_path)
    if meta.get("scope") != "full":
        raise ValueError("Full-scope predictions with provenance are required")
    gold_sha256 = sha256_of(GOLD_PATH)
    predictions_sha256 = sha256_of(pred_path)
    gold = pd.read_csv(GOLD_PATH, sep=None, engine="python")
    required = {"record_id_l", "record_id_r", "label"}
    if missing := required - set(gold.columns):
        raise ValueError(f"Gold labels lack fields: {sorted(missing)}")
    gold = gold[["record_id_l", "record_id_r", "label"]].copy()
    gold["record_id_l"], gold["record_id_r"] = (
        gold[["record_id_l", "record_id_r"]].min(axis=1),
        gold[["record_id_l", "record_id_r"]].max(axis=1),
    )
    if gold.duplicated(["record_id_l", "record_id_r"]).any():
        raise ValueError("Gold labels contain duplicate pair keys")
    normalized = gold["label"].map(normalise_label)
    if normalized.isna().any():
        raise ValueError("Gold labels contain invalid label values")
    gold["is_positive"] = normalized.eq("match")
    disputed = audit_gold_against_device()
    disputed = disputed.loc[disputed["verdict"] == "contradicted", ["record_id_l", "record_id_r"]]
    disputed = disputed.assign(is_disputed=True)
    gold = gold.merge(disputed, on=["record_id_l", "record_id_r"], how="left")
    gold["is_disputed"] = gold["is_disputed"].eq(True)
    fields = ("email_std", "phone_std", "dob_std", "first_name_std", "last_name_std", "city_std")
    columns = ["record_id_l", "record_id_r", "match_probability", "match_weight", *GAMMAS]
    columns += [f"{field}_{side}" for field in fields for side in ("l", "r")]
    predictions = pd.read_parquet(pred_path, columns=columns)
    if sha256_of(GOLD_PATH) != gold_sha256 or sha256_of(pred_path) != predictions_sha256:
        raise ValueError("Gold labels or predictions changed while reading; rerun with one snapshot")
    if predictions.duplicated(["record_id_l", "record_id_r"]).any():
        raise ValueError("Predictions contain duplicate pair keys")
    merged = gold.merge(predictions, on=["record_id_l", "record_id_r"], how="left", indicator=True)
    missing = merged[merged["_merge"] == "left_only"]
    scored = merged[merged["_merge"] == "both"].drop(columns="_merge")
    for name, field in (("agree_email", "email_std"), ("agree_phone", "phone_std"),
                        ("agree_dob", "dob_std"), ("agree_city", "city_std")):
        left, right = scored[f"{field}_l"], scored[f"{field}_r"]
        scored[name] = left.notna() & right.notna() & left.eq(right)
    names = ("first_name_std", "last_name_std")
    scored["agree_name"] = pd.Series(True, index=scored.index)
    for field in names:
        left, right = scored[f"{field}_l"], scored[f"{field}_r"]
        scored["agree_name"] &= left.notna() & right.notna() & left.eq(right)
    if not include_disputed:
        scored = scored[~scored["is_disputed"]]
    if scored.empty:
        raise ValueError("No labelled pair was scored by the current Splink model")
    scored = scored.reset_index(drop=True)
    schema = json.dumps(FEATURES, sort_keys=True)
    provenance = {
        "model_version": meta.get("model_version"),
        "prediction_sha256": predictions_sha256,
        "gold_sha256": gold_sha256,
        "feature_schema_sha256": hashlib.sha256(schema.encode()).hexdigest(),
        "feature_schema": FEATURES,
        "splink_version": meta.get("splink_version"),
        "random_seed": RANDOM_SEED,
        "unscored_gold_pairs": len(missing),
        "unscored_gold_positive_pairs": int(missing["is_positive"].sum()),
        "total_gold_pairs": len(gold),
        "disputed_gold_pairs": int(gold["is_disputed"].sum()),
    }
    return gold, scored, provenance


def evaluate(include_disputed: bool = False, seed: int = RANDOM_SEED) -> dict:
    gold, pairs, provenance = load_data(include_disputed)
    X = features_for(pairs)
    y = pairs["is_positive"].astype(int).to_numpy()
    groups = record_groups(gold, pairs)
    positive_groups = len(set(groups[y == 1]))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "shadow_only",
        "include_disputed": include_disputed,
        "provenance": provenance,
        "scored_gold_pairs": len(pairs),
        "positive_pairs": int(y.sum()),
        "positive_groups": positive_groups,
        "disputed_pairs_scored": int(pairs["is_disputed"].sum()),
        "group_split": "Connected components across all gold pair record IDs, including unscored pairs",
        "A_current_policy": metrics(y, pairs["match_probability"].to_numpy(), MATCH_THRESHOLD),
        "folds": [],
        "pooled": {},
        "verdict": "not_proven",
        "limitation": (
            "Labels were sampled from previous model candidates, not randomly from all pairs. "
            "Few positive groups, disputed positive labels and unscored gold pairs prevent "
            "a reliable conclusion about production accuracy or material improvement. "
            "B uses a monotone transform of Splink's own probability (match_weight), "
            "so it adds no independent evidence. Never promote this shadow model."
        ),
    }
    if positive_groups < 2:
        report["limitation"] += " Fewer than two positive groups: supervised folds unavailable."
        return report
    splitter = StratifiedGroupKFold(n_splits=min(5, positive_groups), shuffle=True, random_state=seed)
    for fold, (train, test) in enumerate(splitter.split(X, y, groups)):
        train_ids = set(pairs.iloc[train][["record_id_l", "record_id_r"]].to_numpy().ravel())
        test_ids = set(pairs.iloc[test][["record_id_l", "record_id_r"]].to_numpy().ravel())
        if train_ids & test_ids:
            raise ValueError("Record leakage between train and test")
        yt, ye = y[train], y[test]
        item = {
            "fold": fold,
            "train_pairs": len(train),
            "test_pairs": len(test),
            "test_positives": int(ye.sum()),
            "test_disputed": int(pairs.iloc[test]["is_disputed"].sum()),
            "shared_record_ids": 0,
            "test_record_ids_sha256": hashlib.sha256("|".join(sorted(test_ids)).encode()).hexdigest(),
            "A": metrics(ye, pairs.iloc[test]["match_probability"].to_numpy(), MATCH_THRESHOLD),
        }
        if yt.sum() == 0 or ye.sum() == 0 or yt.sum() == len(yt):
            item["skipped_supervised"] = "train/test lacks a positive or train lacks a negative"
        else:
            for name, model in (
                ("B", make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))),
                ("C", HistGradientBoostingClassifier(max_depth=2, min_samples_leaf=2, random_state=seed)),
            ):
                columns = FEATURES[name]
                model.fit(X.iloc[train][columns], yt)
                threshold = train_threshold(yt, model.predict_proba(X.iloc[train][columns])[:, 1])
                score = model.predict_proba(X.iloc[test][columns])[:, 1]
                item[name] = metrics(ye, score, threshold)
        report["folds"].append(item)
    for name in ("A", "B", "C"):
        rows = [row[name] for row in report["folds"] if name in row]
        report["pooled"][name] = {
            key: sum(row[key] for row in rows) for key in ("tp", "fp", "fn", "tn")
        } if rows else None
        if rows:
            value = report["pooled"][name]
            value["precision"] = round(value["tp"] / (value["tp"] + value["fp"]), 4) if value["tp"] + value["fp"] else 0.0
            value["recall"] = round(value["tp"] / (value["tp"] + value["fn"]), 4) if value["tp"] + value["fn"] else 0.0
            value["f1"] = round(2 * value["tp"] / (2 * value["tp"] + value["fp"] + value["fn"]), 4) if 2 * value["tp"] + value["fp"] + value["fn"] else 0.0
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Splink and two supervised models in shadow mode")
    parser.add_argument("--include-disputed", action="store_true")
    args = parser.parse_args()
    report = evaluate(args.include_disputed)
    if (sha256_of(GOLD_PATH) != report["provenance"]["gold_sha256"]
            or sha256_of(predictions_path(full=True)) != report["provenance"]["prediction_sha256"]):
        raise ValueError("Gold labels or predictions changed during evaluation; no report saved")
    path = OUTPUT_DIR / ("stage1_abc_with_disputed.json" if args.include_disputed else "stage1_abc.json")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"pooled": report["pooled"], "status": report["verdict"],
                      "scored_gold_pairs": report["scored_gold_pairs"],
                      "unscored_gold_pairs": report["provenance"]["unscored_gold_pairs"]}, indent=2))
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()
