from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw" / "crm_50000_customers_dirty_v3.csv"
PROCESSED_DATA_PATH = PROJECT_ROOT / "data" / "processed" / "crm_standardized.parquet"
LABELS_DIR = PROJECT_ROOT / "data" / "labels"

OUTPUT_DIR = PROJECT_ROOT / "outputs"

# One definition per artifact. These used to be hardcoded in three modules, so a
# --full run left labels and threshold_eval reading the stale 10k sample file.
PREDICTIONS_SAMPLE_PATH = OUTPUT_DIR / "splink_predictions_sample.parquet"
PREDICTIONS_FULL_PATH = OUTPUT_DIR / "splink_predictions.parquet"
ENTITY_MAP_PATH = OUTPUT_DIR / "entity_map.parquet"
MASTER_PATH = OUTPUT_DIR / "master_customers.parquet"

SCOPE_SAMPLE = "sample"
SCOPE_FULL = "full"


def predictions_path(full: bool) -> Path:
    return PREDICTIONS_FULL_PATH if full else PREDICTIONS_SAMPLE_PATH


def scope_of(full: bool) -> str:
    return SCOPE_FULL if full else SCOPE_SAMPLE


def meta_path(artifact: Path) -> Path:
    return artifact.with_suffix(artifact.suffix + ".meta.json")


def read_meta(path: Path) -> dict:
    """Provenance sidecar for an artifact. Empty when absent, never invented."""
    meta_file = meta_path(path)
    if not meta_file.exists():
        return {}
    return json.loads(meta_file.read_text(encoding="utf-8"))


def write_meta(path: Path, **fields) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta_path(path).write_text(json.dumps(fields, indent=2, default=str), encoding="utf-8")

COLUMN_MAP = {
    "customer_id": "customer_id",
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
    "phone": "phone_number",
    "gender": "gender",
    "dob": "dob",
    "signup_date": "signup_date",
    "address": "address",
    "city": "city",
    "state": "state",
    "country": "country",
    "device_ids": "device_id(s)",
    "source": "source",
}

SOURCE_RECORD_ID_COLUMN = None

# Day/month order for ambiguous dates (both parts <= 12). None means "derive it
# from the rows where day > 12 or month > 12". A column with no such evidence is
# NOT guessed: standardize exits and asks, because dob_exact and city_dob depend
# on this answer. Measured on the current dataset: 30,279 rows have day > 12 and
# 0 have month > 12, so the file resolves to "dmy" on its own.
DATE_ORDER: str | None = None  # "dmy" | "mdy"

RANDOM_SEED = 42
SMOKE_SAMPLE_SIZE = 10000

# Starter blocking rules shared between benchmark and training.
# Equi-join keys only; fuzzy similarity belongs after candidate generation (DESIGN.md).
# Rules 1-6 are exact keys; 7-12 use lossy prefix keys (see standardize.add_blocking_keys)
# because exact blocking produced only 3,487 of 49,995,000 pairs on a 10k sample.
# Measured on that 10k sample. `email_local_pre3` on its own was rejected:
# 480,961 pairs with a 368-record block, because email_local_pre3 collides on
# common first-name prefixes. Adding last_name_std_pre3 cuts it to 2,796.
BENCHMARK_RULES: list[tuple[str, list[str]]] = [
    ("email_exact", ["email_std"]),
    ("phone_exact", ["phone_std"]),
    ("name_exact", ["first_name_std", "last_name_std"]),
    ("city_dob", ["city_std", "dob_std"]),
    ("dob_exact", ["dob_std"]),
    ("address_city", ["address_std", "city_std"]),
    ("phone_prefix", ["phone_pre7"]),
    ("name_prefix", ["last_name_std_pre3", "first_name_std_pre3"]),
    ("name_prefix_state", ["last_name_std_pre3", "state_std"]),
    ("email_local_name", ["email_local_pre3", "last_name_std_pre3"]),
    ("email_domain_name", ["email_domain_pre4", "last_name_std_pre3", "first_name_std_pre3"]),
    ("city_state_dob_year", ["city_std", "state_std", "dob_year_std"]),
]

# ASSUMPTION, not a measurement. The deterministic rules below are assumed to
# recover this fraction of true duplicate pairs; Splink divides by it to
# estimate probability_two_random_records_match. Replace with a value measured
# on the reviewed gold sample before trusting any match probability.
LAMBDA_RECALL_ASSUMPTION = 0.7

# P(m true match lands in a comparison's "all other" bucket) — pinned, not trained.
#
# WHY: on this dataset every duplicate group is identical on every field, so EM
# finds m ~= 0 for the "differs" level and Splink clamps it to 8.58e-300. log2 of
# that is -996.6, so all 292,016 non-matches scored EXACTLY -996.578428 (std
# 2.3e-13, one single value) and the review band could never contain anything.
# The model could not express "unsure" at all.
#
# MEASURED at 4k rows, sweeping this value, holding everything else fixed:
#   floor  weight values  weight range        pairs in review band  match edges
#   none          1       -996.6 (constant)                      0          13
#   0.01        505       -886.6 .. -31.7                       1          13
#   0.05        505       -493.7 .. -17.8                     121          13
#   0.20        504       -996.6 ..  -1.7                    1269          13
#
# 0.05 chosen: the band opens to a reviewable size while the match-edge count is
# unchanged. 0.20 floods the queue; 0.01 is too tight to be useful.
#
# ASSUMPTION, not a measurement from real dirty data: that ~5% of true matches
# differ completely on a given field. It cannot be measured here — this dataset
# contains no such pair, which is the whole reason this constant is needed.
M_ELSE_LEVEL_FLOOR: float | None = 0.05

# Measured on the 50k file: with the pinned m floor the score distribution is
# still bimodal on the match side — 1,867/1,867 device pairs score exactly p =
# 1.0, so every threshold in [0.5, 0.999] selects the same 1,867 edges. 0.9 is
# therefore safe HERE, but is NOT a general threshold; re-measure when data,
# comparisons, or the floor change.
MATCH_THRESHOLD = 0.9
# Below this a pair is rejected outright. Between it and MATCH_THRESHOLD a human
# checks. 1e-300 means "Splink collapsed this row to zero belief". REVIEW band
# content on 50k with the m floor pinned: 27,773 pairs in (1e-10, 0.9).
REVIEW_THRESHOLD = 1e-10

# Threshold can be applied from the retrain page (Threshold exploration). The
# applied values live in outputs/thresholds_override.json so every later run and
# subprocess picks them up without editing code; the defaults above stay as the
# documented fallback when no override exists.
_OVERRIDE = OUTPUT_DIR / "thresholds_override.json"
if _OVERRIDE.exists():
    try:
        _t = json.loads(_OVERRIDE.read_text(encoding="utf-8"))
        MATCH_THRESHOLD = float(_t.get("match_threshold", MATCH_THRESHOLD))
        REVIEW_THRESHOLD = float(_t.get("review_threshold", REVIEW_THRESHOLD))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass  # a broken override must not stop the pipeline; defaults stand
