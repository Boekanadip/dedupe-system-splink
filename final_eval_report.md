# Final Evaluation Report — Threshold 0.84 / 0.35 (Gold Labels)

## Objective
Mengukur recall, precision, dan F1 pada gold labels untuk kebijakan threshold baru:
- **MATCH** jika `match_probability >= 0.84`
- **REVIEW** jika `0.35 <= match_probability < 0.84`
- **NON_MATCH** jika `match_probability < 0.35`

## Sumber Data
- Gold labels: `data/labels/gold_labels.csv` — **3.593 pasangan** (1.099 `match`, 2.494 `no_match`).
- Yatim skor: **378 pasangan tanpa `match_probability`** (stratum `outside_blocking_*`, `feedback_only_unverified`, sebagian `typo_*`). Pasangan ini berada di luar cakupan prediksi dan tidak dihitung di tabel utama.
- Sampel berlabel berskor: **3.215 pasangan** (851 `match`, 2.364 `no_match`), diekspor ke `outputs/gold_scored.parquet`.

## Hasil Terukur (n = 3.215 pasangan berskor)

| Threshold | TP | FP | FN | TN | Recall | Precision | F1 |
|---|---|---|---|---|---|---|---|
| 0.35 | 849 | 73 | 2 | 2.291 | 0.9976 | 0.9208 | 0.9577 |
| 0.50 | 849 | 64 | 2 | 2.300 | 0.9976 | 0.9299 | 0.9626 |
| 0.82 | 849 | 62 | 2 | 2.302 | 0.9976 | 0.9319 | 0.9637 |
| **0.84** | **849** | **59** | **2** | **2.305** | **0.9976** | **0.9350** | **0.9653** |
| 0.90 | 849 | 58 | 2 | 2.306 | 0.9976 | 0.9361 | 0.9659 |

## Distribusi Pita Keputusan pada 0.84 / 0.35 (n = 3.215)
- **MATCH** (`P >= 0.84`): 908 pasangan
- **REVIEW** (`0.35 <= P < 0.84`): 14 pasangan — **0 gold positif**, 14 gold negatif
- **NON_MATCH** (`P < 0.35`): 2.293 pasangan

## Karakteristik Error
- **FN = 2** (pada 851 gold positif berskor): probabilitas maksimum FN hanya `2.67e-10`, artinya model memberi skor ekstrem rendah. Kedua kasus tercatat di stratum `unlabelled_same_email`.
- **FP = 59** pada threshold 0.84: pasangan diprediksi MATCH namun gold `no_match`.
- Pita REVIEW praktis kosong pada gold (14 pasangan), karena distribusi `match_probability` bersifat bimodal di sekitar 0 dan 1 (median `1.07e-7`, Q3 `1.0`).

## Kesimpulan
- **Target recall ≥ 0.95 TERCAPAI** pada threshold 0.84 (`0.9976`), berbeda jauh dari laporan sebelumnya (0.7867 dan 0.9431) yang menggunakan subset/holdout berbeda.
- Precision `0.9350` — masih di bawah 0.95, namun jauh dari klaim laporan sebelumnya (`0.8924`).
- Pemilihan 0.84 vs 0.90 hanya mengubah 1 FP — dampak kecil pada gold ini.

## Catatan Penting (Keterbatasan)
1. **Gold labels tidak independen** — stratum sampel dipilih berdasarkan perilaku model (`unlabelled_high_probability`, `singleton_candidate`, etc.), sehingga recall/precision tidak dapat diekstrapolasi ke seluruh populasi kandidat.
2. **Provenance `gold_labels.csv` belum diverifikasi** — skor ditulis ke kolom `match_probability` dari run yang tidak terdokumentasi; model/versi tidak tercatat di gold. Angka di atas sah untuk file gold ini, bukan bukti performa model aktif (`v20261027_161903`).
3. **378 pasangan tanpa skor tidak dihitung** — mereka adalah pasangan di luar blocking; tidak termasuk recall maupun precision, sesuai batas cakupan blocking.
4. `outputs/splink_predictions.parquet` **tidak ada** di repo; prediksi penuh harus diregenerasi (`python -m src.splink_model --full`) jika ingin evaluasi vs device-channel.

## Langkah Berikutnya
1. Regenerasi `outputs/splink_predictions.parquet` untuk verifikasi ulang dan jalankan `python -m src.evaluate`.
2. Sinkronkan `docs/metadata_pipeline.md` yang masih mengutip angka lama (`0.9431` @ 0.9).
3. Pertimbangkan evaluasi pada holdout stratified terpisah agar gold tidak bercampur dengan training strata.
