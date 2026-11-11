from __future__ import annotations

import argparse
import time
import warnings
from pathlib import Path

import pandas as pd
import splink
from splink import DuckDBAPI, Linker, SettingsCreator, block_on
import splink.comparison_library as cl
from splink.comparison_level_library import CustomLevel, ElseLevel

from . import model_lifecycle
from .config import (
    LAMBDA_RECALL_ASSUMPTION,
    M_ELSE_LEVEL_FLOOR,
    CONTACT_M_PROB,
    MATCH_THRESHOLD,
    PROCESSED_DATA_PATH,
    RANDOM_SEED,
    REVIEW_THRESHOLD,
    SMOKE_SAMPLE_SIZE,
    load_benchmark_rules,
    m_else_floor_for,
    predictions_path,
    scope_of,
    active_path,
    write_meta,
    atomic_write_json,
    atomic_write_parquet,
)


def build_name_comparison() -> cl.CustomComparison:
    both_null = (
        "(first_name_std_l IS NULL OR last_name_std_l IS NULL) "
        "AND (first_name_std_r IS NULL OR last_name_std_r IS NULL)"
    )
    exact = (
        "first_name_std_l IS NOT NULL AND first_name_std_r IS NOT NULL "
        "AND first_name_std_l = first_name_std_r "
        "AND last_name_std_l IS NOT NULL AND last_name_std_r IS NOT NULL "
        "AND last_name_std_l = last_name_std_r"
    )
    phonetic = (
        "phonetic_first_name_l IS NOT NULL AND phonetic_first_name_r IS NOT NULL "
        "AND phonetic_last_name_l IS NOT NULL AND phonetic_last_name_r IS NOT NULL "
        "AND phonetic_first_name_l = phonetic_first_name_r "
        "AND phonetic_last_name_l = phonetic_last_name_r"
    )
    # Fuzzy match untuk typo: jaro-winkler >= 0.85
    fuzzy = (
        "(first_name_std_l IS NOT NULL AND first_name_std_r IS NOT NULL "
        "AND last_name_std_l IS NOT NULL AND last_name_std_r IS NOT NULL "
        "AND jaro_winkler_similarity(first_name_std_l || ' ' || last_name_std_l, "
        "                             first_name_std_r || ' ' || last_name_std_r) >= 0.85)"
    )
    levels = [
        CustomLevel(both_null, label_for_charts="nama kosong").configure(
            is_null_level=True
        ),
        CustomLevel(exact, label_for_charts="ejaan persis").configure(
            m_probability=0.70
        ),
        CustomLevel(fuzzy, label_for_charts="fuzzy match (typo)").configure(
            m_probability=0.50
        ),
        CustomLevel(phonetic, label_for_charts="fonetik saja").configure(
            m_probability=0.30
        ),
        ElseLevel().configure(m_probability=0.10),
    ]
    return cl.CustomComparison(
        comparison_levels=levels, output_column_name="name"
    )


# Ambang "tahun lahir masih sama" untuk uji: selisih DOB > 366 hari = orang lain.
# ponytail: 366 hari, bukan perbandingan tahun kalender; ganti kalau aturan
# pemilik berubah jadi tahun-kalender penuh.
DOB_SAME_YEAR_DAYS = 366

DETERMINISTIC_RULES = [
    block_on("email_std"),
    block_on("phone_pre7"),  
]

BENCHMARK_RULES = load_benchmark_rules()

CORE_IDENTITY_FIELDS = (
    "first_name_std", "last_name_std", "address_std",
    "city_std", "state_std", "country_std",
    "email_std", "phone_std", "dob_std",
)

TRAINING_RULES = [
    (name, block_on(*cols))
    for name, cols in BENCHMARK_RULES
    if not (set(cols) & set(CORE_IDENTITY_FIELDS))
]


def load_data(full: bool = False) -> pd.DataFrame:
    df = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    if not full and len(df) > SMOKE_SAMPLE_SIZE:
        df = df.head(SMOKE_SAMPLE_SIZE).copy()
    return df


def pin_else_level(comparison, output_column_name: str, floor: float | None):
    if floor is None:
        return comparison
    levels = comparison.create_comparison_levels()
    last = levels[-1]
    if getattr(last, "m_probability", None) is None:
        return comparison
    levels[-1] = last.configure(m_probability=floor, fix_m_probability=True)
    return cl.CustomComparison(comparison_levels=levels, output_column_name=output_column_name)


def pin_comparison_level(comparison, output_column_name: str, level_index: int, floor: float):
    levels = comparison.create_comparison_levels()
    if 0 <= level_index < len(levels):
        levels[level_index].configure(m_probability=floor, fix_m_probability=True)
    return cl.CustomComparison(comparison_levels=levels, output_column_name=output_column_name)


def _normalize_fixed_m(comparisons):
    for i, comp in enumerate(comparisons):
        levels = comp.create_comparison_levels()
        total = sum((lv.m_probability or 0) for lv in levels)
        if total > 0 and total != 1:
            comparisons[i] = cl.CustomComparison(
                comparison_levels=[
                    lv.configure(
                        m_probability=(lv.m_probability or 0) / total,
                        fix_m_probability=True,
                    )
                    for lv in levels
                ],
                output_column_name=comp._output_column_name,
            )
    return comparisons


