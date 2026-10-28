
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.standardize import normalize_name, normalize_person_name, soundex
from src.splink_model import NAME_PHONETIC_COLUMNS, build_core_identity_comparison


def code(name):
    return soundex(normalize_person_name(name))

variants = ["mamat", "maamat", "mmamat", "mmt", "mamt", "mmat"]
codes = {v: code(v) for v in variants}
assert len(set(codes.values())) == 1, codes
assert next(iter(codes.values())) == "M530", codes
assert normalize_person_name("3ka") == "eka", normalize_person_name("3ka")
assert code("eka") == code("3ka")
assert code("eka") != code("aka")
assert code("mamat") != code("dimas")

assert normalize_name("jl. merdeka no. 3").endswith("3")

assert NAME_PHONETIC_COLUMNS == {
    "first_name_std": "phonetic_first_name",
    "last_name_std": "phonetic_last_name",
}

sql = build_core_identity_comparison().create_comparison_levels()[1].sql_condition
assert "phonetic_first_name_l = phonetic_first_name_r" in sql, sql
assert "phonetic_last_name_l = phonetic_last_name_r" in sql, sql
assert "phonetic_dob" not in sql, sql

print(f"OK soundex={codes} | eka/3ka identik | alamat aman | SQL komposit benar")
