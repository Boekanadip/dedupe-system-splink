# Blocking Rules — CRM Entity Resolution (Splink)

## Sumber aktif
- Aturan prediksi/training dimuat via `src.config.load_benchmark_rules()`.
- Jika `config/blocking_rules.json` ada: pakai isi file itu.
- Jika tidak ada (kondisi repo saat ini): fallback `DEFAULT_BENCHMARK_RULES` di `src/config.py`.

## Default blocking rules saat ini (12, unik per kombinasi kolom)
| Rule Name | Columns | Tujuan singkat |
|---|---|---|
| `email_exact` | `email_std` | Kecocokan email persis |
| `phone_exact` | `phone_std` | Kecocokan telepon persis |
| `name_exact` | `first_name_std`, `last_name_std` | Nama lengkap sama |
| `city_dob` | `city_std`, `dob_std` | Kota + DOB |
| `dob_exact` | `dob_std` | DOB persis |
| `address_city` | `address_std`, `city_std` | Alamat + kota |
| `phone_prefix` | `phone_pre7` | Prefix telepon (7 digit) |
| `name_prefix` | `last_name_std_pre3`, `first_name_std_pre3` | Prefix nama depan/belakang |
| `city_state_dob_year` | `city_std`, `state_std`, `dob_year_std` | Kota + state + tahun lahir |
| `city_state_dob` | `city_std`, `state_std`, `dob_std` | Kota + state + DOB |
| `phone_last4` | `phone_last4`, `dob_year_std` | 4 digit akhir telepon + tahun lahir |
| `name_fuzzy_last4` | `last_name_std_pre3`, `phone_last4` | Prefix nama belakang + 4 digit telepon |

## Hasil eksperimen (40k processed, gold+device-truth, 2026-11-16)
| Konfigurasi | Kandidat | Coverage gold (in-scope) | Coverage truth | Catatan |
|---|---:|---:|---:|---|
| 15 aturan (sebelum pangkas redundan) | 175,832 | 100% | 100% | baseline sesudah hapus `email_domain` |
| Tanpa `email_domain_name` | 175,832 | 100% | 100% | 0 marginal (redundan) |
| Tanpa `name_prefix_state` | 86,699 | 100% | 100% | -51% kandidat, 0 marginal |
| 12 aturan (aktif sekarang) | 86,699 | 100% | 100% | dipangkas berdasarkan bukti di atas |
| Core 5 (`email_exact,phone_exact,name_exact,dob_exact,city_state_dob`) | 56,230 | 100% | 100% | opsi lebih agresif; perlu validasi data lain |

## Catatan
- Kandidat = **union** semua aturan (deduplikasi pasangan). Aturan dengan overlap sinyal tetap menambah biaya hitung blok; perlu benchmark (jumlah kandidat, coverage/recall, runtime, ukuran blok) sebelum menambah/menghapus.
- Jalur fixed: prediksi memakai union `BENCHMARK_RULES`; training EM memakai subset aturan yang tidak menyentuh field inti identitas (`src/splink_model.py`).
- `DETERMINISTIC_RULES` terpisah (`email_std`, `phone_pre7`) dipakai untuk estimasi parameter awal (lambda), bukan daftar prediksi.
- Angka performa/recall/ukuran blok bersifat **tidak terverifikasi di dokumen ini**; ukur dengan `python -m src.blocking_benchmark` pada data aktual.