NAME_PHONETIC_COLUMNS = {
    "first_name_std": "phonetic_first_name",
    "last_name_std": "phonetic_last_name",
}


def _field_match_term(column: str) -> str:
    phonetic = NAME_PHONETIC_COLUMNS.get(column)
    if phonetic is None:
        return (
            f"({column}_l IS NOT NULL AND {column}_r IS NOT NULL "
            f"AND {column}_l = {column}_r)::INTEGER"
        )
    return (
        f"(({column}_l IS NOT NULL AND {column}_r IS NOT NULL) AND ("
        f"{column}_l = {column}_r OR ("
        f"{phonetic}_l IS NOT NULL AND {phonetic}_r IS NOT NULL "
        f"AND {phonetic}_l = {phonetic}_r)))::INTEGER"
    )


def build_contact_comparison() -> cl.CustomComparison:

    contact_null = (
        "(email_std_l IS NULL AND phone_std_l IS NULL) "
        "OR (email_std_r IS NULL AND phone_std_r IS NULL)"
    )
    both = (
        "email_std_l IS NOT NULL AND email_std_r IS NOT NULL AND email_std_l = email_std_r "
        "AND phone_std_l IS NOT NULL AND phone_std_r IS NOT NULL AND phone_std_l = phone_std_r"
    )
    one = (
        "(email_std_l IS NOT NULL AND email_std_r IS NOT NULL AND email_std_l = email_std_r) "
        "OR (phone_std_l IS NOT NULL AND phone_std_r IS NOT NULL AND phone_std_l = phone_std_r)"
    )
    phone_fuzzy = (
        "phone_std_l IS NOT NULL AND phone_std_r IS NOT NULL AND phone_std_l <> phone_std_r "
        "AND jaro_winkler_similarity(phone_std_l, phone_std_r) >= 0.90"
    )
    email_fuzzy = (
        "email_std_l IS NOT NULL AND email_std_r IS NOT NULL AND email_std_l <> email_std_r "
        "AND jaro_winkler_similarity(email_std_l, email_std_r) >= 0.85"
    )
    levels = [
        CustomLevel(contact_null, label_for_charts="kontak kosong").configure(
            is_null_level=True
        ),
        CustomLevel(both, label_for_charts="email dan telepon").configure(
            m_probability=0.70
        ),
        CustomLevel(one, label_for_charts="email atau telepon").configure(
            m_probability=CONTACT_M_PROB
        ),
        CustomLevel(email_fuzzy, label_for_charts="email mirip (typo)").configure(
            m_probability=0.45
        ),
        CustomLevel(phone_fuzzy, label_for_charts="telepon mirip (typo)").configure(
            m_probability=0.40
        ),
        ElseLevel().configure(m_probability=0.10),
    ]
    return cl.CustomComparison(
        comparison_levels=levels, output_column_name="contact"
    )


def build_location_comparison() -> cl.CustomComparison:

    location_null = (
        "(address_std_l IS NULL AND city_std_l IS NULL) "
        "OR (address_std_r IS NULL AND city_std_r IS NULL)"
    )
    full_match = (
        "address_std_l IS NOT NULL AND address_std_r IS NOT NULL AND address_std_l = address_std_r "
        "AND city_std_l IS NOT NULL AND city_std_r IS NOT NULL AND city_std_l = city_std_r "
        "AND state_std_l IS NOT NULL AND state_std_r IS NOT NULL AND state_std_l = state_std_r"
    )
    street_match = (
        "address_std_l IS NOT NULL AND address_std_r IS NOT NULL AND address_std_l = address_std_r"
    )
    city_match = (
        "city_std_l IS NOT NULL AND city_std_r IS NOT NULL AND city_std_l = city_std_r"
    )
    state_match = (
        "state_std_l IS NOT NULL AND state_std_r IS NOT NULL AND state_std_l = state_std_r"
    )
    three_of_four = (
        "(address_std_l IS NOT NULL AND address_std_r IS NOT NULL AND address_std_l = address_std_r "
        "AND city_std_l IS NOT NULL AND city_std_r IS NOT NULL AND city_std_l = city_std_r)"
        "OR (address_std_l IS NOT NULL AND address_std_r IS NOT NULL AND address_std_l = address_std_r "
        "AND state_std_l IS NOT NULL AND state_std_r IS NOT NULL AND state_std_l = state_std_r)"
        "OR (address_std_l IS NOT NULL AND address_std_r IS NOT NULL AND address_std_l = address_std_r "
        "AND state_std_l IS NOT NULL AND state_std_r IS NOT NULL AND state_std_l = state_std_r)"
    )
    levels = [
        CustomLevel(location_null, label_for_charts="lokasi kosong").configure(
            is_null_level=True
        ),
        CustomLevel(full_match, label_for_charts="alamat lengkap (4 field)").configure(
            m_probability=0.40
        ),
        CustomLevel(street_match, label_for_charts="street cocok").configure(
            m_probability=0.20
        ),
        CustomLevel(city_match, label_for_charts="city cocok").configure(
            m_probability=0.25
        ),
        CustomLevel(state_match, label_for_charts="state cocok").configure(
            m_probability=0.30
        ),
        CustomLevel(three_of_four, label_for_charts="3 dari 4 field cocok").configure(
            m_probability=0.15
        ),
        ElseLevel().configure(m_probability=0.10),
    ]
    return cl.CustomComparison(
        comparison_levels=levels, output_column_name="location"
    )


