# Panduan Pakai Sistem Pencarian Customer Ganda

Panduan ini untuk orang yang **baru pertama kali memakai** sistem ini.
Tidak perlu paham statistika atau pemrograman.

Kalau kamu mau penjelasan teknisnya, ada di `README.md`.

---

## 1. Sistem Ini Untuk Apa?

Database customer sering-berisi orang yang sama lebih dari satu kali. Contohnya:

| Data_customer | Alamat | Telepon |
| --- | --- | --- |
| Budi Santoso | Jl. Melati 5 | 08123456789 |
| Budi Santos | Jl. Melati No. 5 | +62 812-3456-789 |

Datanya berbeda sedikit, tapi orangnya sama. Kalau tidak digabung, pengiriman
pesan bisa dikirim dua kali, dan laporan penjualan jadi salah.

**Tugas sistem:** mencari pasangan data yang kemungkinan besar orang yang sama,
lalu menggabungkan yang sudah pasti, dan menyerahkan yang masih ragu ke manusia.

**Yang sistem ini tidak lakukan:** sistem tidak menebak. Kalau tidak yakin, dia
menyerahkannya ke Anda. Itu disengaja.

---

## 2. Cara Pakai dari Awal sampai Selesai

Ada 10 halaman. Kalau baru pertama kali, cukup ikuti urutan ini.

### Tahap 1 — Upload Data  (halaman Upload Data)

Unggah file CSV data customer.

Sistem akan otomatis:
- Cek kolomnya lengkap atau tidak
- Deteksi format tanggal (misal `25/12/1988` atau `1988-12-25`)
- Tampilkan ringkasan: berapa baris, berapa kolom, berapa data kosong

**Kalau muncul pertanyaan tanggal**, jawab yang benar. Kesalahan di sini membuat
sistem salah membandingkan tanggal lahir.

Kalau semuanya beres, klik **Analisis batch**. Prosesnya sekitar 1–2 menit untuk
50 ribu data.

### Tahap 2 — Lihat Hasil  (halaman Ringkasan)

Setelah selesai, buka **Ringkasan** untuk melihat:
- Berapa customer unik yang ditemukan
- Berapa yang digabung otomatis
- Berapa yang masih perlu diperiksa

Kalau jumlah "perlu diperiksa" sangat besar, jangan panik. Buka **Antrean
Pemeriksaan** untuk menambah them ke antrean kerja.

### Tahap 3 — Periksa Pasangan  (halaman Pemeriksaan)

**Ini halaman yang paling penting.** Di sinilah Anda memutuskan.

Ada dua cara:

**Cara 1 — satu per satu** (disarankan untuk pemeriksaan teliti)
1. Pilih pasangan di dropdown
2. Baca bagian **"Kenapa sistem berpikir begitu?"**
3. Periksa sendiri: apakah ini orang yang sama?
4. Klik **Orang yang sama** atau **Berbeda orang**

**Cara 2 — per banyak sekaligus** (lebih cepat)
1. Di tab **Daftar (massal)**, isi kolom **Keputusan Anda**
2. Klik **Simpan semua perubahan**

### Tahap 4 — Simpan ke Daftar Utama

Setelah memeriksa, scroll ke bawah halaman Pemeriksaan dan klik
**Simpan ke daftar utama**.

Ini menyimpan keputusan Anda. File ini dipakai untuk mengukur seberapa tepat
sistem bekerja.

### Tahap 5 — Perbaiki Hasil  (halaman Daftar Customer)

Sekarang Anda punya satu baris per customer. Halaman ini untuk merapikan:

- **Cari customer** — ketik nama atau email
- **Koreksi nilai** — kalau nama atau nomornya salah, ketik yang benar
- **Tandai salah gabung** — kalau sebenarnya ada 2 orang berbeda yang
  kelihatan jadi 1
- **Tandai salah pecah** — kalau 1 orang terpecah jadi 2 baris

---

## 3. Penjelasan Setiap Halaman

### 📤 Upload Data
Menambah data customer baru.

