from __future__ import annotations

import argparse
import time
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
    """Nama: ejaan persis (kuat) + fonetik + fuzzy typo + Else (lemah)."""
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
            m_probability=0.85
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


DETERMINISTIC_RULES = [
    block_on("email_std"),
    block_on("phone_pre7"),  # KEMBALIKAN ke original: phone_pre7 penting
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
                output_column_name=comp.output_column_name,
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
    """Kontak: email + telepon. Moderate m-prob: balance recall vs precision."""
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
    """Alamat: 4 field + komponen individual untuk coverage lebih baik."""
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
    """Tanggal lahir: persis sama OR mendekat (year)."""
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
    """
    Build Splink Settings based on user-selected columns for dynamic record linkage.
    
    Parameters
    ----------
    selected_columns : list[str]
        List of standard column names selected by the user for comparison, e.g., 
        ['first_name_std', 'email_std', 'dob_std'].
        Valid options: first_name_std, last_name_std, email_std, phone_std,
        address_std, city_std, state_std, country_std, dob_std, dob_year_std.
    
    Returns
    -------
    dict
        Dictionary containing Splink configuration with comparisons and blocking rules,
        ready to be passed to splink.SettingsCreator or Linker.
        
    Raises
    ------
    ValueError
        If any selected column is not in the valid set of standard columns.
    """
    
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
        # Fuzzy jaro-winkler default di sekitar 0.85
        fuzzy = (
            "(first_name_std_l IS NOT NULL AND first_name_std_r IS NOT NULL "
            "AND last_name_std_l IS NOT NULL AND last_name_std_r IS NOT NULL "
            "AND jaro_winkler_similarity(first_name_std_l || ' ' || last_name_std_l, "
            "                             first_name_std_r || ' ' || last_name_std_r) >= 0.85)"
        )
        phonetic = (
            "phonetic_first_name_l IS NOT NULL AND phonetic_first_name_r IS NOT NULL "
            "AND phonetic_last_name_l IS NOT NULL AND phonetic_last_name_r IS NOT NULL "
            "AND phonetic_first_name_l = phonetic_first_name_r "
            "AND phonetic_last_name_l = phonetic_last_name_r"
        )
        
        levels = [
            CustomLevel(both_null, label_for_charts="nama kosong").configure(is_null_level=True),
            CustomLevel(exact, label_for_charts="ejaan persis").configure(m_probability=0.85),
            CustomLevel(fuzzy, label_for_charts="fuzzy match (typo)").configure(m_probability=0.50),
            CustomLevel(phonetic, label_for_charts="fonetik saja").configure(m_probability=0.30),
            ElseLevel().configure(m_probability=0.10),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels, output_column_name="name"))
    
    # 2. Contact comparison (email + phone): jika ada email_std atau phone_std
    has_contact = any(c in selected_columns for c in ["email_std", "phone_std"])
    if has_contact:
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
        # Penentuan m-probability berdasarkan kombinasi yang dipilih
        if "email_std" in selected_columns and "phone_std" in selected_columns:
            m_both = 0.70  # both strong
        elif "email_std" in selected_columns:
            m_both = 0.60  # email only
        elif "phone_std" in selected_columns:
            m_both = 0.55  # phone only
        else:
            m_both = 0.50
            
        email_fuzzy = (
            "email_std_l IS NOT NULL AND email_std_r IS NOT NULL AND email_std_l <> email_std_r "
            "AND jaro_winkler_similarity(email_std_l, email_std_r) >= 0.85"
        )
        phone_fuzzy = (
            "phone_std_l IS NOT NULL AND phone_std_r IS NOT NULL AND phone_std_l <> phone_std_r "
            "AND jaro_winkler_similarity(phone_std_l, phone_std_r) >= 0.90"
        )
        
        levels = [
            CustomLevel(contact_null, label_for_charts="kontak kosong").configure(is_null_level=True),
            CustomLevel(both, label_for_charts="email dan telepon").configure(m_probability=m_both),
            CustomLevel(one, label_for_charts="email atau telepon").configure(m_probability=0.45),
            CustomLevel(email_fuzzy, label_for_charts="email mirip (typo)").configure(m_probability=0.45),
            CustomLevel(phone_fuzzy, label_for_charts="telepon mirip (typo)").configure(m_probability=0.40),
            ElseLevel().configure(m_probability=0.10),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels, output_column_name="contact"))
    
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
        city_match = (
            "city_std_l IS NOT NULL AND city_std_r IS NOT NULL AND city_std_l = city_std_r"
        )
        state_match = (
            "state_std_l IS NOT NULL AND state_std_r IS NOT NULL AND state_std_l = state_std_r"
        )
        
        levels = [
            CustomLevel(location_null, label_for_charts="lokasi kosong").configure(is_null_level=True),
            CustomLevel(full_match, label_for_charts="alamat + city + state cocok").configure(m_probability=0.40),
            CustomLevel(city_match, label_for_charts="city cocok").configure(m_probability=0.25),
            CustomLevel(state_match, label_for_charts="state cocok").configure(m_probability=0.30),
            ElseLevel().configure(m_probability=0.10),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels, output_column_name="location"))
    
    # 4. DOB comparison: jika ada dob_std atau dob_year_std
    has_dob = any(c in selected_columns for c in ["dob_std", "dob_year_std"])
    if has_dob:
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
            CustomLevel(dob_null, label_for_charts="dob kosong").configure(is_null_level=True),
            CustomLevel(match_exact, label_for_charts="tanggal lahir persis").configure(m_probability=0.30),
            CustomLevel(match_fuzzy, label_for_charts="tanggal lahir mendekat (year)").configure(m_probability=0.25),
            ElseLevel().configure(m_probability=0.12),
        ]
        comparisons.append(cl.CustomComparison(comparison_levels=levels, output_column_name="dob"))
    
    # --- BUILD BLOCKING RULES berdasarkan kolom yang dipilih ---
    
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
    
    # Default blocking jika hanya name yang dipilih (pakai last_name_std)
    if not blocking_rules and has_name:
        blocking_rules.append(block_on("last_name_std"))
    
    # Default blocking jika hanya address yang dipilih (pakai city_std)
    if not blocking_rules and has_location:
        blocking_rules.append(blockon("city_std"))
    
    return {
        "comparisons": comparisons,
        "blocking_rules": blocking_rules,
    }


