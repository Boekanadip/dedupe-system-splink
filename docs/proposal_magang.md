# PROPOSAL MAGANG

## Penerapan Probabilistic Record Linkage untuk Perbaikan Deteksi Duplikat Data Customer CRM

| Field | Isian |
|---|---|
| Nama | `[NAMA]` |
| NIM | `[NIM]` |
| Program Studi | `[PROGRAM STUDI]` |
| Instansi Pendidikan | `[INSTANSI PENDIDIKAN]` |
| Tempat Magang | `[NAMA PERUSAHAAN / UNIT]` |
| Mentor | `[NAMA MENTOR]` |
| Periode | `[TANGGAL MULAI]` sampai `[TANGGAL SELESAI]` |
| Tempat Penulisan | `[KOTA]`, `[TANGGAL]`. |

---

## Inti Penelitian

- **Objek**: duplikat data customer pada dataset development Customer 360 dan artefak lokal proyek CRM Entity Resolution.
- **Masalah**: pencocokan eksak melewatkan duplikat karena perbedaan ejaan, format telepon, dan perubahan email. Pemeriksaan manual tidak mengikuti pertumbuhan data.
- **Perlakuan**: alur `standardization → blocking → probabilistic linkage Splink → decision MATCH/REVIEW/NON_MATCH → human review`.
- **Pembanding**: baseline pencocokan eksak pada `email_std` atau `phone_std` versus konfigurasi Splink dengan 12 aturan blocking aktif.
- **Ukuran keberhasilan**: candidate count, coverage terhadap pasangan berlabel, precision, recall, F1, review rate, auto-match rate, dan runtime.
- **Batas klaim**: hasil berasal dari lingkungan lokal dan dataset development. `MATCH` adalah keputusan model, bukan kebenaran terverifikasi. Pasangan `REVIEW` tetap memerlukan manusia.

---

## Ringkasan

Proyek magang ini mengangkat perbaikan proses deteksi duplikat data customer CRM. Satu entitas dunia nyata dapat tercatat lebih dari satu kali ketika nama ditulis berbeda, nomor telepon memakai format lain, atau email berubah. Pencocokan eksak sering melewatkan kasus tersebut, sementara pengecekan manual tidak skala ketika jumlah record bertambah.

Pendekatan yang diusulkan adalah probabilistic record linkage dengan Splink. Alur kerja dimulai dari validasi skema, pembentukan `record_id`, standardisasi ke kolom `*_std` tanpa menimpa nilai mentah, pembangkitan pasangan kandidat lewat blocking, perhitungan `match_probability`, penetapan keputusan `MATCH`, `REVIEW`, atau `NON_MATCH`, lalu pencatatan hasil review manusia untuk evaluasi.

Eksperimen utama membandingkan baseline pencocokan eksak dengan konfigurasi Splink yang memakai 12 aturan blocking aktif. Kinerja diukur dari jumlah pasangan kandidat, cakupan pasangan berlabel, precision, recall, F1, laju review, laju auto-match, dan waktu komputasi. Label gold dipisahkan secara stratifikasi untuk mengurangi tumpang tindih antara penyetelan dan evaluasi.

Seluruh angka akan diperoleh dari eksperimen lokal dan tidak disajikan sebagai bukti kinerja produksi. Luaran proyek berupa pipeline yang dapat direproduksi, tabel hasil evaluasi, dokumentasi teknis, dan laporan magang.

**Kata kunci**: entity resolution, deduplikasi, Splink, blocking, human-in-the-loop, evaluasi model.

---

## 1. Latar Belakang

Data customer pada sistem CRM sering kali tidak bersih. Satu orang atau satu entitas dapat muncul dalam beberapa baris dengan nilai yang tidak identik. Perbedaan dapat berupa ejaan nama, singkatan alamat, format nomor telepon, ataupun perubahan email dari waktu ke waktu.

Ketika duplikat tidak terdeteksi, data master menjadi berantakan. Laporan dapat menghitung satu customer lebih dari satu kali. Segmentasi pemasaran dapat mengirim pesan berulang. Analisis lanjutan menjadi bias karena jumlah entitas tidak sesuai dengan kenyataan.

Pencocokan berbasis kesamaan persis hanya efektif ketika field identik. Pada data yang sudah mengalami standardisasi sebagian atau memiliki typo, pencocokan tersebut kehilangan pasangan yang sebenarnya sama. Di sisi lain, pemeriksaan manual memberi akurasi lebih tinggi, tetapi memerlukan waktu dan tidak dapat dijalankan pada seluruh pasangan ketika volume data bertambah.