def build_dob_comparison() -> cl.CustomComparison:
    dob_null = "dob_std_l IS NULL OR dob_std_r IS NULL"
    match_exact = (
        "dob_std_l IS NOT NULL AND dob_std_r IS NOT NULL AND dob_std_l = dob_std_r"
    )
    match_fuzzy = (
        "dob_std_l IS NOT NULL AND dob_std_r IS NOT NULL "
        "AND (dob_std_l = dob_std_r OR "
        "dob_year_std_l IS NOT NULL AND dob_year_std_r IS NOT NULL "
        "AND ABS(CAST(dob_year_std_l AS INTEGER) - CAST(dob_year_std_r AS INTEGER)) <= 1)"
    )
    levels = [
        CustomLevel(dob_null, label_for_charts="dob kosong").configure(
            is_null_level=True
        ),
        CustomLevel(match_exact, label_for_charts="tanggal lahir persis").configure(
            m_probability=0.30
        ),
        CustomLevel(match_fuzzy, label_for_charts="tanggal lahir mendekat (year)").configure(
            m_probability=0.25
        ),
        ElseLevel().configure(m_probability=0.12),
    ]
    return cl.CustomComparison(
        comparison_levels=levels, output_column_name="dob"
    )


def three_match_level_index() -> int:
    return len(build_dob_comparison().comparison_levels) - 3 + 1


def build_settings():
    comparisons = [
        pin_else_level(build_name_comparison(), "name", m_else_floor_for("last_name_std")),
        pin_else_level(build_contact_comparison(), "contact", m_else_floor_for("email_std")),
        pin_else_level(build_location_comparison(), "location", m_else_floor_for("address_std")),
        pin_else_level(build_dob_comparison(), "dob", m_else_floor_for("dob_std")),
    ]
    prediction_blocks = [block_on(*cols) for _, cols in BENCHMARK_RULES]
    return SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name="record_id",
        comparisons=comparisons,
        blocking_rules_to_generate_predictions=prediction_blocks,
    )


