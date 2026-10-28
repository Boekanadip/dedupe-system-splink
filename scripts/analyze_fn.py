"""Analisis FN pairs dari final_eval output."""
import pandas as pd
import os
os.chdir(r"C:\Users\User\Downloads\dedup-system-splink")

gold = pd.read_csv("data/labels/gold_labels.csv")
pred = pd.read_parquet("outputs/splink_predictions.parquet")

merged = pred.merge(gold, on=["record_id_l", "record_id_r"], suffixes=("_pred", "_gold"))
print("Merged columns:", merged.columns.tolist())
print("Merged shape:", merged.shape)

pos = merged[merged["gold_label"] == "match"].copy()
print(f"Total positive pairs in test: {len(pos)}")
