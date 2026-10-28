# System Dedupe with Splink

### Probabilistic Record Linkage menggunakan Splink, DuckDB, dan Streamlit

Sistem **CRM Entity Resolution & Deduplication** untuk mendeteksi, mengevaluasi, dan mengelola duplikasi data pelanggan menggunakan pendekatan *probabilistic record linkage*.

Pipeline utama:

<img width="2265" height="2151" alt="Image" src="https://github.com/user-attachments/assets/692a6d6a-58e0-4b1a-92e5-b2928cf18eb6" />

Dibangun menggunakan **Python, Splink, DuckDB, Pandas, PyArrow, dan Streamlit**.

---

## 0. Workflow Lengkap Sistem Entity Resolution

Berikut alur lengkap data dari masuk hingga keluar sistem, mencakup komponen teknis dan flow human review:

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    DATA INPUT LAYER                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐    │
│  │   PostgreSQL     │  │   DuckDB Local   │  │    CSV Upload    │  │  Batch File      │    │
│  │  (crm-pg:5432)   │  │  (data/synthetic)│  │   (app.py)       │  │  (scripts/)      │    │
│  └────────┬─────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘    │
│           │                                                                                 │
└───────────┼─────────────────────────────────────────────────────────────────────────────────┘
             ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 VALIDASI & STANDARDISASI                                    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────┐   │
│  │ Schema Validation│ │ Column Mapping   │ │ Format Check    │ │ Normalization        │   │
│  │ (columns wajib) │  │ (DB → standard)  │ │ (date/phone)    │ │ (std fields)         │   │
│  └────────┬────────┘  └─────────────────┘  └─────────────────┘  └──────────────────────┘   │
│           │                                                                                 │
│           ▼                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐     │
│  │                         Standardized Dataset (Parquet)                           │     │
│  │  record_id | first_name_std | last_name_std | email_std | phone_std | ...       │     │
│  └──────────────────────────────────────────────────────────────────────────────────┘     │
└───────────┼─────────────────────────────────────────────────────────────────────────────────┘
            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 BLOCKING / CANDIDATE GENERATION                             │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 14 Blocking Rules (src/config.py):                                                  │  │
│  │   • first_name_exact, last_name_exact                                               │  │
│  │   • email_exact, phone_exact, dob_exact                                             │  │
│  │   • first_name_phonetic, last_name_phonetic                                         │  │
│  │   • city_state_dob, email_domain                                                    │  │
│  │   • phone_last4, address_hash, etc.                                                 │  │
│  │  (rules dipilih berdasarkan coverage & skor probabilistik)                          │  │
│  └───────────────────────┬──────────────────────────────────────────────────────────────┘  │
│                          ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                Candidate Pairs (dari O(N²) → ratusan ribu)                           │  │
│  │  record_id_1 | record_id_2 | blocking_rule | ...                                     │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────┼─────────────────────────────────────────────────────────────────────────────────┘
            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              SPLINK PROBABILISTIC RECORD LINKAGE                            │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Splink Model (v20261027_161903):                                                    │  │
│  │   • M-probabilities: name_exact=0.85, fuzzy=0.50, phonetic=0.30, else=0.10          │  │
│  │   • U-probabilities: based on field uniqueness                                      │  │
│  │   • Comparison levels: exact, fuzzy, phonetic, regex, etc.                          │  │
│  └───────────────────────┬──────────────────────────────────────────────────────────────┘  │
│                          ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │              Pairwise Match Probabilities (gamma scores)                             │  │
│  │  record_id_1 | record_id_2 | match_probability | blocking_rule | ...                 │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────┼─────────────────────────────────────────────────────────────────────────────────┘
            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 DECISION CLASSIFICATION                                     │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Threshold Rules:                                                                    │  │
