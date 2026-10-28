import pandas as pd
import splink

print("Loading model...")
linker = splink.Link.load_model("models/v20261027_161903")

print("Loading predictions...")
pred = pd.read_parquet("outputs/splink_predictions.parquet")
print(f"Total pairs: {len(pred)}")
print(f"Decision counts: {pred['decision'].value_counts().to_dict()}")

# Cari REVIEW pair
review_pairs = pred[pred["decision"] == "REVIEW"]
if len(review_pairs) > 0:
    sample_pair = review_pairs.iloc[0]
    print(f"\nSample REVIEW pair prob: {sample_pair['match_probability']}")
    
    # Coba explain
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
    
    print("\nTesting explain...")
    try:
        explainer = linker.explain(record_pair=(test_data.iloc[0]["record_id"], test_data.iloc[1]["record_id"]))
        result = str(explainer)
        print(f"Explain success! Length: {len(result)} chars")
        print(result[:800])
    except Exception as e:
        print(f"Explain error: {e}")
        import traceback
        traceback.print_exc()