# Catatan Lanjutan — DB Input + Fase 2/3

Diperbarui: 2026-10-13. Dokumen ini untuk melanjutkan pekerjaan di sesi berikutnya.
Baca bagian "Belum dikerjakan" dulu, lalu "Keputusan yang tertunda".

---

## 1. Yang sudah selesai dan teruji

| Item | File | Status |
|---|---|---|
| Konektor DB read-only (DuckDB, lokal `.duckdb` / `postgres://`) | `src/db_source.py` | Teruji via Postgres lokal |
| Export DB → batch CSV + registrasi | `src/db_export.py` | Teruji |
| Satu perintah: fetch → register → `incremental --stage` | `src/job_run.py` | Teruji, exit code + `outputs/job_run_summary.json` |
| Update record lama (bukan buat record baru) | `src/db_refresh.py` | Teruji |
| Kamus kolom DB → pipeline | `src/config.py` → `DB_COLUMN_MAP` | 4 unit test lolos |
| Generator data sintetik | `scripts/make_synthetic_db.py` | Teruji |
| Lepas batch dari registry | `src/registry.py` → `unregister()` | Baru |
| Dokumentasi cara pakai | `docs/DB_INTEGRATION.md` | Baru |
| Fix `corruption_score` (per-kolom, repeats dihapus) | `src/master_record.py` | 1.142 sel master berubah (0,13%) |

### Perintah yang sudah jalan

```powershell
# data sintetik
python scripts/make_synthetic_db.py --rows 2000 --out data/synthetic/crm.duckdb

# Fase 2 — insert baru
python -m src.job_run --config config/job.json --date-order dmy

# Fase 3 — update record berubah
python -m src.db_refresh --source data/synthetic/crm.duckdb --table crm_customers --date-order dmy

# export saja tanpa scoring
python -m src.db_export --source ... --table ... --watermark
```

### Yang sudah dibuktikan

- Idempoten: re-run kedua → `0 rows`, exit 0, tidak ada data ganda.
- Watermark hanya maju setelah seluruh job sukses (perbaikan: sebelumnya maju
  sebelum incremental, batch jadi orphan dan tidak bisa di-retry).
- Retry: kalau incremental gagal, export mendeteksi "sudah terdaftar" (sha256)
  lalu lanjut ke incremental memakai batch lama.
- Read-only benar-benar enforced: `crm_reader` SELECT jalan, INSERT →
  `permission denied for table crm_customers`.
- Tanggal DB (DATE → datetime64) diterjemahkan ke string di connector, kalau
  tidak `dob_std` jadi None diam-diam.
- `customer_pk` float (`2001.0`) vs int (`2001`) dinormalkan via `_pk_str`.

---

## 2. BELUM DIKERJAKAN — prioritas besok

### P1. Bersihkan parquet dari baris sintetik ⚠️

`data/processed/crm_standardized.parquet` terkontaminasi **2003 baris tes**
(`rec_101856..rec_103858`, kolom `customer_pk` terisi). Akibatnya:

```
rows     101.855 → 103.858
entities 93.659  → 95.659
smoke test 43/43 → 42/43  (FAIL: incremental_candidate_prefilter_is_exact)
```

Root cause sudah diverifikasi dengan kontrol bersih:

```
tanpa baris sintetik (101.855) : MATCH diff = 0  → lolos
dengan baris sintetik (103.858): MATCH diff = 1  → gagal
                                pasangan rec_102366 ↔ rec_103049
```

Cara membersihkan: buang baris yang `customer_pk` tidak null dari parquet,
lalu jalankan ulang `python -m src.clustering --full` dan
`python -m src.master_record` supaya entity/master ikut kembali. Backup dulu
file-nya sebelum diubah.

### P2. Temuan nyata dari kegagalan test (pre-filter tidak persis setara)

Ini bukan cuma masalah data tes. `candidate_old_rows` melewatkan 1 MATCH edge
antar dua baris. Artinya inspeksi #6 (TF dihitung pada subset) dan
ketidaksetaraan pre-filter punya konsekuensi nyata, bukan sekadar teori.
Perlu diputuskan: catat sebagai keterbatasan, atau selidiki pasangannya.

### P3. Tentukan skema output — keputusan manusia

Empat hal ini harus diputuskan sebelum `db_push.py` bisa ditulis:

1. Berapa tabel output — 1 (cuma peta) atau 2 (+ nilai master)?
2. Kolom persis tiap tabel.
3. Primary key tiap tabel output (untuk upsert idempoten).
4. Sumber nilai master → **sudah disepakati: nilai RAW, bukan `_std`**.

Usulan minimal yang pernah diajukan:

```
dedup_results.entity_assignment
  customer_pk   (PK dari sumber)
  record_id     (ID internal pipeline)
  entity_id     (hasil pengelompokan)
  model_version
  resolved_at
```

Setelah 1–4 jelas: tulis `src/db_push.py` dengan `--dry-run`, `--upsert`,
summary JSON, exit code.

### P4. Halaman Streamlit untuk tarik dari DB

Sekarang jalur DB **hanya CLI**. `app.py` masih `st.file_uploader` murni.
Kalau demo ke atasan, dia tidak bisa klik tombol. Perlu halaman baru
(misal `pages/10_db.py`).

---

## 3. Keputusan yang tertunda / sudah disepakati

| Topik | Status |
|---|---|
| Nilai master dikembalikan pakai **RAW** | Sudah disepakati |
| Jalur DB pakai **CLI dulu**, tanpa Streamlit | Sudah disepakati |
| Kirim ke DB: DS tulis script, backend bikin skema + akun + jadwal | Sudah disepakati |
| Apakah hanya peta entitas atau + nilai master | **Belum** |
| Format kolom tabel output | **Belum** |
| Apakah `REVIEW_THRESHOLD` dinaikkan | **Belum** (lihat §4) |

