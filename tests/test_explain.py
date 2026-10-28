#!/usr/bin/env python3
import pandas as pd
from splink import PySplinkModel

print("Loading model and predictions...")

# Load predictions
pred = pd.read_parquet("outputs/splink_predictions.parquet")
print(f"Total pairs: {len(pred)}")
print(f"Decision counts: {pred['decision'].value_counts().to_dict()}")

# Load model
linker = PySplinkModel.load_model("models/v20261027_161903")

# Cari satu pasangan REVIEW
review_pairs = pred[pred["decision"] == "REVIEW"]
if len(review_pairs) == 0:
    print("Tidak ada REVIEW pairs")
    exit()

sample_pair = review_pairs.iloc[0]
print(f"\nSample REVIEW pair:")
print(f"  record_id_l: {sample_pair['record_id_l']}")
print(f"  record_id_r: {sample_pair['record_id_r']}")
print(f"  match_prob: {sample_pair['match_probability']}")

# Buat data untuk explain dengan field yang sudah ada di parquet
# Extract field names dari parquet
sample_l = {k: v for k, v in sample_pair.items() if k.startswith(('first_name', 'last_name', 'email', 'phone', 'city', 'state', 'dob'))}
sample_r = {}

print(f"\nSample left fields: {list(sample_l.keys())[:10]}")
print(f"Sample right fields: {list(sample_r.keys())[:10]}")

# Coba explain dengan data minimal
# Splink expect data dengan record_id dan comparison columns
try:
    # Coba pake data dari parquet fields yang ada
    test_data = pd.DataFrame([{
        "record_id": sample_pair["record_id_l"],
        "first_name_std": "Budi",
        "last_name_std": "Mulia",
        "email_std": "budi@example.com",
        "phone_pre7": "0812345678",
        "city_std": "Jakarta",
        "state_std": "DKI",
        "dob_std": "1990-01-15"
    }, {
        "record_id": sample_pair["record_id_r"],
        "first_name_std": "Budi",
        "last_name_std": "Mulia",
        "email_std": "budi@example.com",
        "phone_pre7": "0812345678",
        "city_std": "Jakarta",
        "state_std": "DKI",
        "dob_std": "1990-01-15"
    }])
    
    explainer = linker.explain(record_pair=(test_data.iloc[0]["record_id"], test_data.iloc[1]["record_id"]))
    result_str = str(explainer)
    print(f"\nExplain result length: {len(result_str)} chars")
    print(f"Explain preview (first 1000 chars):")
    print(result_str[:1000])
except Exception as e:
    print(f"\nExplain error: {type(e).__name__}: {str(e)[:300]}")
    import traceback
    traceback.print_exc()