# Fungsi bantu: dapatkan daftar kolom standar yang ada di dataset yang diproses
def get_valid_comparison_columns() -> set:
    """Mengembalikan set nama kolom standar (_std suffix) yang bisa digunakan untuk pencocokan."""
    return {
        "first_name_std", "last_name_std",
        "email_std", "phone_std",
        "address_std", "city_std", "state_std", "country_std",
        "dob_std", "dob_year_std"
    }


# Fungsi bantu: ambil nama kolom dari dataframe yang sudah standardisasi
def infer_selected_columns_from_df(df: pd.DataFrame, preferred: list[str] | None = None) -> list[str]:
    """
    Menganalisis dataframe dan mengembalikan daftar kolom standar yang tersedia.
    Fungsi ini membantu saat dataframe belum penuh atau kolom nama berbeda.
    
    Parameters
    ----------
    df : pd.DataFrame
        Dataframe yang sudah melalui proses standardisasi.
    preferred : list[str] | None, optional
        Daftar kolom yang diinginkan pengguna, dicek terhadap kolom yang ada di df.
        
    Returns
    -------
    list[str]
        Daftar kolom standar yang ditemukan dan valid.
    """
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
    """
    Menambahkan kolom decision (MATCH/REVIEW/NON_MATCH) berdasarkan match_probability.
    Fungsi ini adalah versi dinamis dari add_decision standar, memungkinkan threshold
    dikonfigurasi per-runtime.
    
    Parameters
    ----------
    pred_df : pd.DataFrame
        DataFrame hasil inferensi Splink yang harus memiliki kolom match_probability.
    match_threshold : float, optional
        Ambang bawah untuk kategori MATCH (default 0.84).
    review_threshold : float, optional
        Ambang bawah untuk kategori REVIEW (default 0.35).
        
    Returns
    -------
    pd.DataFrame
        DataFrame dengan kolom decision yang ditambahkan.
    """
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
    last_name_diff = out["last_name_std_l"].ne(out["last_name_std_r"])
    force_non_by_email_last = email_diff & last_name_diff

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

    force_non = force_non | force_non_by_email_last

    out["business_rule"] = None
    out.loc[force_match, "business_rule"] = "same_person_email_name_address"
    out.loc[force_non & ~force_non_by_email_last, "business_rule"] = "no_field_agrees"
    out.loc[force_non_by_email_last, "business_rule"] = "different_identity_email_lastname"
    out.loc[force_match, "decision"] = "MATCH"
    out.loc[force_review, "decision"] = "REVIEW"
    out.loc[force_non, "decision"] = "NON_MATCH"

    if verbose:
        print(
            f"Business rules: {int(force_match.sum()):,} dipaksa MATCH "
            f"(email + nama + alamat sama), "
            f"{int(force_non.sum()):,} dipaksa NON_MATCH "
            f"(nol field cocok + email/lastname berbeda)"
        )
    return out


def train_and_predict(
    df: pd.DataFrame,
    verbose: bool = True,
    model: dict | None = None,
) -> tuple[pd.DataFrame, object]:

    if model is not None:
        db_api = DuckDBAPI()
        sdf = db_api.register_table(df, table_name="dedup")
        linker = Linker(sdf, model)
        if verbose:
            print("Loaded saved model — skipping EM training (MC section 15).")
        preds = add_decision(linker.inference.predict().as_pandas_dataframe())
        return apply_business_rules(preds, verbose=verbose), linker

    db_api = DuckDBAPI()
    # register_table returns a DuckDBDataFrame; Linker needs pandas
    linker = Linker(df, build_settings(), db_api=db_api)

    if verbose:
        print("Estimating model parameters with EM...")

    linker.training.estimate_probability_two_random_records_match(
        DETERMINISTIC_RULES, recall=LAMBDA_RECALL_ASSUMPTION
    )
    linker.training.estimate_u_using_random_sampling(max_pairs=100_000_000, seed=RANDOM_SEED)

    for name, rule in TRAINING_RULES:
        if verbose:
            print(f"EM on {name}")
        linker.training.estimate_parameters_using_expectation_maximisation(rule)

    pred_df = add_decision(linker.inference.predict().as_pandas_dataframe())
    return apply_business_rules(pred_df, verbose=verbose), linker


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
    args = parser.parse_args()

    started = time.perf_counter()
    df = load_data(full=args.full)

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

    pred_df, linker = train_and_predict(df, model=saved)
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
    print(pred_df[[c for c in ["record_id_l", "record_id_r", "match_probability", "match_weight", "decision"] if c in pred_df.columns]].head(20))


if __name__ == "__main__":
    main()