def build_dynamic_settings_from_columns(selected_columns: list[str]) -> dict:
    
    # Validasi: pastikan semua kolom yang dipilih ada di daftar valid
    valid_columns = {
        "first_name_std", "last_name_std",
        "email_std", "phone_std",
        "address_std", "city_std", "state_std", "country_std",
        "dob_std", "dob_year_std"
    }
    
    invalid = [c for c in selected_columns if c not in valid_columns]
    if invalid:
        raise ValueError(
            f"Kolom berikut tidak valid untuk pencocokan Splink: {invalid}. "
            f"Silakan pilih dari: {sorted(valid_columns)}"
        )
    
    # Inisialisasi kosong
    comparisons = []
    blocking_rules = []
    
    # --- BUILD COMPARISONS berdasarkan kolom yang dipilih ---
    
    # 1. Name comparison: jika ada kolom first_name_std atau last_name_std
    has_name = any(c in selected_columns for c in ["first_name_std", "last_name_std"])
    if has_name:
        both_null = (
            "(first_name_std_l IS NULL OR last_name_std_l IS NULL) "
            "AND (first_name_std_r IS NULL OR last_name_std_r IS NULL)"
        )
        exact = (
            "first_name_std_l IS NOT NULL AND first_name_std_r IS NOT NULL "
            "AND first_name_std_l = first_name_std_r "
            "AND last_name_std_l IS NOT NULL AND last_name_std_r IS NOT NULL "
            "AND last_name_std_l = last_name_std_r"
        )
        # Fuzzy jaro-winkler untuk typo
        fuzzy = (
            "(first_name_std_l IS NOT NULL AND first_name_std_r IS NOT NULL "
            "AND last_name_std_l IS NOT NULL AND last_name_std_r IS NOT NULL "
            "AND jaro_winkler_similarity(first_name_std_l || ' ' || last_name_std_l, "
            "                             first_name_std_r || ' ' || last_name_std_r) >= 0.85)"
        )
        levels = [
            CustomLevel(both_null, label_for_charts="nama kosong").configure(is_null_level=True),
            CustomLevel(exact, label_for_charts="ejaan persis").configure(m_probability=0.70),
            CustomLevel(fuzzy, label_for_charts="fonetik/typos").configure(m_probability=0.35),
            ElseLevel().configure(m_probability=0.05),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels, output_column_name="name"))
    
    # 2a. Email comparison: jika ada email_std
    has_email = "email_std" in selected_columns
    if has_email:
        email_null = "(email_std_l IS NULL AND email_std_r IS NULL)"
        both_email = (
            "email_std_l IS NOT NULL AND email_std_r IS NOT NULL AND email_std_l = email_std_r"
        )
        email_fuzzy = (
            "email_std_l IS NOT NULL AND email_std_r IS NOT NULL AND email_std_l <> email_std_r "
            "AND jaro_winkler_similarity(email_std_l, email_std_r) >= 0.85"
        )
        email_localpart = (
            "email_std_l IS NOT NULL AND email_std_r IS NOT NULL "
            "AND email_std_l <> email_std_r "
            "AND substring(email_std_l, 1, instr(email_std_l, '@') - 1) "
            "= substring(email_std_r, 1, instr(email_std_r, '@') - 1)"
        )
        
        levels_email = [
            CustomLevel(email_null, label_for_charts="email kosong").configure(is_null_level=True),
            CustomLevel(both_email, label_for_charts="email persis").configure(m_probability=0.70),
            CustomLevel(email_fuzzy, label_for_charts="email mirip (JW >= 0.85)").configure(m_probability=0.45),
            CustomLevel(email_localpart, label_for_charts="local-part sama").configure(m_probability=0.30),
            ElseLevel().configure(m_probability=0.05),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels_email, output_column_name="email"))
    
    # 2b. Phone comparison: jika ada phone_std
    has_phone = "phone_std" in selected_columns
    if has_phone:
        phone_null = "(phone_std_l IS NULL AND phone_std_r IS NULL)"
        both_phone = (
            "phone_std_l IS NOT NULL AND phone_std_r IS NOT NULL AND phone_std_l = phone_std_r"
        )
        phone_fuzzy = (
            "phone_std_l IS NOT NULL AND phone_std_r IS NOT NULL AND phone_std_l <> phone_std_r "
            "AND jaro_winkler_similarity(CAST(phone_std_l AS VARCHAR), CAST(phone_std_r AS VARCHAR)) >= 0.90"
        )
        phone_pre7 = (
            "phone_std_l IS NOT NULL AND phone_std_r IS NOT NULL "
            "AND phone_std_l <> phone_std_r "
            "AND substring(CAST(phone_std_l AS VARCHAR), 1, 7) = substring(CAST(phone_std_r AS VARCHAR), 1, 7)"
        )
        
        levels_phone = [
            CustomLevel(phone_null, label_for_charts="telepon kosong").configure(is_null_level=True),
            CustomLevel(both_phone, label_for_charts="telepon persis").configure(m_probability=0.70),
            CustomLevel(phone_fuzzy, label_for_charts="telepon mirip (JW >= 0.90)").configure(m_probability=0.45),
            CustomLevel(phone_pre7, label_for_charts="7 digit awal sama").configure(m_probability=0.30),
            ElseLevel().configure(m_probability=0.05),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels_phone, output_column_name="phone"))
    
    # 3. Location/Address comparison: jika ada address_std atau city_std
    has_location = any(c in selected_columns for c in ["address_std", "city_std", "state_std", "country_std"])
    if has_location:
        location_null = (
            "(address_std_l IS NULL AND city_std_l IS NULL) "
            "OR (address_std_r IS NULL AND city_std_r IS NULL)"
        )
        full_match = (
            "address_std_l IS NOT NULL AND address_std_r IS NOT NULL AND address_std_l = address_std_r "
            "AND city_std_l IS NOT NULL AND city_std_r IS NOT NULL AND city_std_l = city_std_r "
            "AND state_std_l IS NOT NULL AND state_std_r IS NOT NULL AND state_std_l = state_std_r"
        )
        city_state = (
            "city_std_l IS NOT NULL AND city_std_r IS NOT NULL AND city_std_l = city_std_r "
            "AND state_std_l IS NOT NULL AND state_std_r IS NOT NULL AND state_std_l = state_std_r "
            "AND (address_std_l IS NULL OR address_std_r IS NULL OR address_std_l <> address_std_r)"
        )
        city_only = (
            "city_std_l IS NOT NULL AND city_std_r IS NOT NULL AND city_std_l = city_std_r "
            "AND (state_std_l IS NULL OR state_std_r IS NULL OR state_std_l <> state_std_r)"
        )
        
        levels = [
            CustomLevel(location_null, label_for_charts="lokasi kosong").configure(is_null_level=True),
            CustomLevel(full_match, label_for_charts="alamat + city + state cocok").configure(m_probability=0.60),
            CustomLevel(city_state, label_for_charts="city + state cocok").configure(m_probability=0.35),
            CustomLevel(city_only, label_for_charts="city cocok saja").configure(m_probability=0.20),
            ElseLevel().configure(m_probability=0.05),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels, output_column_name="location"))
    
    # 4. DOB comparison: jika ada dob_std atau dob_year_std
    has_dob = any(c in selected_columns for c in ["dob_std", "dob_year_std"])
    if has_dob:
        dob_null = "dob_std_l IS NULL OR dob_std_r IS NULL"
        match_exact = (
            "dob_std_l IS NOT NULL AND dob_std_r IS NOT NULL AND dob_std_l = dob_std_r"
        )
        dob_year_month = (
            "dob_std_l IS NOT NULL AND dob_std_r IS NOT NULL "
            "AND dob_std_l <> dob_std_r "
            "AND substr(dob_std_l, 1, 7) = substr(dob_std_r, 1, 7)"
        )
        dob_year_close = (
            "dob_std_l IS NOT NULL AND dob_std_r IS NOT NULL "
            "AND dob_year_std_l IS NOT NULL AND dob_year_std_r IS NOT NULL "
            "AND ABS(CAST(dob_year_std_l AS INTEGER) - CAST(dob_year_std_r AS INTEGER)) <= 1"
        )
        
        levels = [
            CustomLevel(dob_null, label_for_charts="dob kosong").configure(is_null_level=True),
            CustomLevel(match_exact, label_for_charts="tanggal lahir persis").configure(m_probability=0.70),
            CustomLevel(dob_year_month, label_for_charts="tahun + bulan sama").configure(m_probability=0.40),
            CustomLevel(dob_year_close, label_for_charts="tahun ±1").configure(m_probability=0.25),
            ElseLevel().configure(m_probability=0.05),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels, output_column_name="dob"))
    
    
    # Email blocking jika email_std dipilih
    if "email_std" in selected_columns:
        blocking_rules.append(block_on("email_std"))
    
    # Phone blocking jika phone_std dipilih
    if "phone_std" in selected_columns:
        blocking_rules.append(block_on("phone_std"))
    
    # City blocking jika city_std dipilih
    if "city_std" in selected_columns:
        blocking_rules.append(block_on("city_std"))
    
    # DOB blocking jika dob_std dipilih
    if "dob_std" in selected_columns:
        blocking_rules.append(block_on("dob_std"))

    # Blocking tambahan untuk kandidat ambigu; tidak menggantikan exact blocks.
    if "last_name_std" in selected_columns and "dob_year_std" in selected_columns:
        blocking_rules.append(block_on("last_name_std", "dob_year_std"))
    if "first_name_std" in selected_columns and "city_std" in selected_columns:
        blocking_rules.append(block_on("first_name_std", "city_std"))
    
    # Default blocking jika hanya name yang dipilih (pakai last_name_std)
    if not blocking_rules and has_name:
        blocking_rules.append(block_on("last_name_std"))
    
    # Default blocking jika hanya address yang dipilih (pakai city_std)
    if not blocking_rules and has_location:
        blocking_rules.append(block_on("city_std"))
    
    if not blocking_rules and has_dob:
        if "dob_year_std" in selected_columns:
            blocking_rules.append(block_on("dob_year_std"))
        elif "dob_std" in selected_columns:
            blocking_rules.append(block_on("dob_std"))
    
    # Fallback terakhir: gunakan last_name_std sebagai blocking (hampir pasti ada)
    if not blocking_rules:
        blocking_rules.append(block_on("last_name_std"))
    
    # Normalisasi m_probability agar jumlah per komparasi = 1
    comparisons = _normalize_fixed_m(comparisons)
    
    return {
        "comparisons": comparisons,
        "blocking_rules": blocking_rules,
    }


