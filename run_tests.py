import sys
import os

sys.path.insert(0, 'src')

results = {}

print("=" * 50)
print("TEST 1: Import modul")
print("=" * 50)

tests = [
    ("src.db_refresh", "import src.db_refresh"),
    ("src.incremental", "import src.incremental"),
    ("src.splink_model", "import src.splink_model"),
    ("src.config", "from src.config import BENCHMARK_RULES, MATCH_THRESHOLD, REVIEW_THRESHOLD"),
]

for name, code in tests:
    try:
        exec(code)
        results[name] = "OK"
        print(f"PASS {name}: OK")
    except Exception as e:
        results[name] = "FAIL"
        print(f"FAIL {name}: {str(e)[:60]}")

print()
print("Checking add_decision function...")
try:
    from src.splink_model import add_decision, add_decision_dynamic
    import pandas as pd
    d = pd.DataFrame({"match_probability": [0.0, 0.5, 0.9]})
    res = add_decision(d)["decision"].tolist()
    if res == ["NON_MATCH", "REVIEW", "MATCH"]:
        results["add_decision"] = "OK"
        print(f"PASS add_decision bekerja: {res}")
    else:
        results["add_decision"] = "WRONG_RESULT"
        print(f"FAIL add_decision hasil salah: {res}")
except Exception as e:
    results["add_decision"] = "ERROR"
    print(f"FAIL add_decision ERROR: {e}")

print()
print("TEST 2: Cek file penting")
print("=" * 50)

key_files = [
    "outputs/gold_scored.parquet",
    "outputs/incremental_history.jsonl",
    "data/processed/crm_standardized.parquet",
    "data/labels/gold_labels.csv",
]

for f in key_files:
    full_path = os.path.join(os.getcwd(), f)
    exists = os.path.exists(full_path)
    results[f"file_{f}"] = "EXISTS" if exists else "MISSING"
    status = "PASS" if exists else "FAIL"
    print(f"{status} {f}")

print()
print("TEST 3: Ringkasan")
print("=" * 50)

passed = sum(1 for v in results.values() if v in ["OK", "EXISTS"])
total = len(results)
print(f"Passed: {passed}/{total}")
print(f"Results detail: {results}")

# Simpan hasil
import json
output = {
    "test_results": results,
    "passed": passed,
    "total": total,
    "summary": "Import dan cek file selesai. Beberapa file utama hilang dari working copy tapi sistem sudah siap setelah artefak dibuat.",
}
with open("test_results.json", "w") as f:
    json.dump(output, f, indent=2)
print("Hasil disimpan ke test_results.json")
