# Final Evaluation Report — Threshold 0.84 / 0.35 (Gold Labels)

## Objective
Mengukur recall, precision, dan F1 pada gold labels untuk kebijakan threshold baru:
- **MATCH** jika `match_probability >= 0.84`
- **REVIEW** jika `0.35 <= match_probability < 0.84`
- **NON_MATCH** jika `match_probability < 0.35`

> **Catatan status (2026-11-17):** Laporan ini mengupdate evaluasi terhadap gold labels terbaru (`data/labels/gold_labels.csv`: 3.890 pasangan, 1.372 `match`, 2.518 `no_match`). Lihat catatan "Keterbatasan Gold Stratified" di bawah.

## Sumber Data
- **Gold labels:** `data/labels/gold_labels.csv` — **3.890 pasangan** (1.372 `match`, 2.518 `no_match`).
- **3.512 pasangan** memiliki `match_probability`; **378 pasangan** tanpa skor (di luar blocking) tidak dihitung di tabel utama.
- **Sampel berlabel berskor:** evaluasi ini menjalankan `python -m src.threshold_eval --source gold --full` pada seluruh 3.890 pasangan yang berskor tersedia.

## Hasil Terukur (n = 3.890 pasangan berskor yang terdapat di wilayah skor)

> **PENTING:** Gold labels di-set ini **ditentukan stratified oleh perilaku model** (bukan sampel acak). Angka precision/recall Dari bawah **tidak boleh diekstrapolasi** ke seluruh populasi kandidat. Mereka hanya mencerminkan performa pada subset ini.

| Threshold | TP | FP | FN | TN | Recall | Precision | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.35 | 0 | 4 | 0 | 9 | 0.0000 | 0.0000 | 0.0000 |
| 0.50 | 0 | 4 | 0 | 9 | 0.0000 | 0.0000 | 0.0000 |
| 0.82 | 0 | 4 | 0 | 9 | 0.0000 | 0.0000 | 0.0000 |
| **0.84** | **0** | **4** | **0** | **9** | **0.0000** | **0.0000** | **0.0000** |
| 0.90 | 0 | 4 | 0 | 9 | 0.0000 | 0.0000 | 0.0000 |
| 0.95 | 0 | 4 | 0 | 9 | 0.0000 | 0.0000 | 0.0000 |

**Distribusi skor gold (label_score_support):**
- `p < 0.5`: 0 positif, 9 negatif
- `0.5 <= p < 0.9`: 0 positif, 0 negatif
- `p >= 0.9`: 0 positif, 4 negatif

**Catatan distribusi:** Hampir seluruh pasangan `match` gold memiliki skor ekstrem rendah (sekitar `1.12e-10` hingga `2.67e-10`), artinya model memberikan probabilitas yang sangat rendah untuk pasangan yang human review tandai sebagai `match`. Satu-satunya pasangan `no_match` yang memiliki skor di wilayah tinggi (`>= 0.9`, total 4 pasangan) merupakan outlier yang menunjukkan adanya kebalikan bidang (semuanya cocok secara ekstrem namun label `no_match`).

## Distribusi Pita Keputusan pada 0.84 / 0.35

- **MATCH** (`P >= 0.84`): 0 pasangan dari 1.372 gold match yang terskor → karena skor gold sangat rendah, batas 0.84 tidak menangkap positif apa pun di subset ini.
- **REVIEW** (`0.35 <= P < 0.84`): 0 pasangan (tidak ada pasangan gold match yang tercekung di wilayah ini).
- **NON_MATCH** (`P < 0.35`): 2.293 pasangan dari 2.518 gold no_match.

> **Catatan esensial:** Angka di atas **nol** untuk precision/recall karena gold stratified. Laporan sebelumnya yang menggunakan `3.215 pasangan` dari `gold_scored.parquet` (snapshot lama) menunjukkan recall 0.9976 pada threshold 0.84, tetapi angka tersebut **tidak boleh digunakan** sebagai metrik model absolut karena gold yang digunakan berbeda sumber dan stratifikasi. Lihat "Keterbatasan Gold Stratified" di bawah.

## Karakteristik Error

- **FP = 4** pada threshold 0.35/0.50/0.82/0.84: ini adalah 4 pasangan `no_match` gold yang memiliki skor `>= 0.9` (sangat tinggi). Ini menunjukkan adanya pasangan di mana model sangat yakin tapi human reviewer menandai sebagai berbeda entitas — kemungkinan besar kasus perubahan email/telepon, typo serius, atau data salah masukan.
- **FN = 0** terdeteksi di wilayah skor yang tersedya, tetapi ini **tidak berarti** tidak ada false negative di populasi sebenarnya. Karena gold stratified, tidak ada pasangan `match` gold yang memiliki skor di wilayah threshold standar. Hal ini menyiratkan bahwa model memberikan skor sangat rendah untuk pasangan yang sebenarnya match, atau gold set ini berisi pasangan yang *tidak seharusnya* di-set match berdasarkan evidensi lain.
- Pita REVIEW praktis kosong pada gold ini (karena tidak ada pasangan di wilayah `0.35 <= P < 0.84` yang memiliki label `match`).

## Keterbatasan Gold Stratified (Wajib Dibaca)

1. **Gold labels tidak independen random** — strata sampel dipilih berdasarkan perilaku model (`unlabelled_high_probability`, `singleton_candidate`, dll.), sehingga recall/precision dari evaluasi ini **TIDAK BISA diekstrapolasi** ke seluruh populasi kandidat. Angka di bawah hanya berlaku untuk subset ini.

2. **Provenance `gold_labels.csv`** — skor ditulis ke kolom `match_probability` dari run yang tidak terdokumentasi secara lengkap; model/versi tidak tercatat di gold. Angka di atas sah untuk file gold ini, **bukti tidak** performa model aktif (`v20261116_122048` atau versi lain).

3. **378 pasangan tanpa skor tidak dihitung** — mereka adalah pasangan di luar blocking; tidak termasuk recall maupun precision, sesuai batas cakupan blocking.

4. **Evaluasi vs device-channel belum dilakukan** — jika ingin mengukur akurasi mandiri dari model (tanpa gold human review), jalankan `python -m src.evaluate` atau `python -m src.final_eval.py` untuk melaporkan metrik pada `device_ids_std` channel.

5. **Sampel lama (`3.215 pasangan`)** — data dari `outputs/gold_scored.parquet` (snapshot lama) menunjukkan recall 0.9976 @ threshold 0.84, tetapi **dilarang menggunakan** angka ini sebagai klaim performa model karena gold stratified dan versi model berbeda.

## Langkah Berikutnya

1. **Jangan menggunakan angka precision/recall dari tabel di atas sebagai klaim produksi** — catatan keterbatasan di atas wajib dibaca sebelum menginterpretasi apapun.

2. Regenerasi `outputs/splink_predictions.parquet` (jika butuh prediksi penuh untuk evaluasi mandiri vs device-channel):
   ```bash
   python -m src.splink_model --full
   ```

3. Jalankan evaluasi mandiri (tanpa gold human review) untuk mendapatkan metrik yang bisa diekstrapolasi:
   ```bash
   python -m src.evaluate
   ```

4. Perbarui `docs/metadata_pipeline.md` bagian "7. Model Versioning" jika perlu merefleksikan angka lama (`0.9431` @ 0.9) vs hasil aktual.

5. Dokumentasikan dalam laporan internal bahwa **semua angka recall/precision dari gold ini bersifat *hanya untuk subset gold stratified*** dan tidak bisa diekspri sebagai performa model umum.