│  │   • ≥ 0.95 → AUTO MATCH (23.081 pairs)                                               │  │
│  │   • ≤ 0.01 → AUTO NON_MATCH (1.449.659 pairs)                                        │  │
│  │   • 0.01 - 0.95 → REVIEW MANUAL (50.220 pairs)                                       │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
│                          │                          │                         │            │
│                          ▼                          ▼                         ▼            │
│  ┌────────────────────┐   ┌────────────────────┐  ┌────────────────────┐      │            │
│  │   AUTO MATCH       │   │   AUTO NON_MATCH   │  │   REVIEW QUEUE     │      │            │
│  │   → langsung       │   │   → langsung       │  │   → human review   │      │            │
│  │   cluster/master   │   │   discard          │  │   (pages/1_review) │      │            │
│  └────────────────────┘   └────────────────────┘  └────────────────────┘      │            │
└───────────┼─────────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                              HUMAN REVIEW (Opsional)                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Review Queue (pages/1_review, pages/5_queue):                                       │  │
│  │   • Tampilkan pasangan kandidat                                                      │  │
│  │   • Tampilkan evidence field-by-field                                               │  │
│  │   • Tampilkan match probability                                                     │  │
│  │   • Tombol: MATCH / NON_MATCH                                                       │  │
│  │   • Catat feedback ke data/labels/feedback.csv                                      │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
│                          │                                                                  │
│                          ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │              Feedback Labels (gold_labels.csv)                                       │  │
│  │  record_id_1 | record_id_2 | label (match/no_match) | reviewer | timestamp           │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────┼─────────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 CLUSTERING & ENTITY ID                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Connected Components Algorithm:                                                     │  │
│  │   • Match pairs → union-find / graph clustering                                     │  │
│  │   • Assign unique entity_id untuk setiap cluster                                    │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
│                          │                                                                  │
│                          ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │              Entity Map (entity_map.parquet)                                         │  │
│  │  record_id | entity_id                                                               │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────┼─────────────────────────────────────────────────────────────────────────────────┘
            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 MASTER RECORD GENERATION                                    │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Master Record Rules (pages/2_master):                                               │  │
│  │   • Ambil record dengan data paling lengkap                                         │  │
│  │   • Prioritas: non-null values, updated_at, source reliability                      │  │
│  │   • Merge fields dengan decision logic                                              │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
│                          │                                                                  │
│                          ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │              Master Customers (master_customers.parquet)                             │  │
│  │  entity_id | first_name | last_name | email | phone | ... | source_records          │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────┼─────────────────────────────────────────────────────────────────────────────────┘
            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 OUTPUT & DEPLOYMENT                                         │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Output Files:                                                                       │  │
│  │   • splink_predictions.parquet (all pairs)                                          │  │
│  │   • entity_map.parquet (record → entity)                                            │  │
│  │   • master_customers.parquet (one row per entity)                                   │  │
│  │   • run_summary.json (metrics, counts)                                              │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
│                          │                   │                     │                        │
│                          ▼                   ▼                     ▼                        │
│  ┌────────────────────────┐  ┌──────────────────────┐  ┌────────────────────────────────┐ │
│  │   FastAPI Endpoint     │  │   Streamlit Dashboard│  │   PostgreSQL (crm-pg)          │ │
│  │   (api/app.py)         │  │   (ui/app.py)        │  │   (monitoring/export)          │ │
│  │   • POST /predict      │  │   • overview charts  │  │   • customer_matches             │ │
│  │   • POST /predict/{id} │  │   • review queue     │  │   • model_metadata               │ │
│  │   • GET /matches       │  │   • master records   │  │   • review_queue                 │ │
│  └────────────────────────┘  └──────────────────────┘  └────────────────────────────────┘ │
└───────────┼─────────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 MONITORING & RETRAIN                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Metrics Collection (monitor/metrics.py):                                            │  │
│  │   • Match rate, review rate, coverage                                               │  │
│  │   • Precision/Recall (jika ground truth tersedia)                                   │  │
│  │   • Processing time per stage                                                       │  │
│  │   • Alert threshold (match rate ↓, volume ↑)                                        │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
│                          │                                                                  │
│  ┌───────────────────────┴──────────────────────────────────────────────────────────────┐  │
│  │  Retrain Trigger (monitor/scripts/monitor_retrain.py):                              │  │
│  │   • Scheduled (batch harian/mingguan)                                               │  │
│  │   • Event-based (feedback volume ↑, drift detection)                                │  │
│  │   • Manual (pages/4_retrain.py)                                                     │  │
│  └──────────────────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Workflow Deskripsi Per Stage