# Fungsi bantu: dapatkan daftar kolom standar yang ada di dataset yang diproses
def get_valid_comparison_columns() -> set:
    return {
        "first_name_std", "last_name_std",
        "email_std", "phone_std",
        "address_std", "city_std", "state_std", "country_std",
        "dob_std", "dob_year_std"
    }


# Fungsi bantu: ambil nama kolom dari dataframe yang sudah standardisasi
def infer_selected_columns_from_df(df: pd.DataFrame, preferred: list[str] | None = None) -> list[str]:
    
    valid = get_valid_comparison_columns()
    # Cari interseksi antara kolom di df dan valid columns
    available = [c for c in df.columns if c in valid]
    
    if preferred:
        # Filter preferred yang benar-benar ada
        filtered = [c for c in preferred if c in available]
        # Jika preferred tidak menghasilkan apa-apa (semua salah), gunakan yang ditemukan
        if filtered:
            return filtered
    
    return available[:10]  # Return maksimal 10 kolom pertama yang valid


# Fungsi bantu: rangkum decision dari prediksi dengan kolom yang dipilih
def add_decision_dynamic(pred_df: pd.DataFrame, match_threshold: float = 0.84, review_threshold: float = 0.35) -> pd.DataFrame:
    
    out = pred_df.copy()
    out["decision"] = "NON_MATCH"
    out.loc[out["match_probability"] >= match_threshold, "decision"] = "MATCH"
    out.loc[(out["match_probability"] >= review_threshold) & (out["match_probability"] < match_threshold), "decision"] = "REVIEW"
    return out


def add_decision(pred_df: pd.DataFrame) -> pd.DataFrame:
    return add_decision_dynamic(pred_df, MATCH_THRESHOLD, REVIEW_THRESHOLD)


BUSINESS_RULE_KEYS = ("email_std", "first_name_std", "last_name_std", "address_std")
ZERO_EVIDENCE_FIELDS = (
    "email_std", "first_name_std", "last_name_std",
    "address_std", "phone_std", "dob_std", "city_std",
)