Proyek ini telah membangun prototipe sistem Entity Resolution berbasis Splink dengan Python dan DuckDB. Sistem tersebut mencakup standardisasi, blocking, skor probabilitas, antrean review, pembentukan `entity_id`, dan versi model. Yang masih dibutuhkan adalah perumusan eksperimen yang jelas untuk membuktikan bahwa konfigurasi tersebut benar-benar memberi perbaikan, bukan sekadar berjalan pada demo.

Proposal ini merangkum rencana tersebut sebagai tugas magang dengan fokus pada perbaikan yang terukur dan dapat dipertanggungjawabkan.

---

## 2. Rumusan Masalah

1. Bagaimana penerapan standardisasi dan strategi blocking memengaruhi jumlah pasangan kandidat serta cakupan pasangan yang benar?
2. Bagaimana kinerja probabilistic linkage Splink dibandingkan baseline pencocokan eksak ditinjau dari precision, recall, dan F1 pada data berlabel?
3. Bagaimana perubahan ambang keputusan memengaruhi keseimbangan antara otomatisasi `MATCH` dan kebutuhan review manusia?

---

## 3. Tujuan Penelitian

1. Menerapkan alur standardisasi dan blocking yang dapat diukur cakupan dan biaya komputasinya.
2. Membandingkan kinerja Splink dengan baseline pencocokan eksak menggunakan metrik yang sama.
3. Menganalisis pengubahan ambang keputusan terhadap laju auto-match dan laju review.
4. Menghasilkan dokumentasi eksperimen yang dapat direproduksi dan tidak mengklaim lebih dari bukti yang ada.

---

## 4. Manfaat Penelitian

### 4.1 Manfaat Praktis

- Memberi dasar pengambilan keputusan untuk memilih konfigurasi deduplikasi, bukan hanya mengandalkan nilai ambang yang umum dipakai.
- Mengurangi ketergantungan pada pemeriksaan manual untuk pasangan yang sudah memiliki bukti kuat.
- Menyediakan antrean review yang menyimpan alasan skor, sehingga keputusan manusia dapat ditelusuri kembali.
- Menjaga data mentah tetap utuh melalui standardisasi pada kolom terpisah.

### 4.2 Manfaat Akademik

- Menyajikan penerapan entity resolution sebagai eksperimen terukur, bukan sekadar demonstrasi aplikasi.
- Memisahkan evaluasi blocking, linkage, dan decision sehingga tidak ada satu metrik tunggal yang menutupi kelemahan komponen lain.
- Menunjukkan batasan generalisasi ketika data yang dipakai berasal dari lingkungan development.

---

## 5. Ruang Lingkup

Penelitian ini dibatasi pada hal-hal berikut.

- Sumber data berupa file CSV dan artefak lokal DuckDB/Parquet yang tersedia di lingkungan pengembangan.
- Implementasi memakai Python, Splink, dan DuckDB pada komputasi lokal.
- Fokus pada deduplikasi dalam batch dan pencocokan record baru ke entitas yang sudah ada.
- Antarmuka Streamlit dipakai sebagai sarana demonstrasi dan review, bukan sebagai objek utama penelitian.
- Tidak mencakup deployment produksi, autentikasi, scheduler produksi, atau integrasi langsung dengan data klien.
- Volume produksi tidak diketahui, sehingga klaim skalabilitas tidak dibuat hanya dari dataset 50.000 record.

---

## 6. Tinjauan Pustaka Singkat

### 6.1 Entity Resolution

Entity Resolution adalah proses mengidentifikasi record yang merujuk pada entitas dunia nyata yang sama. Identitas sumber seperti `customer_id` tidak dapat langsung dianggap sebagai identitas entitas karena tidak selalu unik atau benar. Proyek ini membedakan tiga konsep, yaitu `record_id` untuk baris fisik, `customer_id` untuk identifier sistem sumber, dan `entity_id` untuk hasil resolusi.

### 6.2 Probabilistic Record Linkage

Pendekatan Fellegi dan Sun memodelkan keputusan pencocokan sebagai perbandingan bukti antarfield. Setiap field menyumbang bobot berdasarkan kemungkinan kecocokan dan ketidakcocokan. Splink menerapkan prinsip ini dengan menghitung `match_weight` dan `match_probability` untuk setiap pasangan kandidat.

### 6.3 Blocking