### 1. Data Input Layer
**Sumber data masuk ke sistem melalui 4 channel:**
- **PostgreSQL**: Sistem CRM eksternal (crm-pg Docker container), membaca tabel `crm_customers`
- **DuckDB Local**: File database lokal untuk demo development
- **CSV Upload**: File `.csv` diupload via Streamlit UI (pages/upload.py)
- **Batch File**: Script terjadwal di `scripts/batch_predict.py` untuk proses harian

### 2. Validasi & Standardisasi
**Setiap record melewati pipeline pembersihan:**
- **Schema validation**: Cek kolom wajib, tipe data, delimiter
- **Column mapping**: Konversi field sumber ke format standard (DB_COLUMN_MAP di src/config.py)
- **Format check**: Validasi format email, phone, tanggal
- **Standardization**: Transformasi ke bentuk konsisten (lowercase, normalize phone, extract domain email)
- **Hasil**: Dataset parquet dengan suffix `_std` untuk field yang telah dinormalisasi

### 3. Blocking / Candidate Generation
**Mengurangi kompleksitas O(N²) dengan filtering:**
- **14 blocking rules** aktif (dikonfigurasi di src/config.py)
- Aturan berbasis: exact match, phonetic (SoundEx), fuzzy (Levenshtein), hash, timestamp
- Setiap pasangan kandidat dicatat blocking rule yang menyebabkannya muncul
- Output: subset pasangan yang layak dibandingkan (bukan semua pasangan)

### 4. Splink Probabilistic Record Linkage
**Algoritma Fellegi-Sunter untuk match probability:**
- Model version `v20261027_161903` (trained dengan EM algorithm)
- M-probabilities (match probabilities): name_exact=0.85, name_fuzzy=0.50, phone_phonetic=0.30
- U-probabilities (uniqueness): based on field frequency di population
- Comparison levels: exact, fuzzy, phonetic, regex, case_statement
- Output: match_probability (0.0–1.0) untuk setiap pasangan

### 5. Decision Classification
**Thresholding untuk kategori keputusan:**
- **AUTO MATCH (≥0.95)**: 23.081 pairs — langsung dimasukkan cluster
- **AUTO NON_MATCH (≤0.01)**: 1.449.659 pairs — diabaikan
- **REVIEW MANUAL (0.01–0.95)**: 50.220 pairs — perlu konfirmasi human
- **Optimal threshold**: 0.86 (Recall=0.9886, Precision=0.9263, F1=0.9564)

### 6. Human Review (Opsional tapi Direkomendasikan)
**Interface untuk verifikasi pasangan ambiguitas:**
- **pages/1_review.py**: Review single pair dengan full evidence
- **pages/5_queue.py**: Daftar pasangan REVIEW yang pending
- **pages/6_batch.py**: Review batch baru sebelum digabung ke master
- Feedback disimpan di `data/labels/feedback.csv` dan `gold_labels.csv`

### 7. Clustering & Entity ID
**Graph-based clustering untuk mengelompokkan record:**
- Algorithm: Connected Components (union-find)
- Match pairs → graph edges → clusters → entity_id
- Output: `entity_map.parquet` (record_id → entity_id mapping)

### 8. Master Record Generation
**Representasi tunggal untuk setiap entity:**
- Ambil field non-null dengan prioritas<unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk>
 the
\'t;
.;<unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk><unk>: