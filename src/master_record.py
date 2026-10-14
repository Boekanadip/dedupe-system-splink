from __future__ import annotations

import re
import time

import pandas as pd

from .config import (
    ENTITY_MAP_PATH,
    MASTER_PATH,
    MATCH_THRESHOLD,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    SCOPE_FULL,
    read_meta,
    write_meta,
    atomic_write_parquet,
    atomic_write_json,
    active_path,
    atomic_write_csv,
)

MASTER_SUMMARY_PATH = OUTPUT_DIR / "master_summary.csv"

# device_ids_std berisi daftar pada setiap baris, sehingga tidak dapat dipilih
# sebagai nilai tunggal. Kolom ini tetap ada di parquet terstandardisasi untuk audit.
MASTER_FIELDS = [
    "first_name_std",
    "last_name_std",
    "email_std",
    "phone_std",
    "dob_std",
    "address_std",
    "city_std",
    "state_std",
    "country_std",
]
LINEAGE_FIELDS = ["record_id", "customer_id", "source"]


# Kolom yang angka-nya adalah ISI sah, bukan kerusakan. Tanggal, telepon, dan
# nomor rumah memang berisi angka; menghukum angka di sana selalu memilih nilai
# yang salah. Diukur pada data ini: dob_std "1988-04-11" mencetak skor 18 hanya
# karena delapan angkanya, sehingga kalah telak dari nilai lain yang sama sahnya.
DIGIT_EXPECTED = frozenset({"dob", "phone", "signup_date", "email", "address"})

# Kolom yang simbol-nya adalah ISI sah: tanda "-" pada tanggal dan "@"/"." pada
# email. Simbol lain tetap dihukum — normalize_text sudah membuang simbol dari
# nama/kota/alamat, jadi yang tersisa memang mencurigakan.
SYMBOL_EXPECTED = frozenset({"dob", "email", "phone"})


def corruption_score(value: str, field: str = "") -> int:
    """Skor keanehan sebuah nilai terstandardisasi. Makin kecil makin dipilih.

    Dipakai HANYA sebagai pemecah seri setelah jumlah kemunculan (`n`), jadi
    nilai yang paling sering muncul di dalam entity tetap menang tanpa syarat.

    DUA PERUBAHAN dari versi lama, keduanya berdasar temuan terukur:

    1. PENALTI HURUF BERULANG DIHAPUS. Verifikasi menunjukkan "Muhammad" (benar)
       mencetak 2 sedangkan "Muhamed" (salah ketik) mencetak 1, sehingga justru
       salah ketik yang dipilih. Profiling juga menemukan 10.666 catatan dengan
       karakter berulang bersebelahan — pola itu umum dan sah pada nama asli
       ("Muhammad", "Lee", "Stafford"), jadi menghukumnya merugikan lebih banyak
       daripada menolong.

    2. PENALTI ANGKA SEKARANG PER-KOLOM. Versi lama menghukum angka di semua
       kolom, padahal tanggal lahir, telepon, dan nomor rumah memang berisi
       angka. Itu membuat tanggal lahir nyaris mustahil dipilih sebagai nilai
       master.

    Sisa metriknya tetap: angka di nama/kota = ganjil, simbol di nama/kota = ganjil.
    """
    if field.startswith("master_"):
        field = field[len("master_"):]
    field = field.removesuffix("_std")

    text = str(value)
    digits = len(re.findall(r"\d", text))
    symbols = len(re.findall(r"[^a-z\s'’-]", text))
    score = 0
    if field not in DIGIT_EXPECTED:
        score += digits
    if field not in SYMBOL_EXPECTED:
        score += symbols
    return score


def pick_master_values(frame: pd.DataFrame) -> pd.DataFrame:
    """Pilih nilai terstandardisasi terkuat dan paling sedikit rusak per entity dan kolom.

    Urutan: pilih nilai yang paling banyak disepakati, lalu yang paling sedikit
    rusak, kemudian urutkan secara alfabetis. Setiap tahap deterministik,
    sehingga masukan yang sama selalu menghasilkan catatan master yang sama.
    """
    long = frame.melt(
        id_vars=["entity_id"],
        value_vars=MASTER_FIELDS,
        var_name="field",
        value_name="value",
    ).dropna(subset=["value"])

    counts = long.groupby(["entity_id", "field", "value"]).size().reset_index(name="n")
    # corruption dinilai per-kolom: angka sah pada tanggal/telepon tapi ganjil
    # pada nama. Tanpa field-nya, tanggal lahir selalu kalah dari nilai lain.
    counts["corruption"] = counts.apply(
        lambda r: corruption_score(r["value"], r["field"]), axis=1
    )
    # Urutkan berdasarkan jumlah terbanyak, kerusakan paling sedikit, lalu nilai.
    counts = counts.sort_values(
        ["entity_id", "field", "n", "corruption", "value"],
        ascending=[True, True, False, True, True],
    )
    best = counts.drop_duplicates(["entity_id", "field"])[["entity_id", "field", "value"]]

    wide = best.pivot(index="entity_id", columns="field", values="value").reset_index()
    wide.columns = ["entity_id", *[f"master_{c}" for c in wide.columns[1:]]]
    return wide


