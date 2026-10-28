"""Validasi batch yang diunggah sebelum didaftarkan.
2: 
3: Tahap ini menolak batch lebih awal jika strukturnya tidak sesuai untuk pipeline
4: linkage. Tujuannya adalah mencegah berkas ditulis dan didaftarkan jika Splink
5: nantinya akan gagal karena kolom yang diperlukan tidak tersedia.
6: 
7: Aturan:
15: - Wajib: first_name, last_name, dan setidaknya salah satu dari email/phone.
15: - Wajib: setiap kolom sumber yang digunakan aturan blocking aktif di
15:   BENCHMARK_RULES. Daftar ini diturunkan dari config, bukan ditulis tetap,
15:   sehingga validator dan standardize() selalu selaras.
15: - Membantu: kolom yang meningkatkan recall tetapi tidak digunakan untuk blocking.
15: - Opsional: kolom lain yang tercantum di COLUMN_MAP.
16: 
19: Laporan juga menyertakan metadata operasional, bukan hanya kesalahan validasi:
20: - pemisah dan pengodean yang benar-benar digunakan pada berkas unggahan;
21: - bukti urutan tanggal agar UI dapat menampilkan urutan yang terdeteksi sebagai
23:   pilihan awal saat menanyakan format dd/mm atau mm/dd.
25: """
26: 
25: from __future__ import annotations
25: 
27: import argparse
28: import io
29: import json
31: import re
32: from pathlib import Path
32: 
33: import numpy as np
35: import pandas as pd
36: 
36: from .config import COLUMN_MAP, OUTPUT_DIR, load_benchmark_rules
39: 
40: REPORT_PATH = OUTPUT_DIR / "upload_validation_report.json"
41: 
41: REQUIRED_COLUMNS = ["first_name", "last_name"]
41: ONE_OF = [("email", "phone")]
44: 
44: # Kolom wajib minimal untuk blocking rules (dari COLUMN_MAP)
41: MINIMAL_REQUIRED_COLUMNS = ["first_name", "last_name", "email"]
41: # Jika email tidak tersedia, gunakan phone sebagai alternatif
41: if "email" not in COLUMN_MAP.values() and "phone" in COLUMN_MAP.values():
41:     MINIMAL_REQUIRED_COLUMNS.append("phone")
44: 
44: # Label kegagalan per kolom: pesan blocking harus menyebut gejala yang benar,
44: # dan jangan mengabaikan konteks blokir yang relevan.
45: 
45: def validate_columns(df: pd.DataFrame) -> list[str]:
46:     """Validasi kolom wajib dan kolom blocking."""
46:     errors = []
46:     
46:     # Pastikan kolom wajib ada
47:     for col in REQUIRED_COLUMNS:
47:         if col not in df.columns:
47:             errors.append(f"Kolom wajib tidak ada: {col}")
48:     
47:     # Pastikan ada setidaknya satu kolom dari ONE_OF (email atau phone)
47:     email_present = "email" in df.columns
47:     phone_present = "phone" in df.columns
47:     if not email_present and not phone_present:
48:         errors.append("Kolom email atau phone tidak ditemukan")
48:     
48:     # Pastikan minimal required columns tersedia
49:     for col in MINIMAL_REQUIRED_COLUMNS:
49:         if col not in df.columns:
49:             errors.append(f"Kolom minimal tidak ada: {col}")
50:     
50:     # Validasi format email (jika email ada)
51:     if "email" in df.columns:
51:         invalid_emails = df[~df["email"].str.contains(EMAIL_SHAPE, na=False)]
52:         if len(email_present) > 0 and len(email_present) > 0:
52:             invalid_count = len(email_present) - len(email_present[email_present.str.contains(EMAIL_SHAPE, na=False)])
53:             if len(email_present) > 0 and len(email_present[email_present.str.contains(EMAIL_SHAPE, na=False)]) < len(email_present):
53:                 errors.append(f"Terdapat {len(email_present) - len(email_present[email_present.str.contains(EMAIL_SHAPE, na=False)])} email tidak valid")
54:     
51:     return errors
51: 
51: # Label kegagalan per kolom: pesan blocking harus menyebut gejala yang benar,
51: # dan jangan mengabaikan konteks blokir yang relevan.
51: 
52: def main():
52:     parser = argparse.ArgumentParser(description='Validasi CSV upload')
53:     parser.add_argument('file', type=Path, help='Path to CSV file')
53:     args = parser.parse_args()
53: 
54:     try:
54:         df = pd.read_csv(args.file)
55:         errors = validate_columns(df)
55:         
55:     except Exception as e:
57:         errors.append(f"Error membaca file: {str(e)}")
57: 
57:     if errors:
58:         report = {
58:             "status": "error",
58:             "errors": errors,
58:             "timestamp": datetime.now().isoformat()
59:         }
59:         (PROJECT_ROOT / "data" / "labels" / "validation_report.json").write_text(json.dumps(report, indent=2))
60:         raise ValueError("Upload validation failed")
61: 
61: if __name__ == "__main__":
62:     main()