Blocking membatasi pasangan yang dibandingkan agar sistem tidak melakukan perbandingan seluruh pasangan record. Strategi blocking perlu diuji dari sisi jumlah kandidat, cakupan pasangan benar, waktu, dan ukuran blok. Aturan yang cepat tetapi kehilangan banyak pasangan benar tidak dapat dikatakan baik. Sebaliknya, aturan dengan cakupan tinggi tetapi volume kandidat berlebih juga bermasalah.

### 6.4 Human-in-the-Loop

Pasangan dengan bukti yang tidak meyakinkan tidak dipaksa menjadi `MATCH`. Pasangan tersebut masuk ke antrean `REVIEW` untuk diputuskan manusia. Hasil review disimpan sebagai label yang dapat dipakai kembali untuk evaluasi, analisis kesalahan, dan penyesuaian model di kemudian hari.

### 6.5 Evaluasi

Evaluasi dipisahkan menjadi empat bagian, yaitu evaluasi blocking, evaluasi linkage, evaluasi ambang keputusan, dan evaluasi entitas. Metrik yang dipakai meliputi candidate count, coverage, precision, recall, F1, false positive, false negative, review rate, auto-match rate, dan runtime. Angka hanya boleh dipakai jika berasal dari eksperimen yang sebenarnya dijalankan.

---

## 7. Metodologi

### 7.1 Jenis dan Pendekatan

Penelitian ini memakai pendekatan eksperimen kuantitatif dengan dukungan analisis deskriptif. Eksperimen dilakukan dengan membandingkan dua konfigurasi pada dataset yang sama. Analisis deskriptif dipakai untuk menjelaskan karakteristik data dan distribusi skor sebelum metrik dihitung.

### 7.2 Objek dan Sumber Data

- Dataset development: Customer 360, berkas `crm_50000_customers_dirty_v3.csv` dari Kaggle.
- Snapshot kerja lokal: registry batch dan `crm_standardized.parquet` pada direktori `data/processed/`.
- Label: `data/labels/gold_labels.csv` dan hasil review pada antrean `review_queue`.
- Artefak pendukung: konfigurasi model, metadata versi, dan laporan evaluasi lokal.

Data customer, model, dan hasil pipeline tidak disertakan pada clone bersih repository. Ketersediaan artefak lokal menjadi prasyarat sebelum eksperimen dijalankan.

### 7.3 Definisi Operasional

| Istilah | Definisi |
|---|---|
| `record_id` | Identitas internal untuk satu baris record fisik. |
| `customer_id` | Identitas dari sistem sumber, tidak otomatis menjadi kebenaran entitas. |
| `entity_id` | Identitas entitas hasil proses resolusi. |
| Pasangan kandidat | Dua record yang lolos minimal satu aturan blocking. |
| `match_probability` | Skor probabilitas bahwa dua record merujuk entitas yang sama. |
| `MATCH` | Keputusan otomatis ketika skor berada di atas ambang match. |
| `REVIEW` | Keputusan menunda ketika skor berada di antara ambang review dan ambang match. |
| `NON_MATCH` | Keputusan menolak ketika skor berada di bawah ambang review. |
| Coverage | Perbandingan pasangan benar yang berhasil masuk kandidat terhadap seluruh pasangan benar pada label referensi. |
| Precision | Proporsi pasangan yang diputuskan cocok dan memang benar. |
| Recall | Proporsi pasangan benar yang berhasil ditemukan. |
| F1 | Rata-rata harmonik precision dan recall. |
| Review rate | Proporsi pasangan yang masuk kategori `REVIEW`. |
| Auto-match rate | Proporsi pasangan yang langsung menjadi `MATCH` tanpa review. |

### 7.4 Prosedur Penelitian

1. **Audit repository dan artefak**  
   Memeriksa struktur kode, konfigurasi aktif, ketersediaan data, dan kondisi artefak lokal.

2. **Profiling dan validasi skema**  
   Memeriksa tipe kolom, nilai kosong, duplikat persis, dan kolom yang dibutuhkan aturan blocking.

3. **Standardisasi**  
   Membentuk kolom `*_std` seperti `first_name_std`, `email_std`, dan `phone_std`. Nilai mentah tidak ditimpa.

4. **Pembentukan baseline**  
   Membangun baseline berupa pencocokan eksak pada `email_std` atau `phone_std`. Baseline ini dipakai sebagai pembanding, bukan sebagai sistem produksi.

5. **Benchmark blocking**  
   Menjalankan 12 aturan blocking aktif, lalu mengukur jumlah pasangan kandidat, cakupan terhadap label referensi, dan waktu komputasi.

6. **Pemodelan Splink**  
   Membangun comparison levels, mengestimasi parameter dengan EM, lalu memberi skor pada pasangan kandidat.