def apply_business_rules(pred_df: pd.DataFrame, verbose: bool = False) -> pd.DataFrame:
    out = pred_df.copy()
    needed = [f"{c}_{s}" for c in BUSINESS_RULE_KEYS for s in ("l", "r")]
    missing = [c for c in needed if c not in out.columns]
    if missing:
        if verbose:
            print(f"Business rules skipped — columns absent: {missing}")
        out["business_rule"] = None
        return out

    email_diff = out["email_std_l"].ne(out["email_std_r"])
    first_name_diff = out["first_name_std_l"].ne(out["first_name_std_r"])
    last_name_diff = out["last_name_std_l"].ne(out["last_name_std_r"])
    force_non_by_email_fullname = email_diff & first_name_diff & last_name_diff

    keys_same = pd.Series(True, index=out.index)
    for col in BUSINESS_RULE_KEYS:
        left, right = out[f"{col}_l"], out[f"{col}_r"]
        keys_same &= left.notna() & right.notna() & left.eq(right)

    force_match = keys_same
    force_review = pd.Series(False, index=out.index)

    any_agree = pd.Series(False, index=out.index)
    for col in ZERO_EVIDENCE_FIELDS:
        left, right = out.get(f"{col}_l"), out.get(f"{col}_r")
        if left is None or right is None:
            continue
        any_agree |= left.notna() & right.notna() & left.eq(right)
    force_non = ~any_agree

    out["business_rule"] = None
    out.loc[force_match, "business_rule"] = "strong_agreement_email_name_address"
    out.loc[force_non & ~force_non_by_email_fullname, "business_rule"] = "no_field_agreement"
    out.loc[force_non_by_email_fullname, "business_rule"] = "conflicting_email_fullname"

    # match_probability dan threshold yang sudah dihitung model.
    if verbose:
        print(
            f"Business-rule evidence: strong={int(force_match.sum()):,}, "
            f"no_agreement={int(force_non.sum()):,}, "
            f"conflict_email_fullname={int(force_non_by_email_fullname.sum()):,}; "
            "decision tidak ditimpa"
        )
    # Jika nama+email+alamat sama persis tapi DOB beda/kosong, jadikan REVIEW
    # demi manusia bisa memeriksa kapanDOBnya tidak konsisten.
    dob_l = out.get("dob_std_l")
    dob_r = out.get("dob_std_r")
    if dob_l is not None and dob_r is not None:
        dob_both = dob_l.notna() & dob_r.notna() & (dob_l == dob_r)
        unverified = keys_same & ~dob_both
        already = out["business_rule"].isna()
        out.loc[unverified & already, "business_rule"] = "unverified_dob"
        out.loc[unverified & already, "decision"] = "REVIEW"
    return out


def _fuzzy_match_candidates(
    new_df: pd.DataFrame,
    existing_df: pd.DataFrame,
    columns: list[str],
    threshold: float = 80.0,
) -> pd.Series:
    from rapidfuzz import fuzz, process

    candidate_mask = pd.Series(False, index=existing_df.index)

    # Exact match untuk email dan phone (akurasi penting)
    exact_fields = ["email_std", "phone_std"]
    for col in exact_fields:
        if col in columns and col in new_df.columns and col in existing_df.columns:
            values = new_df[col].dropna().astype(str)
            values = values[values.str.len() > 0]
            if not values.empty:
                candidate_mask |= existing_df[col].astype(str).isin(values)

    # Fuzzy match untuk nama dan kota (ketemu duplikat beda email)
    fuzzy_fields = ["first_name_std", "last_name_std", "city_std"]
    for col in fuzzy_fields:
        if col in columns and col in new_df.columns and col in existing_df.columns:
            new_values = new_df[col].dropna().astype(str)
            new_values = new_values[new_values.str.len() > 1]
            existing_values = existing_df[col].dropna().astype(str)
            existing_unique = existing_values.unique().tolist()

            for _, nv in new_values.items():
                if pd.isna(nv) or len(str(nv)) < 2:
                    continue
                matches = process.extract(
                    str(nv), existing_unique,
                    scorer=fuzz.ratio,
                    score_cutoff=threshold,
                )
                if matches:
                    similar_values = [m[0] for m in matches]
                    candidate_mask |= existing_df[col].astype(str).isin(similar_values)

    return candidate_mask


def _candidate_rows_for_new_records(
    new_df: pd.DataFrame,
    existing_df: pd.DataFrame,
    selected_columns: list[str] | None = None,
    fuzzy_threshold: float = 80.0,
) -> pd.DataFrame:
    fields = selected_columns or [
        "email_std", "phone_std", "last_name_std", "first_name_std",
        "city_std", "dob_year_std",
    ]
    available = [c for c in fields if c in new_df.columns and c in existing_df.columns]
    if not available:
        raise ValueError("Tidak ada blocking column yang sama pada data baru dan existing")

    candidate_mask = _fuzzy_match_candidates(new_df, existing_df, available, fuzzy_threshold)

    candidates = existing_df.loc[candidate_mask]
    return pd.concat([new_df, candidates], ignore_index=True)


def predict_new_records(
    new_df: pd.DataFrame,
    existing_df: pd.DataFrame,
    model: dict,
    selected_columns: list[str] | None = None,
    verbose: bool = True,
) -> tuple[pd.DataFrame, object]:
    if "record_id" not in new_df or "record_id" not in existing_df:
        raise ValueError("new_df dan existing_df wajib memiliki record_id")
    new_ids = set(new_df["record_id"])
    candidates = _candidate_rows_for_new_records(new_df, existing_df, selected_columns)
    predictions, linker = train_and_predict(
        candidates, verbose=verbose, model=model, selected_columns=selected_columns
    )
    predictions = predictions[
        predictions["record_id_l"].isin(new_ids) | predictions["record_id_r"].isin(new_ids)
    ].copy()
    predictions["review_status"] = "pending"
    return predictions, linker


def _validate_fully_trained(linker) -> None:
    settings = linker._settings_obj.as_dict()
    missing = []
    for comparison in settings.get("comparisons", []):
        name = comparison.get("output_column_name", "unknown")
        for index, level in enumerate(comparison.get("comparison_levels", [])):
            if level.get("is_null_level") or level.get("sql_condition") == "ELSE":
                continue
            for parameter in ("m_probability", "u_probability"):
                if level.get(parameter) is None:
                    missing.append(f"{name}[{index}].{parameter}")
    if missing:
        raise RuntimeError(
            "Scoring dihentikan: model belum fully trained; parameter kosong: "
            + ", ".join(missing)
            + ". Kurangi level langka atau latih u_probability pada seluruh pasangan."
        )


