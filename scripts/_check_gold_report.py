"""Cek cepat isi outputs/version_gold_scores.json (dipakai untuk uji manual)."""
import json
import sys

d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "outputs/version_gold_scores.json", encoding="utf-8"))
print("generated_at:", d["generated_at"])
for v in d["versions"]:
    key = "at_%s" % v["own_match_threshold"]
    m = v["clean"][key]
    print(
        v["version"],
        v["created_at"],
        "F1=%.4f" % m["f1"],
        "TP=%d FP=%d FN=%d" % (m["tp"], m["fp"], m["fn"]),
        "kandidat=%s" % v.get("candidate_pairs"),
    )