---

## 4. Temuan dari inspeksi kode (belum ditangani)

### 4.1 Angka review — README basi

README §15 menulis `REVIEW = 27`. Angka aktual yang diukur:

```
predictions  1.148.963
MATCH          9.833
REVIEW         4.585   ← bukan 27
NON_MATCH  1.134.545
review_queue     681   (386 sudah diperiksa, 295 pending)
```

### 4.2 Komposisi REVIEW — tiga jalur masuk

`decision` bukan murni threshold; ada override aturan bisnis:

| Jalur | Mekanisme | Jumlah |
|---|---|---|
| Pita biasa | `1e-8 ≤ P < 0.9` | ~4.570 |
| Override aturan 1 | `P ≥ 0.9` tapi email+nama+alamat identik & dob beda/kosong → dipaksa REVIEW | 15 |
| Kebalikannya | 0 field identitas cocok → dipaksa NON_MATCH walau `P > 1e-8` | 112 |

Distribusi skor di REVIEW:

```
1e-8 .. 1e-6   4.075  (89%)  ← noise, kemungkinan besar beda orang
1e-6 .. 1e-4     456
1e-4 .. 1e-3      31
1e-3 .. 1e-2       6
1e-2 .. 0.1        1
0.1  .. 0.9        1
>= 0.9            15       ← paling berbahaya: skor sempurna, dob konflik
```

Antrian sudah diurutkan benar (`labels.py:324`):
`sort_values(["agree_count","match_probability"], descending)` — jadi 15 kasus
berbahaya (banyak field cocok) muncul paling atas.

**Ide yang BELUM dievaluasi:** menaikkan `REVIEW_THRESHOLD` dari `1e-8` ke
`1e-6` akan membuang ~4.075 noise. TAPI smoke test mencatat
`lowest gold positive 1.555e-08` — artinya `1e-6` **akan** membuang gold
positive. Jangan naikkan tanpa eksperimen di gold set.

### 4.3 Enam temuan inspeksi — status

| # | Temuan | Prioritas | Status |
|---|---|---|---|
| 1 | `entity_id` bisa bergeser kalau **registry** berubah (bukan saat retrain dengan registry tetap) | Tinggi | Belum — perlu komunikasi ke downstream |
| 2 | `BENCHMARK_RULES` hardcoded → `SystemExit` kalau `dob` hilang → multi-client gagal | Sedang (PoC aman) | Belum |
| 3 | `m_else_level_floor` per-kolom belum ada baseline eksperimen (config sendiri menulis "ASSUMPTION") | Tinggi — false negative diam-diam | Belum |
| 4 | `corruption_score` cacat utk kolom tanggal | Sedang | ✅ **Sudah diperbaiki hari ini** |
| 5 | `REVIEW_THRESHOLD 1e-8` → 4.585 pasangan | Tinggi | Belum — lihat §4.2 |
| 6 | TF dihitung pada subset, bukan corpus penuh | Rendah (sudah diukur: 12/1.172) | Belum — kaitkan dengan §2 P2 |

**Catatan soal #1:** `batch_eval.py:72` sudah mengukur
`old_entity_ids_changed`, dan `batch_eval.py:107` mencatat di runtime.
Jadi ini known issue dengan meteran, bukan temuan baru. Yang belum ada adalah
komunikasi/kontrak ke sistem downstream.

**Catatan soal #3:** risiko spesifik — pasangan valid dengan **dob salah
ketik** kena floor `0.001` → jatuh NON_MATCH, lolos dari review, hilang
diam-diam. Perlu diukur di gold set: berapa gold positive yang punya `dob` beda.

---

## 5. Konteks latihan Docker/Postgres

Container masih bisa dibuat ulang (perintah lengkap ada di
`docs/DB_INTEGRATION.md` §6). Kredensial latihan lokal:

```
host      127.0.0.1:5432   (bind localhost saja, bukan jaringan)
db        crm
owner     crm_owner     (write — hanya untuk setup)
reader    crm_reader     (SELECT saja — dipakai pipeline)
table     crm_customers  (2003 baris)
```

Kredensial ini HANYA untuk latihan lokal. DB asli: ambil dari env var /
secret manager, jangan hardcode.

**Kalau DB asli datang, urutan pengerjaan:**

1. Minta backend: host, port, nama DB, nama tabel, **akun read-only**.
2. `SELECT * FROM tabel LIMIT 0` → cocokkan nama kolom → isi `DB_COLUMN_MAP`.
3. Cek ada `updated_at` (timezone konsisten, semua UTC atau semua lokal) dan
   kolom PK stabil (`customer_id` terbukti TIDAK unik — 4.870 nilai kembar
   di dataset lama, jangan dipakai sebagai PK).
4. Tes kecil: `python -m src.db_export --source postgres://... --table ... --watermark`

---

## 6. Yang perlu ditanyakan ke backend / atasan

1. Data kantor pakai PostgreSQL (sudah dikonfirmasi). Perlu: host, port,
   nama DB, nama tabel/view, akun read-only, daftar kolom + tipe datanya.
2. Apakah tabel itu punya `updated_at`? Kalau tidak, perlu strategi lain
   untuk deteksi perubahan.
3. Apakah ada kolom PK yang benar-benar unik dan stabil?
4. Kalau hasil dedup mau dikembalikan ke DB: siapa bikin skema
   `dedup_results`, dan apakah boleh ada akun tulis khusus ke situ saja.