### 📊 Ringkasan
Kondisi hasil deduplikasi sekarang. Hanya untuk melihat, tidak ada tombol ubah.

### 🔎 Pemeriksaan
Menentukan pasangan mana yang orangnya sama. **Halaman kerja utama Anda.**

### 👥 Daftar Customer
Hasil akhir: satu baris per orang. Tempat membetulkan kekeliruan.

### 📋 Antrean Pemeriksaan
Daftar semua pasangan yang perlu diperiksa manusia. Antrean kerja hanya
mengambil sebagian kecil, halaman ini menampilkan semuanya.

### 📦 Data Batch Baru
Memeriksa data baru sebelum dipakai. Baris yang tidak Anda setujui tetap
masuk sebagai customer sendiri, tidak dihapus.

### 🕳️ Celah yang Terlewat
Dua hal yang tidak muncul di halaman lain:
- **Record sendirian** — record yang tidak pernah cocok dengan siapa pun
- **Perlu diperiksa, belum di antrean** — pasangan yang belum dilihat manusia

### 🔍 Kenapa Sistem Bilang Begitu?
Menjawab satu pasangan tertentu: kenapa sistem yakin atau tidak yakin.
Untuk belajar menilai sendiri.

### ⚙️ Pengaturan Sistem
Tempat mengubah batas kepastian dan melatih ulang model.
**Hanya untuk yang yakin. Semua perubahan di sini manual.**

### 📜 Riwayat Keputusan
Jejak audit: siapa mengubah apa, kapan.

---

## 4. Cara Membaca Angka Peluang

Setiap pasangan dapat angka **0% sampai 100%**. Ini artinya: "seberapa mungkin
kedua record ini orang yang sama".

| Angka | Arti | Yang terjadi |
| --- | --- | --- |
| **100%** | Hampir pasti sama | Digabung otomatis |
| **90% – 99%** | Kemungkinan besar sama | Digabung otomatis |
| **Di bawah 90%** | Tidak yakin | **Masuk antrean, menunggu Anda** |
| **Hampir 0%** | Pasti berbeda | Tidak digabung |

### Contoh

**Peluang 100%**
```
Budi Santoso | budi.santoso@mail.com | 08123456789
Budi Santoso | budi.santoso@mail.com | 08123456789
```
Semua sama → sistem yakin.

**Peluang sekitar 75%**
```
Budi Santoso  | budi@mail.com   | 08123456789
Budi Sihombing| budi@mail.com   | 08129998877
```
Nama berbeda, tapi email sama. Sistem tidak tahu ini orang sama atau saudara.
→ Anda yang memutuskan.

**Peluang 2%**
```
Budi Santoso  | budi@mail.com | 08123456789
Andi Susanto  | andi@mail.com | 08111122222
```
Tidak ada yang sama. Sistem yakin ini orang berbeda.

---

## 5. Cara Menilai Pasangan (Panduan Praktis)

Buka bagian **"Kenapa sistem berpikir begitu?"**. Di sana ada tabel yang
membandingkan tiap data satu per satu.

| Tanda | Artinya |
| --- | --- |
| **Sama persis** | Isi kedua record identik |
| **Mirip (92% mirip)** | Hampir sama, ada yang beda sedikit |
| **Sangat mirip, beda 1 karakter** | Kemungkinan salah ketik |
| **Beda** | Isinya tidak sama |
| **Hanya ada di salah satu** | Salah satu record tidak punya data ini |
| **Tidak ada data di field ini** | Dua-duanya kosong di field ini |

### Kapan harus bilang "Orang yang sama"

- Email sama persis
- Atau nama sama + tanggal lahir sama
- Namanya beda sedikit tapi semua data lain sama (kemungkinan salah ketik)
- Salah satu nama berbeda karena alasan yang masuk akal (ganti nama setelah menikah)

### Kapan harus bilang "Berbeda orang"

- Tanggal lahir berbeda → hampir pasti orang berbeda
- Email dan nomor telepon berbeda semua
- Nama sama, tapi kota, pekerjaan, dan tanggal lahir berbeda

