# %% [markdown]
# # 01 — Profiling Data
# Jalankan berkas ini sebagai notebook Jupyter di VS Code.
# Perbarui `src/config.py` terlebih dahulu jika nama kolom CSV berbeda.

# %%
import pathlib
import sys

# Temukan folder utama proyek dari lokasi berkas ini agar tetap berfungsi dari
# direktori kerja mana pun. sys.path.append(os.path.abspath('..')) bergantung
# pada direktori kerja saat ini.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pandas as pd

from src.config import COLUMN_MAP, RAW_DATA_PATH
from src.profiling import build_profile, load_raw, validate_columns
from src.standardize import add_record_id

# %%
df_raw = load_raw(RAW_DATA_PATH)
print("Shape:", df_raw.shape)
print("Columns:")
print(df_raw.columns.tolist())

# %%
validation = validate_columns(df_raw)
if validation["missing_configured"]:
    print("CHANGE THESE IN src/config.py:")
    for logical, actual in validation["mapping"].items():
        if actual in validation["missing_configured"]:
            print(f"- {logical}: '{actual}' was not found")
else:
    print("All configured columns found.")

# %%
df = add_record_id(df_raw)
df.head(10)

# %%
profile_result = build_profile(df_raw)
column_profile = pd.DataFrame(profile_result["column_profile"])

missingness = column_profile.sort_values("null_pct", ascending=False)
missingness

# %%
unique_counts = column_profile[["column", "unique_count"]].sort_values("unique_count")
unique_counts

# %%
print("Exact duplicate rows:", profile_result["duplicate_rows"])
print("Customer ID report:", profile_result["duplicate_customer_id"])
print("First name anomalies:", profile_result["name_anomalies_first"])
print("Last name anomalies:", profile_result["name_anomalies_last"])
print("Phone anomalies:", profile_result["phone_anomalies"])

# %% [markdown]
# ## Periksa nilai mentah
# Ubah `cols_to_inspect` hanya jika pemetaan nama logis ke nama sumber berubah.

# %%
cols_to_inspect = [
    COLUMN_MAP.get("first_name"),
    COLUMN_MAP.get("last_name"),
    COLUMN_MAP.get("email"),
    COLUMN_MAP.get("phone"),
    COLUMN_MAP.get("address"),
    COLUMN_MAP.get("device_ids"),
]
cols_to_inspect = [c for c in cols_to_inspect if c in df.columns]

for c in cols_to_inspect:
    print(f"\n### {c}")
    print(df[c].dropna().astype(str).sample(min(20, df[c].notna().sum()), random_state=42).to_string(index=False))

# %% [markdown]
# Langkah berikutnya: buat standardisasi konservatif dan fitur pencocokan.
# Jangan latih Splink terlebih dahulu.