7. **Penetapan keputusan**  
   Menerapkan ambang `MATCH=0.84` dan `REVIEW=0.35` sebagai konfigurasi awal. Nilai tersebut dapat diubah hanya jika evaluasi mendukung.

8. **Evaluasi**  
   Memisahkan label secara stratifikasi 80/20 dengan `random_state=42`, lalu menghitung precision, recall, F1, review rate, dan auto-match rate pada data uji.

9. **Analisis sensitivitas ambang**  
   Membandingkan beberapa nilai ambang untuk melihat pergeseran antara otomatisasi dan beban review. Hasilnya dipakai sebagai rekomendasi, bukan klaim final.

10. **Review dan dokumentasi**  
    Menyimpan pasangan abu-abu ke antrean review, mencatat alasan keputusan, lalu menuliskan hasil eksperimen beserta keterbatasannya.

### 7.5 Desain Eksperimen Utama

| Komponen | Baseline | Perlakuan |
|---|---|---|
| Pencocokan | `email_std` eksak atau `phone_std` eksak | Splink dengan 12 aturan blocking aktif |
| Skor | Tidak ada probabilitas | `match_probability` |
| Keputusan | Cocok atau tidak cocok | `MATCH`, `REVIEW`, `NON_MATCH` |
| Review | Tidak terstruktur | Antrean review dengan bukti perbandingan |
| Metrik utama | Precision, recall | Precision, recall, F1, coverage, review rate, runtime |

Perbandingan dilakukan pada dataset dan label yang sama. Jika satu konfigurasi unggul hanya karena label dipakai bersamaan untuk penyetelan dan pengujian, hasil tersebut tidak dianggap valid.

### 7.6 Instrumen Penelitian

- Python 3.11 atau lebih baru.
- Splink sebagai mesin linkage.
- DuckDB sebagai backend eksekusi lokal.
- Streamlit untuk antarmuka upload dan review.
- `gold_labels.csv` sebagai referensi evaluasi.
- Skrip eksperimen pada direktori `src/` dan `notebooks/`.

### 7.7 Teknik Analisis Data

Analisis dilakukan dengan pendekatan berikut.

1. Statistik deskriptif untuk karakteristik data dan distribusi skor.
2. Confusion matrix untuk setiap konfigurasi dan ambang.
3. Perhitungan precision, recall, F1, review rate, auto-match rate, dan runtime.
4. Perbandingan candidate count dan coverage antarstrategi blocking.
5. Analisis kesalahan pada pasangan false positive dan false negative.
6. Pemeriksaan konsistensi antara keputusan model dan label review manusia.

### 7.8 Validitas dan Reproducibility

- Label uji dipisahkan dari label yang dipakai untuk penyetelan.
- Split stratifikasi memakai `random_state=42` agar dapat diulang.
- Konfigurasi model, ambang, dan versi artefak dicatat.
- Skrip eksperimen dijalankan dari repository, bukan dari salinan manual.
- Nilai metrik disimpan bersama metadata sumber data dan versi model.
- Klaim hasil selalu disertai keterangan scope data dan metode pengukuran.

### 7.9 Aspek Etika dan Keamanan

- Data customer sensitif tidak disimpan di repository.
- Kredensial berasal dari environment variable atau file `.env` yang tidak di-commit.
- Nilai mentah dipertahankan dan tidak ditimpa oleh nilai standardisasi.
- Hasil review tidak dihapus tanpa jejak.
- Penghapusan record tidak dilakukan secara diam-diam. Jika diperlukan, dibuat penanda baru.
- `MATCH` tidak dipresentasikan sebagai fakta mutlak di hadapan pengguna.

---

## 8. Jadwal Kegiatan

| Minggu | Kegiatan | Luaran |
|---|---|---|
| 1 | Studi literatur, audit repository, dan penyusunan proposal | Proposal disetujui |
| 2 | Profiling data, validasi skema, dan pengecekan artefak | Ringkasan profil data |
| 3 | Standardisasi dan pembangunan baseline | Skrip baseline |
| 4 | Benchmark blocking dan pengukuran kandidat | Tabel perbandingan aturan |
| 5 | Training Splink dan scoring pasangan | Model dan prediksi |
| 6 | Evaluasi metrik dan analisis ambang | Tabel metrik dan catatan kesalahan |
| 7 | Review antrean, perbaikan dokumentasi, dan uji ulang | Artefak evaluasi final |
| 8 | Penyusunan laporan dan presentasi hasil | Laporan magang |