def train_and_predict(
    df: pd.DataFrame,
    verbose: bool = True,
    model: dict | None = None,
    selected_columns: list[str] | None = None,
    max_pairs: int = 100_000,
    training_df: pd.DataFrame | None = None,
    full_u_estimation: bool = False,
) -> tuple[pd.DataFrame, object]:

    if model is not None:
        db_api = DuckDBAPI()
        sdf = db_api.register(df, table_name="input_data")
        linker = Linker(sdf, model)
        if verbose:
            print("Loaded saved model — skipping EM training (MC section 15).")
        preds = add_decision(linker.inference.predict().as_pandas_dataframe())
        return apply_business_rules(preds, verbose=verbose), linker

    # Batas DuckDB: mencegah konsumsi RAM >80% di laptop 16GB
    import duckdb
    duckdb.execute("SET memory_limit='6GB'")
    duckdb.execute("SET threads=4")

    db_api = DuckDBAPI()
    
    # Gunakan settings dinamis jika kolom dipilih, else built-in
    if selected_columns is not None:
        settings_dict = build_dynamic_settings_from_columns(selected_columns)
        comparisons = settings_dict["comparisons"]
        blocking_rules = settings_dict["blocking_rules"]
    else:
        comparisons = []
        blocking_rules = []
        # fallback ke build_settings jika tidak ada seleksi
        sdf = db_api.register(df, table_name="input_data")
        linker = Linker(sdf, build_settings())
        if verbose:
            print("Estimating model parameters with EM...")
        linker.training.estimate_probability_two_random_records_match(
            DETERMINISTIC_RULES, recall=LAMBDA_RECALL_ASSUMPTION
        )
        linker.training.estimate_u_using_random_sampling(max_pairs=max_pairs, seed=RANDOM_SEED)
        for name, rule in TRAINING_RULES:
            if verbose:
                print(f"EM on {name}")
            linker.training.estimate_parameters_using_expectation_maximisation(rule)
        pred_df = add_decision(linker.inference.predict().as_pandas_dataframe())
        return apply_business_rules(pred_df, verbose=verbose), linker
    
    # Latih parameter pada data training terpisah; scoring tetap pada kandidat df.
    train_frame = training_df if training_df is not None else df
    if full_u_estimation:
        total_pairs = len(train_frame) * (len(train_frame) - 1) // 2
        if total_pairs > 5_000_000:
            raise ValueError(
                "full_u_estimation ditolak: "
                f"{total_pairs:,} pasangan melebihi batas 5,000,000. "
                "Gunakan max_pairs 1,000,000-5,000,000."
            )
        max_pairs = total_pairs
    if "record_id" not in train_frame:
        raise ValueError("training_df wajib memiliki record_id")
    if training_df is not None and set(train_frame["record_id"]) & set(df["record_id"]):
        warnings.warn(
            "training_df dan df scoring memiliki record_id yang overlap. "
            "Ini dapat menyebabkan data leakage. Untuk eksperimen ini aman, "
            "untuk produksi gunakan data training yang disjoint.",
            stacklevel=2,
        )

    settings = SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name="record_id",
        comparisons=comparisons,
        blocking_rules_to_generate_predictions=blocking_rules,
    )
    train_sdf = db_api.register(train_frame, table_name="training_data")
    linker = Linker(train_sdf, settings)
    
    if verbose:
        print("Estimating model parameters with EM...")
    
    linker.training.estimate_probability_two_random_records_match(
        DETERMINISTIC_RULES, recall=LAMBDA_RECALL_ASSUMPTION
    )
    # Estimasi u memakai seluruh ruang pasangan jika muat; max_pairs membatasi RAM.
    total_pairs = len(train_frame) * (len(train_frame) - 1) // 2
    u_pairs = min(max_pairs, total_pairs)
    linker.training.estimate_u_using_random_sampling(max_pairs=u_pairs, seed=RANDOM_SEED)
    
    # EM training: pakai dynamic blocking_rules jika ada, else TRAINING_RULES global
    if blocking_rules:
        for i, rule in enumerate(blocking_rules):
            if verbose:
                print(f"EM on dynamic block {i}")
            linker.training.estimate_parameters_using_expectation_maximisation(rule)
    else:
        for name, rule in TRAINING_RULES:
            if verbose:
                print(f"EM on {name}")
            linker.training.estimate_parameters_using_expectation_maximisation(rule)
    
    _validate_fully_trained(linker)
    # Setelah training selesai, buat linker scoring terpisah untuk kandidat.
    settings_dict = linker._settings_obj.as_dict()
    score_sdf = db_api.register(df, table_name="scoring_data")
    scoring_linker = Linker(score_sdf, settings_dict)
    _validate_fully_trained(scoring_linker)
    pred_df = add_decision(scoring_linker.inference.predict().as_pandas_dataframe())
    return apply_business_rules(pred_df, verbose=verbose), scoring_linker


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Splink and score candidate pairs.")
    parser.add_argument(
        "--full",
        action="store_true",
        help=f"Train and predict on every row, not the {SMOKE_SAMPLE_SIZE} sample.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Explicitly run on the smoke sample. This is the default.",
    )
    parser.add_argument(
        "--reuse-model",
        metavar="PATH",
        default=None,
        help=(
            "Score using a saved model version instead of retraining (MASTER_CONTEXT "
            "section 15). Accepts a models/v... directory, a model.json path, or "
            "'latest' for the newest saved version."
        ),
    )
    parser.add_argument(
        "--columns",
        metavar="COL1,COL2,...",
        default=None,
        help=(
            "Comma-separated list of columns to use for dynamic matching. "
            "Valid: first_name_std, last_name_std, email_std, phone_std, "
            "address_std, city_std, state_std, country_std, dob_std, dob_year_std"
        ),
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=10_000,
        help="Max pairs for EM sampling (default: 10000). Use 1-5M for production.",
    )
    parser.add_argument(
        "--full-u-estimation",
        action="store_true",
        help="Estimate u_probability over all training pairs; may require substantial memory.",
    )
    parser.add_argument(
        "--new-data",
        metavar="PATH",
        help="Parquet berisi record baru; wajib bersama --existing-data dan --reuse-model.",
    )
    parser.add_argument(
        "--existing-data",
        metavar="PATH",
        help="Parquet existing standardized data untuk kandidat incremental.",
    )
    args = parser.parse_args()

    if bool(args.new_data) != bool(args.existing_data):
        raise SystemExit("--new-data dan --existing-data harus digunakan bersama")
    if args.new_data and not args.reuse_model:
        raise SystemExit("Mode incremental wajib memakai --reuse-model PATH atau latest")

    started = time.perf_counter()
    df = pd.read_parquet(args.existing_data) if args.existing_data else load_data(full=args.full)

    saved = None
    reused_from = None
    if args.reuse_model == "latest":
        latest = model_lifecycle.latest()
        if latest is None:
            raise SystemExit(
                "No saved model version found. Train one first, or drop --reuse-model."
            )
        saved = model_lifecycle.load_model_json(latest)
        reused_from = latest.name
        print(f"Reusing model version: {latest.name}")
    elif args.reuse_model:
        saved = model_lifecycle.load_model_json(args.reuse_model)
        given = Path(args.reuse_model)
        reused_from = given.name if given.is_dir() else given.parent.name

    selected_columns = (
        [c.strip() for c in args.columns.split(",")] if args.columns else None
    )
    if args.new_data:
        new_df = pd.read_parquet(args.new_data)
        pred_df, linker = predict_new_records(
            new_df,
            df,
            saved,
            selected_columns=selected_columns,
        )
    else:
        pred_df, linker = train_and_predict(
            df,
            model=saved,
            selected_columns=selected_columns,
            max_pairs=args.max_pairs,
            full_u_estimation=args.full_u_estimation,
        )
    out_path = predictions_path(full=args.full)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_parquet(pred_df, out_path)

    runtime = round(time.perf_counter() - started, 2)
    meta_extra = {
        "input_rows": len(df),
        "splink_version": splink.__version__,
        "training_rules": [name for name, _ in TRAINING_RULES],
        "trained": saved is None,
        "runtime_seconds": runtime,
    }

    version = None
    if saved is None:
        version = model_lifecycle.save_version(
            linker, pred_df, scope_of(args.full), runtime, meta_extra
        )
        meta_extra["model_version"] = version.name

    write_meta(
        out_path,
        artifact="splink_predictions",
        scope=scope_of(args.full),
        input_rows=len(df),
        pairs_scored=len(pred_df),
        blocking_rules=[name for name, _ in BENCHMARK_RULES],
        training_rules=[name for name, _ in TRAINING_RULES],
        lambda_recall_assumption=LAMBDA_RECALL_ASSUMPTION,
        m_else_level_floor=M_ELSE_LEVEL_FLOOR,
        match_threshold=MATCH_THRESHOLD,
        review_threshold=REVIEW_THRESHOLD,
        random_seed=RANDOM_SEED,
        splink_version=splink.__version__,
        model_version=version.name if version else reused_from,
        trained=saved is None,
        runtime_seconds=runtime,
    )

    print(f"Input rows: {len(df):,}")
    print(f"Pairs scored: {len(pred_df):,}")
    if version is not None:
        print(f"Model version saved: {version}")
    else:
        print("Reused a saved model — no new version written.")
    if "decision" in pred_df.columns:
        counts = pred_df["decision"].value_counts().to_dict()
        total = len(pred_df)
        print(f"Decisions: {counts}")
        print(
            f"  auto-match rate {counts.get('MATCH', 0) / total:.4%} | "
            f"review rate {counts.get('REVIEW', 0) / total:.4%} | "
            f"non-match rate {counts.get('NON_MATCH', 0) / total:.4%}"
        )
    print(f"Saved: {out_path}")
    
    # Export to CSV
    csv_path = out_path.with_suffix(".csv")
    cols = ["record_id_l", "record_id_r", "match_probability", "match_weight", "decision", "review_status"]
    cols = [c for c in cols if c in pred_df.columns]
    pred_df[cols].to_csv(csv_path, index=False)
    print(f"CSV: {csv_path}")
    
    print(pred_df[[c for c in ["record_id_l", "record_id_r", "match_probability", "match_weight", "decision"] if c in pred_df.columns]].head(20))


if __name__ == "__main__":
    main()