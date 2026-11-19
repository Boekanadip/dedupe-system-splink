"""AC-N2: REVIEW-band pairs, null-kan address_std di satu sisi — boleh PA naik ke >= 0.84?

Analytical hitung ulang dari `outputs/splink_predictions.parquet` yang sudah
menyimpan gamma_* dan semua field mentah per pasangan. Tidak perlu model scoring
ulang via Splink (read-only, tanpa akses DB).

Bobot diambil langsung dari model.json / SQL yang dihasilkan model.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import pandas as pd

from src.config import active_path, predictions_path

OUT = Path('outputs/experiments')
MATCH = 0.84
REVIEW = 0.35

# Weights dari model v20261027_074552 (dilihat dari SQL inference output).
BIAS = -18.17244756714254
MW_NAME = {-1: 0.0, 2: 14.807565425925869, 1: 10.791778507911872, 0: -6.6437690833042655}
MW_CONTACT = {-1: 0.0, 2: 18.716969142724643, 1: 16.061950049853692, 0: -7.6438514190478815}
MW_LOCATION = {-1: 0.0, 1: 18.490269162830394, 0: -5.643853143779075}
MW_DOB = {-1: 0.0, 1: 14.067865465218734, 0: -9.965706229718052}


def _prob(mw: float) -> float:
    if mw >= 0:
        return 1.0 / (1.0 + math.pow(2.0, -mw))
    return math.pow(2.0, mw) / (1.0 + math.pow(2.0, mw))


def _gamma_location_null_address(row) -> int:
    """gamma_location setelah address_std_l di-null."""
    al = None  # address_std_l diforce null
    ar = row['address_std_r']
    cl = row['city_std_l']
    cr = row['city_std_r']
    sl = row['state_std_l']
    sr = row['state_std_r']
    col_ = row['country_std_l']
    cor_ = row['country_std_r']

    def isnan(v):
        try:
            return pd.isna(v)
        except TypeError:
            return v is None

    # -1 jika (alamat null dan kota null) di salah satu sisi
    if (isnan(al) and isnan(cl)) or (isnan(ar) and isnan(cr)):
        return -1
    # 1 jika semua match dan tidak null
    if (not any(isnan(v) for v in (al, ar, cl, cr, sl, sr, col_, cor_))
            and al == ar and cl == cr and sl == sr and col_ == cor_):
        return 1
    return 0


def main() -> None:
    preds = pd.read_parquet(active_path(predictions_path(full=True)))
    band = preds[
        (preds.match_probability >= REVIEW) & (preds.match_probability < MATCH)
    ].copy()
    band = band.drop_duplicates(['record_id_l', 'record_id_r'])
    print(f'REVIEW band pairs found: {len(band)}')

    if band.empty:
        print('Tidak ada pasangan band REVIEW.')
        return

    mw = (
        BIAS
        + band['gamma_name'].map(MW_NAME).fillna(0.0)
        + band['gamma_contact'].map(MW_CONTACT).fillna(0.0)
        + band['gamma_dob'].map(MW_DOB).fillna(0.0)
    )
    # Lokasi: hitung ulang dengan address_std_l = null.
    new_loc = band.apply(_gamma_location_null_address, axis=1)
    mw_new = (
        BIAS
        + band['gamma_name'].map(MW_NAME).fillna(0.0)
        + band['gamma_contact'].map(MW_CONTACT).fillna(0.0)
        + band['gamma_dob'].map(MW_DOB).fillna(0.0)
        + new_loc.map(MW_LOCATION).fillna(0.0)
    )

    prob_before = mw.map(_prob)
    prob_after = mw_new.map(_prob)

    rising = prob_after >= MATCH
    delta = prob_after - prob_before

    report = {
        'model_version': 'v20261027_074552',
        'source': 'outputs/splink_predictions.parquet',
        'group': 'REVIEW_band',
        'threshold': MATCH,
        'pairs': int(len(band)),
        'pairs_rising_to_0.84_or_more': int(rising.sum()),
        'pairs_count_rising_percent': round(100 * rising.mean(), 3),
        'max_prob_after': round(float(prob_after.max()), 6),
        'max_delta': round(float(delta.max()), 6),
        'mean_delta': round(float(delta.mean()), 6),
        'verdict': 'PASS' if rising.sum() == 0 else 'FAIL',
        'read_only': True,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'model_diagnostics_ac_n2.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    print(f'\nSaved: {path}')


if __name__ == '__main__':
    main()
