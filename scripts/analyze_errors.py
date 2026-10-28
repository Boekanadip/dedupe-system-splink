import glob
import json
import os

import pandas as pd

GOLD = "data/labels/gold_labels.csv"
PRED = "outputs/splink_predictions.parquet"

gold = pd.read_csv(GOLD).rename(columns={"match_probability": "p_prev"})
pred = pd.read_parquet(PRED).rename(columns={"match_probability": "p"})
cols = [c for c in ("record_id_l", "record_id_r", "p", "decision") if c in pred.columns]
m = gold.merge(pred[cols], on=["record_id_l", "record_id_r"], how="inner")

m["is_match"] = m["label"] == "match"
m["agree_contact_both"] = m["agree_email"] & m["agree_phone"]
m["agree_contact_one"] = m["agree_email"] | m["agree_phone"]

pos = m[m["is_match"]]
neg = m[~m["is_match"]]
fn = pos[pos["p"] < 0.5]
fp = neg[neg["p"] >= 0.5]

print(f"gold overlap: {len(m)} pasangan | pos {len(pos)} | neg {len(neg)}")
print(f"tp {(pos['p'] >= 0.5).sum()} | fn {len(fn)} | fp {len(fp)}\n")

PATTERN = [
    "agree_name",
    "agree_contact_both",
    "agree_contact_one",
    "agree_city",
    "agree_dob",
]


def show(df: pd.DataFrame, title: str, k: int = 10):
    if df.empty:
        print(f"{title}: kosong\n")
        return
    tab = (
        df.groupby(PATTERN)
        .agg(n=("p", "size"), p_med=("p", "median"), p_max=("p", "max"))
        .sort_values("n", ascending=False)
        .head(k)
    )
    print(title)
    print(tab.to_string())
    print()


show(fn, "1) Pola FN (gold match, p < 0.5)")
show(fp, "2) Pola FP (bukan match, p >= 0.5)")

print("3) Jarak FN ke ambang 0.5")
bins = [0, 1e-9, 1e-6, 1e-3, 0.01, 0.1, 0.3, 0.5]
print(
    pd.cut(fn["p"], bins=bins, right=False)
    .value_counts()
    .sort_index()
    .to_string()
)
print(f"   fn dengan p >= 0.3 : {(fn['p'] >= 0.3).sum()}")
print(f"   fn dengan p >= 0.1 : {(fn['p'] >= 0.1).sum()}\n")

print("4) m empiris (gold-positif) vs m model")
latest = sorted(glob.glob("models/*/model.json"), key=os.path.getmtime)[-1]
model_m = {
    c["output_column_name"]: [
        lv["m_probability"] for lv in c["comparison_levels"]
    ]
    for c in json.load(open(latest))["comparisons"]
}
emp = {
    "name.exact": pos["agree_name"].mean(),
    "contact.both": pos["agree_contact_both"].mean(),
    "contact.one": pos["agree_contact_one"].mean(),
    "location.match": pos["agree_city"].mean(),
    "dob.match": pos["agree_dob"].mean(),
}
print(f"   model: {latest}")
for key, val in emp.items():
    comp, level = key.split(".")
    idx = {"name.exact": 0, "contact.both": 0, "contact.one": 1,
           "location.match": 0, "dob.match": 0}[key]
    print(f"   {key:18s} empiris={val:.4f}  model={model_m[comp][idx]:.4f}")

emp_else = {
    "name.else": 1 - emp["name.exact"],
    "contact.else": 1 - pos["agree_contact_one"].mean(),
    "location.else": 1 - emp["location.match"],
    "dob.else": 1 - emp["dob.match"],
}
for comp, val in emp_else.items():
    name = comp.split(".")[0]
    print(f"   {comp:18s} empiris={val:.4f}  model={model_m[name][-1]:.4f}")

print("\n5) 15 FN teratas (paling dekat ambang) — cek manual apakah gold benar")
cols_fn = [
    "record_id_l", "record_id_r", "p", "stratum",
    "agree_name", "agree_email", "agree_phone", "agree_dob", "agree_city",
]
print(fn.sort_values("p", ascending=False)[cols_fn].head(15).to_string(index=False))
