"""Eksperimen read-only: pin u_probability dari frekuensi pasangan empiris.

Tidak menimpa model produksi, predictions, atau entity_map.
Output: outputs/experiments/u_pin_model.json, u_pin_results.json, u_pin_report.md
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from splink import DuckDBAPI, Linker

from src.splink_model import train_and_predict

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "v20261117_115206" / "model.json"
DATA_PATH = ROOT / "data" / "processed" / "crm_standardized.parquet"
CUST_PATH = DATA_PATH
OUT = ROOT / "outputs" / "experiments"
SAMPLE_ROWS = 10_000


def exact_pairs(df: pd.DataFrame, cols: list[str]) -> tuple[int, int]:
    sub = df[cols].dropna()
    denom = len(sub) * (len(sub) - 1) // 2
    g = sub.groupby(cols, dropna=True).size()
    num = int((g * (g - 1) // 2).sum())
    return num, denom


def u_exact(df: pd.DataFrame, cols: list[str]) -> float:
    num, denom = exact_pairs(df, cols)
    return num / denom if denom else 0.0


def u_union(df: pd.DataFrame, cols: list[str]) -> float:
    counts = [exact_pairs(df, [c]) for c in cols]
    inter = exact_pairs(df, cols)
    num = sum(c[0] for c in counts) - inter[0]
    denom = sum(c[1] for c in counts) / len(cols)
    return num / denom if denom else 0.0


def empirical_values(df: pd.DataFrame) -> dict:
    """Kunci: (comparison, comparison_vector_value) -> u empiris."""
    return {
        ("contact", 4): u_exact(df, ["email_std", "phone_std"]),
        ("contact", 3): u_union(df, ["email_std", "phone_std"]),
        ("location", 5): u_exact(df, ["address_std", "city_std", "state_std"]),
        ("location", 4): u_exact(df, ["address_std"]),
        ("dob", 2): u_exact(df, ["dob_std"]),
        ("name", 1): u_exact(df, ["phonetic_first_name", "phonetic_last_name"]),
    }


def pinned_model(model: dict, df: pd.DataFrame, values: dict) -> dict:
    """Patch u_probability di dict model; fix_u_probability=True agar EM tidak menimpa."""
    out = json.loads(json.dumps(model))
    tiny = df.head(2)
    linker = Linker(DuckDBAPI().register(tiny, table_name="tiny"), out)
    patched = []
    for raw_comp, comp in zip(out["comparisons"], linker._settings_obj.comparisons):
        name = comp.output_column_name
        # Urutan comparison_levels di Splink tidak sama dengan urutan di JSON.
        # Cocokkan lewat sql_condition agar gamma tidak salah petakan.
        gamma_by_sql = {
            lv.sql_condition: lv._comparison_vector_value
            for lv in comp.comparison_levels
        }
        for raw_level in raw_comp["comparison_levels"]:
            key = (name, gamma_by_sql.get(raw_level.get("sql_condition")))
            if key not in values:
                continue
            old = raw_level.get("u_probability")
            raw_level["u_probability"] = values[key]
            raw_level["fix_u_probability"] = True
            patched.append({"comparison": name, "gamma": key[1], "u_old": old, "u": values[key]})
    return out, patched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="skor seluruh data, bukan 10.000 baris")
    args = parser.parse_args()
    suffix = "_full" if args.full else ""

    full = pd.read_parquet(DATA_PATH)
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    values = empirical_values(full)
    pinned, patched = pinned_model(model, full, values)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"u_pin_model{suffix}.json").write_text(
        json.dumps(pinned, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    n_rows = len(full) if args.full else SAMPLE_ROWS
    df = full.head(n_rows).reset_index(drop=True)
    t0 = time.perf_counter()
    base, _ = train_and_predict(df, model=model)
    t_base = time.perf_counter() - t0
    t0 = time.perf_counter()
    new, _ = train_and_predict(df, model=pinned)
    t_new = time.perf_counter() - t0

    keys = ["record_id_l", "record_id_r"]
    merged = base[keys + ["decision", "match_probability"]].merge(
        new[keys + ["decision", "match_probability"]], on=keys,
        suffixes=("_base", "_pin"),
    )
    changed = merged[merged.decision_base != merged.decision_pin]

    rec = pd.read_parquet(
        DATA_PATH, columns=["record_id", "customer_id", "device_ids_std"]
    )
    rec["dev"] = rec["device_ids_std"].apply(
        lambda x: "|".join(sorted(str(v) for v in x if v not in (None, "")))
        if isinstance(x, (list, tuple, np.ndarray))
        else ("" if pd.isna(x) else str(x))
    )
    cust_l = rec.rename(columns={
        "record_id": "record_id_l", "customer_id": "cid_l", "dev": "dev_l",
    })[["record_id_l", "cid_l", "dev_l"]]
    cust_r = rec.rename(columns={
        "record_id": "record_id_r", "customer_id": "cid_r", "dev": "dev_r",
    })[["record_id_r", "cid_r", "dev_r"]]
    changed = changed.merge(cust_l, on="record_id_l", how="left").merge(
        cust_r, on="record_id_r", how="left"
    )
    changed["same_cid"] = changed.cid_l.notna() & changed.cid_r.notna() & changed.cid_l.eq(changed.cid_r)
    changed["same_dev"] = changed.dev_l.ne("") & changed.dev_r.ne("") & changed.dev_l.eq(changed.dev_r)
    new_match = changed[changed.decision_pin == "MATCH"]

    transitions = (
        changed.groupby(["decision_base", "decision_pin"]).size()
        .reset_index(name="n").to_dict("records")
    )
    results = {
        "scope": "full" if args.full else "sample",
        "sample_rows": n_rows,
        "pairs": len(merged),
        "decisions_base": base["decision"].value_counts().to_dict(),
        "decisions_pin": new["decision"].value_counts().to_dict(),
        "changed_pairs": len(changed),
        "transitions": transitions,
        "new_match": int(len(new_match)),
        "new_match_same_cid": int(new_match.same_cid.sum()),
        "new_match_same_dev": int(new_match.same_dev.sum()),
        "changed_same_cid": int(changed.same_cid.sum()),
        "mean_prob_base": float(merged.match_probability_base.mean()),
        "mean_prob_pin": float(merged.match_probability_pin.mean()),
        "max_prob_base": float(merged.match_probability_base.max()),
        "max_prob_pin": float(merged.match_probability_pin.max()),
        "runtime_base_s": round(t_base, 2),
        "runtime_pin_s": round(t_new, 2),
    }
    (OUT / f"u_pin_results{suffix}.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    lines = [
        "# Pin u_probability dari data empiris",
        "",
        f"- Scope: {results['scope']} - {n_rows:,} baris, {len(merged):,} pasangan",
        f"- Model asli: {results['decisions_base']}",
        f"- Model u-pin: {results['decisions_pin']}",
        f"- Pasangan berubah keputusan: **{len(changed):,}**",
        f"- MATCH baru: {results['new_match']:,} (same customer_id: {results['new_match_same_cid']:,}, "
        f"same device: {results['new_match_same_dev']:,})",
        f"- Probabilitas rata-rata: {results['mean_prob_base']:.6f} → {results['mean_prob_pin']:.6f}",
        f"- Probabilitas maksimum: {results['max_prob_base']:.6f} → {results['max_prob_pin']:.6f}",
        "",
        "## Level yang di-pin",
        "",
        "| Comparison | gamma | u lama | u empiris |",
        "|---|---:|---:|---:|",
    ]
    for p in patched:
        lines.append(
            f"| {p['comparison']} | {p['gamma']} | {p['u_old']} | {p['u']:.8g} |"
        )

    lines += [
        "",
        "## Perpindahan keputusan",
        "",
        "| Dari | Ke | n |",
        "|---|---|---:|",
    ]
    for t in transitions:
        lines.append(f"| {t['decision_base']} | {t['decision_pin']} | {t['n']:,} |")

    lines += [
        "",
        "## Catatan",
        "",
        "- u empiris dihitung dari seluruh pasangan non-null di data processed.",
        "- customer_id dan device adalah proxy, bukan label independen.",
        f"- Model produksi tidak diubah. File model hasil eksperimen ada di `u_pin_model{suffix}.json`.",
        "- Dua level tetap memakai default: phone fuzzy dan kombinasi alamat parsial (0 pasangan).",
        "",
    ]
    (OUT / f"u_pin_report{suffix}.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
