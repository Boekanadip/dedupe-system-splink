"""One-shot verification.  Jalankan:  python check_model.py"""
import glob, json, os
import pandas as pd

L = sorted(glob.glob("models/*/model.json"), key=os.path.getmtime)[-1]
print("model:", L)
d = json.load(open(L))
grand = 0.0
for c in d["comparisons"]:
    ms = [lv["m_probability"] for lv in c["comparison_levels"]]
    us = [lv["u_probability"] for lv in c["comparison_levels"]]
    s = sum(x for x in ms if x is not None)
    grand += s
    print(f"  {c['output_column_name']:10s} m_sum={round(s,4)} "
          f"m={[round(x,4) for x in ms]} u={[round(x,6) for x in us]}")
print(f"GRAND SUM m = {round(grand,4)}  (harus tiap comparison = 1.0)\n")

pred = pd.read_parquet("outputs/splink_predictions.parquet")
p = pred["match_probability"]
print("match_probability:")
print(f"  max         = {p.max():.4e}")
print(f"  top10 avg   = {p.nlargest(10).mean():.4e}")
print(f"  count>=.5   = {(p>=0.5).sum()}")
print(f"  count>=.9   = {(p>=0.9).sum()}")
print(f"  count>=.99  = {(p>=0.99).sum()}")
print(f"  median      = {p.median():.4e}")

# Precision / recall @0.5 vs gold
g = pd.read_csv("data/labels/gold_labels.csv")
truth = g[["record_id_l", "record_id_r", "label"]].copy()
truth["is_match"] = truth["label"].isin(["match", 1, "1", True])
merged = pred[["record_id_l", "record_id_r", "match_probability"]].merge(
    truth[["record_id_l", "record_id_r", "is_match"]],
    on=["record_id_l", "record_id_r"],
    how="inner",
)
tp = int(((merged["match_probability"] >= 0.5) & (merged["is_match"])).sum())
fp = int(((merged["match_probability"] >= 0.5) & (~merged["is_match"])).sum())
fn = int(((merged["match_probability"] <  0.5) & (merged["is_match"])).sum())
prec = tp / (tp + fp) if (tp + fp) else 0.0
rec  = tp / (tp + fn) if (tp + fn) else 0.0
print(f"\npairs overlapped with gold: {len(merged)} of {len(truth)} gold rows")
print(f"tp={tp} fp={fp} fn={fn}")
print(f"precision@0.5 = {prec:.4f}")
print(f"recall@0.5    = {rec:.4f}")
