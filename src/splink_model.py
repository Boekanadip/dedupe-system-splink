from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import splink
from splink import DuckDBAPI, Linker, SettingsCreator, block_on
import splink.comparison_library as cl

from . import model_lifecycle
from .config import (
    LAMBDA_RECALL_ASSUMPTION,
    MATCH_THRESHOLD,
    M_ELSE_LEVEL_FLOOR,
    PROCESSED_DATA_PATH,
    RANDOM_SEED,
    REVIEW_THRESHOLD,
    SMOKE_SAMPLE_SIZE,
    load_benchmark_rules,
    m_else_floor_for,
    predictions_path,
    scope_of,
    write_meta,
    atomic_write_parquet,
    atomic_write_json,
)

DETERMINISTIC_RULES = [
    block_on("email_std"),
    block_on("phone_std"),
]

BENCHMARK_RULES = load_benchmark_rules()
TRAINING_RULES = [(name, block_on(*cols)) for name, cols in BENCHMARK_RULES]


def load_data(full: bool = False) -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DATA_PATH)
    if not full and len(df) > SMOKE_SAMPLE_SIZE:
        df = df.head(SMOKE_SAMPLE_SIZE).copy()
    return df


def pin_else_level(comparison, output_column_name: str, floor: float):
    """Bangun ulang pembanding dengan nilai m tingkat "all other" ditetapkan ke `floor`.

    Tanpa ini, tingkat tersebut dilatih hingga ~0 lalu dibatasi oleh Splink,
    sehingga semua pasangan bukan-kecocokan mendapat skor identik. Pembanding
    dibangun ulang melalui CustomComparison karena perubahan pada objek hasil
    `create_comparison_levels()` tidak berpengaruh; objek itu dibangun ulang
    setiap kali dipanggil.

    Kini `floor` ditetapkan per kolom (M_ELSE_LEVEL_FLOOR_BY_FIELD): batas rendah
    pada dob dan phone memberi bobot besar pada ketidakcocokannya, sehingga lima
    kolom yang cocok tidak menutupi dua kolom yang berbeda.
    """
    levels = comparison.create_comparison_levels()
    levels[-1].configure(m_probability=floor, fix_m_probability=True)
    return cl.CustomComparison(comparison_levels=levels, output_column_name=output_column_name)


def build_settings():
    # (pembuat, kolom keluaran, penyesuaian frekuensi istilah?)
    # Penyesuaian TF dipindahkan KE first_name / last_name / email pada
    # 2026-10-12. Sebelumnya hanya diterapkan pada city / state / country, padahal
    # nama depan umum ("randy") atau domain email gratis ("gmail.com") merupakan
    # bukti lemah yang perlu dikurangi bobotnya. Sebaliknya, kecocokan kota yang
    # persis di antara kota-kota Indonesia sudah kuat dengan sendirinya.
    #
    # gender dan signup_date ditambahkan lalu DIHAPUS pada hari yang sama.
    # Pengukuran pada set 101 ribu baris menunjukkan keduanya tidak mengubah
    # salah gabung (4.867 -> 4.867) atau jumlah entity campuran (2.603 -> 2.603).
    # Dua pembanding tambahan yang memperlama pelatihan tanpa manfaat dihapus,
    # bukan disimpan "untuk nanti".
    specs = [
        (cl.NameComparison("first_name_std"), "gamma_first_name_std", True),
        (cl.NameComparison("last_name_std"), "gamma_last_name_std", True),
        (cl.EmailComparison("email_std"), "gamma_email_std", True),
        (
            cl.JaroWinklerAtThresholds("address_std", [0.95, 0.90, 0.80]),
            "gamma_address_std",
            False,
        ),
        (cl.ExactMatch("city_std"), "gamma_city_std", True),
        (cl.ExactMatch("state_std"), "gamma_state_std", True),
        (cl.ExactMatch("country_std"), "gamma_country_std", True),
        (
            cl.DateOfBirthComparison("dob_std", input_is_string=True),
            "gamma_dob_std",
            False,
        ),
        (cl.ExactMatch("phone_std"), "gamma_phone_std", False),
    ]

    comparisons = []
    for creator, output_column, term_frequency in specs:
        # Batas per kolom menggunakan nama kolom SUMBER, bukan nama gamma:
        # prefiks gamma tidak akan cocok dengan kunci
        # M_ELSE_LEVEL_FLOOR_BY_FIELD.
        source_col = output_column.removeprefix("gamma_")
        floor = m_else_floor_for(source_col)
        if floor is None:
            comparison = creator
        else:
            comparison = pin_else_level(creator, output_column, floor)
        # Penyesuaian TF harus diterapkan ulang setelah pembangun ulang, jadi
        # cabang ini ditulis sekali untuk kedua jalur, bukan digandakan.
        if term_frequency:
            comparison = comparison.configure(term_frequency_adjustments=True)
        comparisons.append(comparison)

    if M_ELSE_LEVEL_FLOOR is not None:
        print(
            f"Pinned 'all other' m on {len(comparisons)} comparisons "
            f"(default {M_ELSE_LEVEL_FLOOR}, per-field overrides applied)"
        )

    # Blocking prediksi menggunakan gabungan aturan yang telah di-benchmark.
    # Tanpa pengukuran, pemilihan aturan dapat membuat sistem memberi skor pada
    # pasangan yang biayanya belum diketahui.
    prediction_blocks = [block_on(*cols) for _, cols in BENCHMARK_RULES]

    return SettingsCreator(
        link_type="dedupe_only",
        unique_id_column_name="record_id",
        comparisons=comparisons,
        blocking_rules_to_generate_predictions=prediction_blocks,
    )