def build_lineage(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = frame.groupby("entity_id")
    # Batch saat ini memiliki 1.281 nilai source kosong (diukur 2026-10-01), dan
    # satu entity dapat mencampur nilai kosong dengan nilai nyata — sorted()
    # pada {None, 'referral'} memunculkan TypeError. Nilai kosong dibuang dari
    # daftar; entity tanpa source menghasilkan [], bukan [None].
    return pd.DataFrame(
        {
            "record_count": grouped["record_id"].nunique(),
            "record_ids": grouped["record_id"].apply(lambda s: sorted(s.tolist())),
            "customer_ids": grouped["customer_id"].apply(
                lambda s: sorted(set(s.dropna().tolist()))
            ),
            "sources": grouped["source"].apply(
                lambda s: sorted(set(s.dropna().tolist()))
            ),
        }
    ).reset_index()


def main() -> None:
    started = time.perf_counter()

    if not active_path(PROCESSED_DATA_PATH).exists():
        raise FileNotFoundError("Run python -m src.standardize first.")
    if not active_path(ENTITY_MAP_PATH).exists():
        raise FileNotFoundError("Run python -m src.clustering --full first.")

    records = pd.read_parquet(active_path(PROCESSED_DATA_PATH))
    entity_map = pd.read_parquet(active_path(ENTITY_MAP_PATH))
    frame = records.merge(entity_map[["record_id", "entity_id"]], on="record_id", how="inner")

    if len(frame) != len(records):
        raise ValueError(
            f"entity_map covers {len(frame):,} of {len(records):,} records; rebuild clustering"
        )

    # Pengelompokan cakupan sampel juga mencakup semua record_id, sehingga
    # pemeriksaan panjang di atas tidak dapat mendeteksinya. Ini titik terakhir
    # untuk mencegah cakupan yang keliru menghasilkan berkas master pelanggan salah.
    meta = read_meta(ENTITY_MAP_PATH)
    if meta and meta.get("scope") != SCOPE_FULL:
        raise SystemExit(
            f"{ENTITY_MAP_PATH.name} was built with scope={meta.get('scope')} "
            f"({meta.get('unscored_records', '?')} records never scored).\n"
            "  Building master records from it would emit those as distinct customers.\n"
            f"  Run: python -m src.clustering --full"
        )

    missing = [c for c in MASTER_FIELDS + LINEAGE_FIELDS if c not in frame.columns]
    if missing:
        raise ValueError(f"standardized data is missing columns: {missing}")

    master = build_lineage(frame).merge(pick_master_values(frame), on="entity_id", how="left")

    # Asal-usul: kolom yang berbeda di dalam entity agar peninjau dapat melihat
    # nilai master mana yang ditentukan melalui pertimbangan.
    conflicts = (
        frame.melt(
            id_vars=["entity_id"],
            value_vars=MASTER_FIELDS,
            var_name="field",
            value_name="value",
        )
        .dropna(subset=["value"])
        .groupby(["entity_id", "field"])["value"]
        .nunique()
        .rename("distinct_values")
        .reset_index()
    )
    conflicted = (
        conflicts[conflicts["distinct_values"] > 1]
        .groupby("entity_id")["field"]
        .apply(lambda s: sorted(s.tolist()))
        .rename("conflicted_fields")
        .reset_index()
    )
    master = master.merge(conflicted, on="entity_id", how="left")
    master["conflicted_fields"] = master["conflicted_fields"].apply(
        lambda v: v if isinstance(v, list) else []
    )

    atomic_write_parquet(master, MASTER_PATH)
    write_meta(
        MASTER_PATH,
        artifact="master_customers",
        scope=SCOPE_FULL,
        entities=len(master),
        records=int(master["record_count"].sum()),
        source_entity_map_scope=meta.get("scope"),
        match_threshold=MATCH_THRESHOLD,
    )

    summary = pd.DataFrame(
        [
            {
                "entities": len(master),
                "records": int(master["record_count"].sum()),
                "multi_record_entities": int((master["record_count"] > 1).sum()),
                "largest_entity": int(master["record_count"].max()),
                "entities_with_conflicts": int((master["conflicted_fields"].apply(len) > 0).sum()),
                "mean_customer_ids_per_entity": round(
                    master["customer_ids"].apply(len).mean(), 4
                ),
                "runtime_seconds": round(time.perf_counter() - started, 2),
            }
        ]
    )
    atomic_write_csv(summary, MASTER_SUMMARY_PATH)

    print(summary.to_string(index=False))
    print(f"Saved: {MASTER_PATH}")
    print(f"Saved: {MASTER_SUMMARY_PATH}")


if __name__ == "__main__":
    main()