Jadwal dapat menyesuaikan ketersediaan data dan hasil eksperimen. Perubahan yang memengaruhi metode dicatat, bukan disembunyikan.

---

## 9. Luaran yang Diharapkan

1. Proposal magang dalam satu berkas.
2. Pipeline eksperimen yang dapat dijalankan ulang dari repository.
3. Tabel perbandingan baseline dan Splink.
4. Tabel benchmark blocking dan hasil uji ambang.
5. Ringkasan evaluasi berisi metrik, scope data, dan versi model.
6. Dokumentasi teknis yang menggambarkan kondisi aktual sistem.
7. Laporan magang berisi hasil, keterbatasan, dan rekomendasi lanjut.

Artefak yang memuat data customer mentah tidak dimasukkan ke dalam luaran yang dibagikan.

---

## 10. Indikator Keberhasilan

| Aspek | Indikator | Kriteria |
|---|---|---|
| Blocking | Jumlah pasangan kandidat | Lebih rendah atau sama dengan baseline yang sebanding pada cakupan yang sebanding |
| Blocking | Coverage pasangan benar | Tidak menurun dibanding baseline yang dipakai |
| Linkage | Precision, recall, F1 | Lebih baik dari baseline atau disertai penjelasan trade-off yang jelas |
| Keputusan | Review rate | Menurun atau tetap terkendali tanpa kenaikan false positive yang tidak dapat diterima |
| Keputusan | Auto-match rate | Meningkat hanya jika didukung evaluasi label |
| Operasional | Runtime | Diukur dan dilaporkan, tidak dijadikan klaim tanpa data |
| Dokumentasi | Reproducibility | Eksperimen dapat diulang dari skrip dan konfigurasi yang disimpan |
| Integritas | Keamanan data | Tidak ada data sensitif atau kredensial yang masuk repository |

Target berupa angka absolut tidak ditetapkan di proposal ini. Angka ditentukan setelah eksperimen dijalankan pada data yang tersedia.

---

## 11. Keterbatasan

1. Dataset yang dipakai adalah data development, bukan data produksi klien.
2. Label gold lokal tidak sepenuhnya independen dari proses pengembangan prototipe.
3. `MATCH` adalah hasil model, bukan kebenaran yang sudah diverifikasi manusia.
4. Pasangan `REVIEW` tetap memerlukan keputusan manusia.
5. Sebagian artefak lokal tidak tersedia pada clone bersih repository.
6. Format tanggal yang ambigu tidak boleh ditebak tanpa informasi urutan hari dan bulan.
7. Kinerja pada jutaan record belum diukur, sehingga tidak diklaim.
8. Sistem belum memiliki autentikasi, scheduler produksi, atau deployment produksi yang terverifikasi.

---

## 12. Daftar Pustaka

1. Fellegi, I. P., & Sun, A. B. (1969). A Theory for Record Linkage. *Journal of the American Statistical Association*, 64(328), 1183-1210.
2. Splink. *Splink: Probabilistic record linkage in Python and DuckDB*. https://www.splink.org/.
3. Splink. *Splink source repository*. https://github.com/moj-analytical-services/splink.
4. DuckDB. *DuckDB documentation*. https://duckdb.org/docs/.
5. Streamlit. *Streamlit documentation*. https://docs.streamlit.io/.
6. Dokumen internal proyek: `PRD.md`, `MASTER_CONTEXT.md`, `current_state.md`, `blocking_rules.md`, `data_flow.md`, dan `training_retraining.md`.

---

## Lampiran A. Istilah Singkat

| Istilah | Arti |
|---|---|
| CRM | Customer Relationship Management. |
| ER | Entity Resolution. |
| EM | Expectation-Maximization. |
| Gold label | Label yang sudah ditinjau manusia dan dipakai sebagai referensi evaluasi. |
| Silver label | Label otomatis dari sinyal identitas kuat, bukan kebenaran mutlak. |
| Standardisasi | Pembentukan kolom bersih baru tanpa mengubah nilai mentah. |
| Human-in-the-loop | Alur yang menyisipkan keputusan manusia untuk kasus yang tidak yakin. |

## Lampiran B. Data yang Perlu Disiapkan Sebelum Eksperimen

- File CSV customer pada `data/raw/`.
- `data/processed/crm_standardized.parquet` beserta metadata.
- `data/labels/gold_labels.csv`.
- Konfigurasi blocking dan model aktif.
- Artefak model yang akan dievaluasi.
- Lingkungan Python dengan dependensi pada `requirements.txt`.
