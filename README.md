# System Dedupe with Splink

### Probabilistic Record Linkage menggunakan Splink, DuckDB, dan Streamlit

Sistem **CRM Entity Resolution & Deduplication** untuk mendeteksi, mengevaluasi, dan mengelola duplikasi data pelanggan menggunakan pendekatan *probabilistic record linkage*.

Pipeline utama:

<img width="2265" height="2151" alt="Image" src="https://github.com/user-attachments/assets/692a6d6a-58e0-4b1a-92e5-b2928cf18eb6" />

Dibangun menggunakan **Python, Splink, DuckDB, Pandas, PyArrow, dan Streamlit**.

---

## 0. Workflow Lengkap Sistem Entity Resolution

Berikut alur lengkap data dari masuk hingga keluar sistem, mencakup komponen teknis dan flow human review:

```mermaid
graph TD
    %% Input Layer
    A[Data Input Layer] --> A1[PostgreSQL crm-pg:5432]
    A --> A2[DuckDB Local]
    A --> A3[CSV Upload]
    A --> A4[Batch File scripts/]

    %% Validation & Standardization
    A --> B[Validasi & Standardisasi]
    B --> B1[Schema Validation]
    B --> B2[Column Mapping]
    B --> B3[Format Check]
    B --> B4[Normalisasi]
    B --> C[Standardized Dataset Parquet]

    %% Blocking
    C --> D[Blocking / Candidate Generation]
    D --> D1[14 Blocking Rules src/config.py]
    D --> D2[Candidate Pairs O(N²) → ratusan ribu]

    %% Splink Model
    D --> E[Splink Probabilistic Record Linkage]
    E --> E1[Splink Model v20261027_161903]
    E --> E2[M-probabilitas & U-probabilitas]
    E --> E3[Pairwise Match Probability gamma scores]

    %% Decision Classification
    E3 --> F[Decision Classification Threshold]
    F --> F1[≥ 0.95 AUTO MATCH]
    F --> F2[≤ 0.01 AUTO NON_MATCH]
    F --> F3[0.01 - 0.95 REVIEW MANUAL]

    %% Auto Match Path
    F1 --> G[Clustering & Entity ID Union-Find]
    G --> H[Entity Map record_id → entity_id]
    H --> I[Master Record Generation]
    I --> J[Master Customers master_customers]

    %% Auto Non-Match Path: ARCHIVE, NOT DISCARD
    F2 --> K[Archive Non-Match customer_matches.status = NON_MATCH]
    K --> K1[Disimpan untuk audit & monitoring]
    K1 --> L[Output & Deployment]

    %% Review Path
    F3 --> M[Human Review Opsional]
    M --> M1[Review Queue pages/1_review, pages/5_queue]
    M --> M2[Feedback gold_labels.csv]
    M2 --> N[Retrain Model monitor/scripts/monitor_retrain.py]
    N --> L

    %% Output & Deployment
    L --> L1[FastAPI Endpoint api/app.py]
    L --> L2[Streamlit Dashboard ui/app.py]
    L --> L3[PostgreSQL crm-pg monitoring & export]
    L --> L4[Output Files Parquet + JSON]

    %% Monitoring & Retrain
    L4 --> O[Monitoring & Retrain monitor/metrics.py]
    O --> O1[Match rate, review rate, coverage]
    O --> O2[Alert threshold violation]
    O --> O3[Retrain trigger scheduled/event-based/manual]

    %% Styling
    classDef input fill:#e1f5fe,stroke:#015797
    classDef process fill:#e8f5e9,stroke:#2e7d32
    classDef decision fill:#fff3e0,stroke:#ef6c00
    classDef output fill:#f3e5f5,stroke:#7b1f2e
    classDef archive fill:#fff9c4,stroke:#fbc02d
    classDef review fill:#ffecb3,stroke:#ffa000

    class A,A1,A2,A3,A input
    class B,B1,B2,B3,B4,C,D,D1,D2,E,E1,E2,E3,F,F1,F2,F3,G,H,I,J process
    class F1,F2,F3,K,K1,L1,L2,L3,L4 output
    class M,M1,M2,N archive
    class O,O1,O2,O3 review
```

### Deskripsi Per Stage