def add_decision(pred_df: pd.DataFrame) -> pd.DataFrame:
    """Kebijakan tiga arah (PRD §7). Satu kolom sebagai sumber keputusan.

    MATCH berada di atas ambang hasil evaluasi, REVIEW di antaranya, dan
    NON_MATCH di bawahnya. Tahap clustering hanya memakai MATCH, sehingga semua
    pasangan dalam rentang REVIEW harus diperiksa manusia dan sengaja TIDAK
    digabungkan.
    """
    out = pred_df.copy()
    out["decision"] = "NON_MATCH"
    out.loc[out["match_probability"] >= REVIEW_THRESHOLD, "decision"] = "REVIEW"
    out.loc[out["match_probability"] >= MATCH_THRESHOLD, "decision"] = "MATCH"
    return out


# Kolom yang menjadi prasyarat aturan bisnis, dan satu kolom pemisah.
BUSINESS_RULE_KEYS = ("email_std", "first_name_std", "last_name_std", "address_std")
BUSINESS_RULE_DISCRIMINATOR = "dob_std"

# Ambang selisih tanggal lahir yang dianggap "satu tahun" (masih orang yang
# sama). TERUKUR lewat 153 keputusan peninjau: semua pasangan yang dilabeli
# "match" punya selisih dob <= 368 hari (median TEPAT 365 hari — pola tahun
# salah ketik, bulan dan hari tetap sama). 138 dari 143 jatuh di <= 366 hari.
# > 366 = selisih TEBUS lebih dari satu tahun, terlalu besar untuk langsung
# digabung.
DOB_SAME_YEAR_DAYS = 366

# Kolom yang dihitung sebagai "ada yang cocok" untuk aturan nol-bukti.
# TERVALIDASI pada gold: dari 5 pasangan yang TIDAK ADA satu pun field cocok,
# kelima-limanya dilabeli manusia sebagai "beda orang", nol sebagai "orang
# sama". Pada 1 field cocok pun 1.630 vs 5 condong ke beda, tapi 5 kasus
# "orang sama" di sana membuat aturan 1-field tidak aman — jadi hanya 0-field
# yang dipaksa.
ZERO_EVIDENCE_FIELDS = (
    "email_std", "first_name_std", "last_name_std",
    "address_std", "phone_std", "dob_std", "city_std",
)