### Kasus yang perlu hati-hati

| Situasi | Saran |
| --- | --- |
| Satu email dipakai keluarga | **Berbeda orang**, kecuali nama dan tanggal lahir sama |
| Nama sama persis, kota sama | Belum tentu — lihat tanggal lahir |
| Nomor telepon beda format (`0812...` vs `+62 812...`) | **Orang sama** |
| Salah satu field kosong | Jangan buru-buru menyimpulkan |

---

## 6. Pertanyaan yang Sering Muncul

**"Kenapa tidak semuanya digabung otomatis?"**
Karena lebih baik ada yang belum digabung daripada keliru digabung. Salah gabung
lebih merusak daripada lupa gabung.

**"Kenapa jumlahnya banyak sekali?"**
Semakin besar datanya, semakin banyak pasangan yang masih perlu diperiksa. Ini
wajar. Yang penting, bagian yang tersisa adalah yang memang perlu dilihat.

**"Bisa lihat hasilnya tanpa menunggu lama?"**
Bisa. Di halaman Ringkasan klik **Refresh**.

**"Data saya bisa hilang?"**
Tidak. Data asli tidak pernah diubah — sistem menyimpan dua versi (asli dan
yang sudah dibersihkan). Semua yang digabung masih bisa ditelusuri.

**"Kalau salah gabung, bagaimana?"**
Buka halaman **Daftar Customer**, tandai **Salah gabung**, lalu di halaman
**Pengaturan Sistem** lakukan latihan ulang. Tapi lebih baik dicek dari awal.

**"Model belajar sendiri dari keputusan saya?"**
Belum. Keputusan Anda dipakai untuk **mengukur** ketepatan sistem. Melatih ulang
harus dilakukan manual di halaman **Pengaturan Sistem**, supaya hasilnya bisa
diperiksa dulu.

---

## 7. Urutan Kerja yang Disarankan

```
1. Upload data              → cek ringkasannya
2. Lihat Ringkasan          → berapa yang perlu diperiksa?
3. Antrean Pemeriksaan      → masukkan yang perlu diperiksa ke antrean
4. Pemeriksaan              → periksa satu per satu (jangan buru-buru)
5. Simpan ke Daftar Utama   → simpan keputusan Anda
6. Daftar Customer          → betulkan yang keliru
7. Selesai                  → unduh daftar customer
```

---

## 8. Kalau Ada Masalah

| Gejala | Penyebab | Solusi |
| --- | --- | --- |
| Halaman kosong | Pipeline belum pernah dijalankan | Buka halaman Upload, unggah data |
| "Belum ada antrean" | Antrean habis / belum dibuat | Jalankan pipeline dulu, atau tambahkan dari Antrean |
| Angka peluang tidak muncul | Pasangan tidak pernah dibandingkan | Buka halaman Kenapa — biasanya memang tidak mirip |
| Halaman lambat | Data sangat besar | Tunggu proses selesai, jangan klik berulang |
| Perubahan tidak tersimpan | Tombol "Simpan" belum diklik | Klik tombol Simpan, lalu Refresh |

Kalau tetap bermasalah, cek **Riwayat Keputusan** untuk melihat apa yang
sudah dan belum dikerjakan.

---

## 9. Ringkasan Satu Halaman

```
APA INI?          Sistem mencari customer yang sama dalam data
 
ALUR KERJA:
  Upload → Ringkasan → Antrean → Pemeriksaan → Simpan → Daftar Customer

ATURAN EMAS:
  • Hampir pasti sama → sistem gabung sendiri
  • Tidak yakin       → menunggu Anda
  • Pasti berbeda     → dibuang

KALAU RAGU:
  Jangan tebak. Buka "Kenapa Sistem Bilang Begitu?" dan lihat sendiri.

YANG PENTING:
  Salah gabung jauh lebih berbahaya daripada lupa gabung.
  Kalau tidak yakin, biarkan jadi dua.
```