#### 1. Data Input Layer
**Sumber data masuk ke sistem melalui 4 channel:**
- **PostgreSQL**: Sistem CRM eksternal (crm-pg Docker container), membaca tabel `crm_customers`
- **DuckDB Local**: File database lokal untuk demo development
- **CSV Upload**: File `.csv` diupload via Streamlit UI (pages/upload.py)
- **Batch File**: Script terjadwal di `scripts/batch_predict.py` untuk proses harian

#### 2. Validasi & Standardisasi
**Setiap record melewati pipeline pembersihan:**
- **Schema validation**: Cek kolom wajib, tipe data, delimiter
- **Column mapping**: Konversi field sumber ke format standard (DB_COLUMN_MAP di src/config.py)
- **Format check**: Validasi format email, phone, tanggal
- **Standardization**: Transformasi ke bentuk konsisten (lowercase, normalize phone, extract domain email)
- **Hasil**: Dataset parquet dengan suffix `_std` untuk field yang telah dinormalisasi

#### 3. Blocking / Candidate Generation
**Mengurangi kompleksitas O(N²) dengan filtering:**
- **14 blocking rules** aktif (dikonfigurasi di src/config.py)
- Aturan berbasis: exact match, phonetic (SoundEx), fuzzy (Levenshtein), hash, timestamp
- Setiap pasangan kandidat dicatat blocking rule yang menyebabkannya muncul
- Output: subset pasangan yang layak dibandingkan (bukan semua pasangan)

#### 4. Splink Probabilistic Record Linkage
**Algoritma Fellegi-Sunter untuk match probability:**
- Model version `v20261027_161903` (trained dengan EM algorithm)
- M-probabilities (match probabilities): name_exact=0.85, name_fuzzy=0.50, phone_phonetic=0.30
- U-probabilities (uniqueness): based on field frequency di population
- Comparison levels: exact, fuzzy, phonetic, regex, case_statement
- Output: match_probability (0.0–1.0) untuk setiap pasangan

#### 5. Decision Classification
**Thresholding untuk kategori keputusan:**
- **AUTO MATCH (≥0.95)**: 23.081 pairs — langsung dimasukkan cluster
- **AUTO NON_MATCH (≤0.01)**: 1.449.659 pairs — **disimpan untuk audit** (tidak dibuang/discard)
- **REVIEW MANUAL (0.01–0.95)**: 50.220 pairs — perlu konfirmasi human
- **Optimal threshold**: 0.86 (Recall=0.9886, Precision=0.9263, F1=0.9564)

> **Catatan penting**: Data AUTO NON_MATCH **tidak dibuang**. Status `NON_MATCH` disimpan di tabel `customer_matches` untuk keperluan audit, monitoring, dan retrain model di masa depan.

#### 6. Human Review (Opsional tapi Direkomendasikan)
**Interface untuk verifikasi pasangan ambiguitas:**
- **pages/1_review.py**: Review single pair dengan full evidence
- **pages/5_queue.py**: Daftar pasangan REVIEW yang pending
- **pages/6_batch.py**: Review batch baru sebelum digabung ke master
- Feedback disimpan di `data/labels/feedback.csv` dan `gold_labels.csv`

#### 7. Clustering & Entity ID
**Graph-based clustering untuk mengelompokkan record:**
- Algorithm: Connected Components (union-find)
- Match pairs → graph edges → clusters → entity_id
- Output: `entity_map.parquet` (record_id → entity_id mapping)

#### 8. Master Record Generation
**Representasi tunggal untuk setiap entity:**
- Ambil field non-null dengan prioritas: data completeness, update time, source reliability
- Merge strategy: most recent, most complete, or weighted vote
- Output: `master_customers.parquet` (one row per entity)

#### 9. Output & Deployment
**Distribusi hasil ke berbagai destination:**
- **Local files**: Parquet files untuk development/analysis
- **FastAPI**: REST endpoint (`api/app.py`) untuk aplikasi eksternal
- **Streamlit Dashboard**: UI interaktif (`ui/app.py`) untuk visualisasi
- **PostgreSQL**: Export hasil ke database produksi (crm-pg container)

#### 10. Monitoring & Retrain
**Sistem observability dan model maintenance:**
- **Metrics**: Match rate, review rate, processing time, coverage
- **Alerting**: Threshold violation detection
- **Retrain schedule**: Daily/weekly batch atau event-driven
- **Manual trigger**: pages/4_retrain.py untuk expert override

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