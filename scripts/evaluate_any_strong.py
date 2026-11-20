"""Ukur dampak guard any_strong pada seluruh prediksi produksi.

Read-only: tidak mengubah model, threshold, atau artifact existing.
Output: outputs/experiments/any_strong_full.json + .md
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "outputs" / "experiments"
PRED = ROOT / "outputs" / "splink_predictions.parquet"
REC = ROOT / "data" / "processed" / "crm_standardized.parquet"


def agree(l: pd.Series, r: pd.Series) -> pd.Series:
    """True hanya jika kedua nilai ada dan sama."""
    return l.notna() & r.notna() & (l == r)


def truth_flags() -> pd.DataFrame:
    """Proxy truth dari data: customer_id dan device_ids_std."""
    rec = pd.read_parquet(REC, columns=["record_id", "customer_id", "device_ids_std"])

    def flat(x):
        if isinstance(x, (list, tuple, np.ndarray)):
            vals = [str(v) for v in x if v not in (None, "")]
            return "|".join(sorted(vals))
        return "" if pd.isna(x) else str(x)

    rec["dev"] = rec["device_ids_std"].apply(flat)
    left = rec.rename(columns={
        "record_id": "record_id_l", "customer_id": "cid_l", "dev": "dev_l",
    })[["record_id_l", "cid_l", "dev_l"]]
    right = rec.rename(columns={
        "record_id": "record_id_r", "customer_id": "cid_r", "dev": "dev_r",
    })[["record_id_r", "cid_r", "dev_r"]]
    return left, right


def rate(mask: pd.Series, col: str, df: pd.DataFrame) -> float | None:
    sub = df.loc[mask, col].dropna()
    return float(sub.mean()) if len(sub) else None


def main():
    pred = pd.read_parquet(PRED, columns=[
        "record_id_l", "record_id_r", "decision", "match_probability",
        "email_std_l", "email_std_r",
        "phone_std_l", "phone_std_r",
        "dob_std_l", "dob_std_r",
    ])
    left, right = truth_flags()
    df = pred.merge(left, on="record_id_l", how="left").merge(right, on="record_id_r", how="left")

    df["agree_email"] = agree(df.email_std_l, df.email_std_r)
    df["agree_phone"] = agree(df.phone_std_l, df.phone_std_r)
    df["agree_dob"] = agree(df.dob_std_l, df.dob_std_r)
    df["any_strong"] = df.agree_email | df.agree_phone | df.agree_dob
    df["same_cid"] = df.cid_l.notna() & df.cid_r.notna() & df.cid_l.eq(df.cid_r)
    df["same_dev"] = df.dev_l.ne("") & df.dev_r.ne("") & df.dev_l.eq(df.dev_r)
    df["device_available"] = df.dev_l.ne("") & df.dev_r.ne("")
    df["cid_available"] = df.cid_l.notna() & df.cid_r.notna()

    match = df[df.decision == "MATCH"].copy()
    review = df[df.decision == "REVIEW"].copy()

    def block(sub: pd.DataFrame) -> dict:
        strong = sub[sub.any_strong]
        weak = sub[~sub.any_strong]
        return {
            "n": int(len(sub)),
            "n_any_strong": int(len(strong)),
            "n_no_strong": int(len(weak)),
            "pct_no_strong": round(float(len(weak) / len(sub)), 4) if len(sub) else None,
            "any_strong": {
                "same_cid_rate": rate(strong.any_strong, "same_cid", strong),
                "same_dev_rate": rate(strong.any_strong, "same_dev", strong),
                "n_same_cid": int(strong[strong.cid_available].same_cid.sum()),
                "n_same_dev": int(strong.same_dev.sum()),
                "n_device_available": int(strong.device_available.sum()),
            },
            "no_strong": {
                "same_cid_rate": rate(~weak.any_strong, "same_cid", weak),
                "same_dev_rate": rate(~weak.any_strong, "same_dev", weak),
                "n_same_cid": int(weak[weak.cid_available].same_cid.sum()),
                "n_same_dev": int(weak.same_dev.sum()),
                "n_device_available": int(weak.device_available.sum()),
            },
        }

    # Efek hipotetis guard pada populasi MATCH
    strong_match = match[match.any_strong]
    weak_match = match[~match.any_strong]
    effect = {
        "match_dropped_by_guard": int(len(weak_match)),
        "dropped_but_same_cid": int(weak_match[weak_match.cid_available].same_cid.sum()),
        "dropped_but_same_dev": int(weak_match.same_dev.sum()),
        "kept_but_cid_diff": int(strong_match[strong_match.cid_available & ~strong_match.same_cid].shape[0]),
        "kept_but_dev_diff": int(strong_match[strong_match.device_available & ~strong_match.same_dev].shape[0]),
    }

    result = {
        "scope": "full splink_predictions.parquet",
        "model_version": "v20261117_115206",
        "definition": "any_strong = email_std_l==email_std_r OR phone_std_l==phone_std_r OR dob_std_l==dob_std_r (non-null)",
        "caveat": "customer_id dan device_ids_std adalah proxy truth, bukan label independen. Angka di bawah bukan akurasi sejati.",
        "match": block(match),
        "review": block(review),
        "hypothetical_guard_effect": effect,
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "any_strong_full.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    m = result["match"]
    e = result["hypothetical_guard_effect"]
    lines = [
        "# Ukur Dampak Guard any_strong (Seluruh Prediksi)",
        "",
        f"- Scope: {result['scope']}",
        f"- Definisi: `{result['definition']}`",
        "",
        "## Populasi MATCH",
        "",
        f"- Total MATCH: **{m['n']:,}**",
        f"- Punya any_strong: **{m['n_any_strong']:,}**",
        f"- Tanpa any_strong: **{m['n_no_strong']:,}** ({m['pct_no_strong']*100:.1f}%)",
        "",
        "| Kelompok | n | same customer_id | same device | device tersedia |",
        "|---|---:|---:|---:|---:|",
        f"| any_strong | {m['n_any_strong']:,} | {m['any_strong']['n_same_cid']:,} | {m['any_strong']['n_same_dev']:,} | {m['any_strong']['n_device_available']:,} |",
        f"| tanpa any_strong | {m['n_no_strong']:,} | {m['no_strong']['n_same_cid']:,} | {m['no_strong']['n_same_dev']:,} | {m['no_strong']['n_device_available']:,} |",
        "",
        "## Efek Hipotetis Guard",
        "",
        f"- MATCH yang akan dibatalkan: **{e['match_dropped_by_guard']:,}**",
        f"- Di antaranya same customer_id: {e['dropped_but_same_cid']:,}",
        f"- Di antaranya same device: {e['dropped_but_same_dev']:,}",
        f"- MATCH dengan any_strong tapi customer_id beda: {e['kept_but_cid_diff']:,}",
        f"- MATCH dengan any_strong tapi device beda: {e['kept_but_dev_diff']:,}",
        "",
        "## Catatan",
        "",
        f"- {result['caveat']}",
        "- Angka ini menggantikan klaim sebelumnya yang memakai gold sample 3.215 pasangan.",
        "",
    ]
    (OUTPUT / "any_strong_full.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