def apply_business_rules(pred_df: pd.DataFrame, verbose: bool = False) -> pd.DataFrame:
    """Aturan bisnis domain, tiga arah, semuanya menimpa keputusan model.

    ATURAN 1 — email + nama depan + nama belakang + alamat identik berarti
    orang yang sama, asalkan tanggal lahirnya juga sama.

    Splink adalah naive Bayes dan overconfident: pasangan dengan email+nama+
    alamat identik tetap mendapat p = 1.0 walaupun dob berbeda, karena bobot
    email yang sama persis (log2(m/u) ~ +18,7) menenggelamkan penalti dob.
    TERUKUR pada 101k: 153 pasangan dengan dob berbeda ikut tergabung.

      email+nama+alamat sama + dob sama     -> paksa MATCH
      email+nama+alamat sama + dob BEDA
          atau KOSONG di satu sisi           -> paksa REVIEW
          DOB bisa saja salah ketik, jadi menolak otomatis sama
          berbahayanya dengan menggabung salah. Biayanya timpang — salah
          gabung merusak data selamanya, salah tolak hanya menunda.

    ATURAN 2 — tidak ada satu pun field identitas yang cocok = bukan orang yang
    sama.

    TERVALIDASI pada gold: dari 5 pasangan yang TIDAK ADA satu pun field cocok
    (email, nama, alamat, telepon, dob, kota), kelima-limanya dilabeli manusia
    sebagai "beda orang" — nol yang salah. Pola di gold juga tegas: 0-1 field
    cocok condong ke "beda orang" (1.635 vs 5), 2+ field condong ke "orang
    sama" (592 vs 4). Hanya 0-field yang dipaksa, karena di 1-field masih ada
    5 kasus "orang sama" yang akan hilang.

    Pasangan yang TIDAK memenuhi ketiga kunci persis (mis. alamat beda typo)
    dibiarkan pada keputusan model — aturan ini sengaja sempit supaya tidak
    menarik orang yang benar-benar berbeda hanya karena satu field mirip.
    """
    out = pred_df.copy()
    needed = [f"{c}_{s}" for c in (*BUSINESS_RULE_KEYS, BUSINESS_RULE_DISCRIMINATOR)
              for s in ("l", "r")]
    missing = [c for c in needed if c not in out.columns]
    if missing:
        # Kolom tidak ada (model lama / konfigurasi berbeda). Jangan menebak:
        # lewati aturan dan katakan, supaya hasil tidak diam-diam berubah.
        if verbose:
            print(f"Business rules skipped — columns absent: {missing}")
        out["business_rule"] = None
        return out

    keys_same = pd.Series(True, index=out.index)
    for col in BUSINESS_RULE_KEYS:
        left, right = out[f"{col}_l"], out[f"{col}_r"]
        keys_same &= left.notna() & right.notna() & left.eq(right)

    # Aturan 1: dob SAMA atau beda <= 1 tahun (366 hari) dianggap satu orang.
    # Aturan ini berdasar pengukuran, bukan asumsi: peninjau melabeli 153
    # pasangan email+nama+alamat identik sebagai "match", dan median selisih
    # dob-nya TEPAT 365 hari. Beda hingga 1 tahun = salah ketik tahun, bukan
    # orang kedua.
    dob_left, dob_right = out[f"{BUSINESS_RULE_DISCRIMINATOR}_l"], out[f"{BUSINESS_RULE_DISCRIMINATOR}_r"]
    dob_both = dob_left.notna() & dob_right.notna()
    dob_same = dob_both & dob_left.eq(dob_right)

    dob_within_year = pd.Series(False, index=out.index)
    if dob_both.any():
        try:
            d1 = pd.to_datetime(dob_left[dob_both], errors="coerce")
            d2 = pd.to_datetime(dob_right[dob_both], errors="coerce")
            within = (d1 - d2).dt.days.abs() <= DOB_SAME_YEAR_DAYS
            dob_within_year.loc[dob_both] = within.fillna(False).to_numpy()
        except (ValueError, TypeError):
            # Tanggal tidak bisa diparse — anggap tidak bisa diverifikasi.
            dob_within_year = pd.Series(False, index=out.index)

    # dob beda > 1 tahun ATAU kosong di satu sisi -> tidak bisa diverifikasi
    # sebagai satu orang -> REVIEW.
    dob_unverified = keys_same & ~dob_same & ~dob_within_year

    force_match = keys_same & (dob_same | dob_within_year)
    force_review = dob_unverified

    # ATURAN 2: nol field identitas yang cocok. Perhitungannya dari kolom yang
    # benar-benar ada, supaya aturan ini ikut bekerja meski satu field hilang.
    any_agree = pd.Series(False, index=out.index)
    for col in ZERO_EVIDENCE_FIELDS:
        left, right = out.get(f"{col}_l"), out.get(f"{col}_r")
        if left is None or right is None:
            continue
        any_agree |= left.notna() & right.notna() & left.eq(right)
    force_non = ~any_agree

    out["business_rule"] = None
    out.loc[force_match, "business_rule"] = "same_person_email_name_address"
    out.loc[force_review, "business_rule"] = "unverified_dob"
    out.loc[force_non, "business_rule"] = "no_field_agrees"
    out.loc[force_match, "decision"] = "MATCH"
    # REVIEW, bukan NON_MATCH: tanpa dob yang bisa dibandingkan kita tidak
    # punya bukti untuk menolak, dan menolak otomatis tidak bisa dibatalkan.
    out.loc[force_review, "decision"] = "REVIEW"
    out.loc[force_non, "decision"] = "NON_MATCH"

    if verbose:
        print(
            f"Business rules: {int(force_match.sum()):,} dipaksa MATCH (dob sama), "
            f"{int(force_review.sum()):,} dipaksa REVIEW (dob beda/kosong), "
            f"{int(force_non.sum()):,} dipaksa NON_MATCH (nol field cocok)"
        )
    return out


def train_and_predict(
    df: pd.DataFrame,
    verbose: bool = True,
    model: dict | None = None,
) -> tuple[pd.DataFrame, object]:
    """Beri skor pada semua pasangan kandidat tolok ukur; latih dahulu jika model tidak diberikan.

    Kembalikan (predictions, linker) agar pemanggil dapat menyimpan model yang
    baru dilatih tanpa menjalankan pelatihan untuk kedua kalinya.

    `model` adalah dict model Splink tersimpan. Jika diberikan, seluruh
    pelatihan EM dilewati (MASTER_CONTEXT bagian 15: model tidak dilatih ulang
    setiap kali CSV baru diterima). Linker yang dikembalikan tidak memiliki
    parameter hasil pelatihan sendiri, sehingga save_model_to_json akan menulis
    model yang belum dilatih. Pemanggil hanya boleh menyimpan linker dari proses
    pelatihan.

    Fungsi ini dipisahkan agar src/stress_test.py memberi skor pada data rusak
    dengan konfigurasi model yang sama persis. Jalur pelatihan kedua yang ditulis
    manual dapat diam-diam berbeda dari jalur produksi dan melaporkan tingkat
    pemulihan untuk pipeline yang sebenarnya tidak digunakan.
    """
    if model is not None:
        linker = Linker(df, model, db_api=DuckDBAPI())
        if verbose:
            print("Loaded saved model — skipping EM training (MC section 15).")
        preds = add_decision(linker.inference.predict().as_pandas_dataframe())
        return apply_business_rules(preds, verbose=verbose), linker

    linker = Linker(df, build_settings(), db_api=DuckDBAPI())

    # CATATAN: fungsi EM Splink 4.0.17 tidak memiliki argumen max_pairs; ukuran
    # sampel pelatihan ditentukan oleh aturan blocking pelatihan.
    # Splink sendiri menyarankan max_pairs=1e8 agar sampel u tidak terlalu kecil.
    # Pada sampel 10 ribu baris, batas ini mencakup seluruh data sehingga
    # probabilitas u dihitung secara persis.
    if verbose:
        print("Estimating model parameters with EM...")
    # Nilai bawaan 1e-4 terlalu rendah untuk data ini: semua pasangan bukan-
    # kecocokan menyusut ke probabilitas 1e-300. Perkirakan nilai ini dari aturan
    # deterministik. Pembagi recall merupakan asumsi; lihat LAMBDA_RECALL_ASSUMPTION.
    linker.training.estimate_probability_two_random_records_match(
        DETERMINISTIC_RULES, recall=LAMBDA_RECALL_ASSUMPTION
    )
    linker.training.estimate_u_using_random_sampling(max_pairs=100_000_000, seed=RANDOM_SEED)

    # EM tidak memperkirakan pembanding yang digunakan oleh aturan blockingnya
    # sendiri, sehingga satu aturan saja membuat nilai m pembanding tersebut
    # tidak terlatih. Jalankan setiap aturan yang telah di-benchmark agar semua
    # pembanding dilatih menggunakan aturan lainnya.
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
        # Proses penggunaan ulang tetap harus mencatat model MANA yang memberi
        # skor. model_version kosong membuat evaluate/dashboard menampilkan "n/a"
        # untuk artefak pembentuk entity_map saat ini.
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

    # Setiap pelatihan mendapat direktori versi yang tidak dapat diubah
    # (bagian 16 MASTER_CONTEXT). Proses penggunaan ulang tidak menghasilkan
    # apa pun yang perlu disimpan: menyimpan linker yang tidak dilatih akan
    # menimpa catatan asal-usul dengan model tanpa parameter.
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
