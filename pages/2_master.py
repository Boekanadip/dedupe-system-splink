"""Master record review page (PRD FR-09, output side).

The master record is the system's final output: one row per entity, with the
best value per field. This page lets a person browse entities, see which fields
conflict, inspect the member records, and correct master values.

Corrections are written straight to master_customers.parquet and appended to an
audit file (who, when, field, old -> new). Membership changes are NOT done here:
a wrong merge/split is feedback for retraining, not a manual edit.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import LABELS_DIR, MASTER_PATH, PROCESSED_DATA_PATH, PROJECT_ROOT
from src.ui import (
    format_count,
    monitoring_sidebar,
    page_guide,
    page_header,
)

st.set_page_config(page_title="Master - Entity Resolution", page_icon="👥", layout="wide")
page_header(
    "Daftar Customer",
    "Hasil akhir: satu baris per orang. Kalau ada datanya yang berbeda-beda, "
    "kolomnya ditandai agar bisa dibetulkan.",
)
monitoring_sidebar()
page_guide(__file__)

if not MASTER_PATH.exists() or not PROCESSED_DATA_PATH.exists():
    st.info(
        "Belum ada master record. Jalankan pipeline dari halaman Upload dulu "
        "(clustering + master_record)."
    )
    st.stop()

AUDIT_PATH = LABELS_DIR / "master_corrections.csv"
MASTER_FIELDS = [
    "master_first_name_std", "master_last_name_std", "master_email_std",
    "master_phone_std", "master_dob_std", "master_address_std",
    "master_city_std", "master_state_std", "master_country_std",
]

MASTER_LABELS = {
    "master_first_name_std": "Nama depan",
    "master_last_name_std": "Nama belakang",
    "master_email_std": "Email",
    "master_phone_std": "Nomor telepon",
    "master_dob_std": "Tanggal lahir",
    "master_address_std": "Alamat",
    "master_city_std": "Kota",
    "master_state_std": "Provinsi",
    "master_country_std": "Negara",
}

master = pd.read_parquet(MASTER_PATH)
records = pd.read_parquet(PROCESSED_DATA_PATH)

# ---- cari entity
st.subheader("Cari entity")
query = st.text_input("Cari customer_id / email / entity_id", placeholder="misal: rec_000123 atau john@x.com")
if query:
    q = query.strip().lower()
    hits = master[
        master["customer_ids"].apply(lambda x: q in str(x).lower())
        | master["master_email_std"].astype(str).str.lower().str.contains(q, na=False)
        | master["entity_id"].astype(str).str.lower().str.contains(q, na=False)
    ].sort_values("record_count", ascending=False)
else:
    # 500 teratas; 48k opsi tidak terbaca manusia di selectbox.
    hits = master.sort_values("record_count", ascending=False).head(500)
st.caption(f"{len(hits):,} customer cocok · urut dari yang record-nya terbanyak")
if hits.empty:
    st.stop()

entity_id = st.selectbox("Pilih entity", hits["entity_id"].tolist())
entity = master[master["entity_id"] == entity_id].iloc[0]

# ---- indikator laporan keanggotaan (salah gabung / salah pecah)
FLAGS_PATH = LABELS_DIR / "membership_flags.csv"
open_flags = pd.DataFrame()
if FLAGS_PATH.exists():
    try:
        _flags = pd.read_csv(FLAGS_PATH)
        _flags["status"] = _flags["status"].fillna("open").astype(str)
        open_flags = _flags[(_flags["entity_id"] == entity_id) & (_flags["status"] == "open")]
    except Exception:
        open_flags = pd.DataFrame()

# ---- detail entity
st.subheader(f"Customer {entity_id}")
if not open_flags.empty:
    issues = {
        "wrong_merge": "salah gabung (2 orang jadi 1)",
        "wrong_split": "salah pecah (1 orang jadi 2)",
    }
    for _, row in open_flags.iterrows():
        st.warning(
            f"Laporan: **{issues.get(str(row['issue']), row['issue'])}** — "
            f"status `{row.get('status', 'open')}`, oleh {row.get('reviewer', '—')} "
            f"pada {row.get('timestamp', '—')}."
        )
c1, c2, c3 = st.columns(3)
c1.metric("Jumlah record", format_count(entity["record_count"]))
c2.metric("Customer ID berbeda", format_count(len(entity["customer_ids"])))
c3.metric("Field konflik", format_count(len(entity["conflicted_fields"])))
if len(entity["conflicted_fields"]):
    st.warning(f"Field konflik (record anggota beda): {', '.join(entity['conflicted_fields'])}")

# Lineage = bukti asal-usul (PRD FR-11): record mana yang membentuk entity ini,
# nama apa yang dipakai source system, dari kanal mana. Disembunyikan di expander
# supaya tidak membingungkan, tetap ada untuk audit.
with st.expander("Lineage (audit) — asal-usul entity ini"):
    st.caption("Kode record pembentuk · Kode customer di source · Sumber data yang dipakai")
    st.write({
        "kode record": list(entity["record_ids"]),
        "kode customer": list(entity["customer_ids"]),
        "sumber data": list(entity["sources"]),
    })

# ---- koreksi nilai master
st.subheader("Nilai master (bisa dikoreksi)")
st.caption("Perbaiki nilai yang salah di sini. Sistem memakai nilai pertama sebagai default.")
with st.form("correct_master"):
    cols = st.columns(3)
    new_values = {}
    for i, field in enumerate(MASTER_FIELDS):
        current = entity[field] if field in entity else ""
        new_values[field] = cols[i % 3].text_input(
            MASTER_LABELS.get(field, field),
            value="" if pd.isna(current) else str(current),
        )
    reviewer = st.text_input("Reviewer (nama/kode)", value="reviewer")
    submitted = st.form_submit_button("Simpan koreksi", type="primary")

if submitted:
    changes = {
        f: (entity[f] if f in entity else None, v)
        for f, v in new_values.items()
        if v != ("" if pd.isna(entity.get(f)) else str(entity.get(f)))
    }
    if not changes:
        st.info("Tidak ada perubahan.")
    else:
        # Update master_customers.parquet
        mask = master["entity_id"] == entity_id
        for f, (_, v) in changes.items():
            master.loc[mask, f] = v
        master.to_parquet(MASTER_PATH, index=False)
        # Audit trail
        LABELS_DIR.mkdir(parents=True, exist_ok=True)
        audit = pd.DataFrame(
            [
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "entity_id": entity_id,
                    "field": f,
                    "old_value": old,
                    "new_value": new,
                    "reviewer": reviewer,
                }
                for f, (old, new) in changes.items()
            ]
        )
        if AUDIT_PATH.exists():
            audit = pd.concat([pd.read_csv(AUDIT_PATH), audit], ignore_index=True)
        audit.to_csv(AUDIT_PATH, index=False)
        st.success(f"Disimpan {len(changes)} koreksi. Audit: {AUDIT_PATH.name}")
        st.rerun()

# ---- record anggota
st.subheader("Record anggota")
member_ids = entity["record_ids"]
members = records[records["record_id"].isin(member_ids)]
st.caption(f"{len(members):,} record penyusun entity ini:")
st.dataframe(
    members[["record_id", "customer_id", "first_name_std", "last_name_std",
             "email_std", "phone_std", "dob_std", "city_std", "source"]],
    width="stretch",
    height=300,
    column_config={
        "record_id": st.column_config.TextColumn("Kode record"),
        "customer_id": st.column_config.TextColumn("Kode dari sistem asal"),
        "first_name_std": st.column_config.TextColumn("Nama depan"),
        "last_name_std": st.column_config.TextColumn("Nama belakang"),
        "email_std": st.column_config.TextColumn("Email"),
        "phone_std": st.column_config.TextColumn("Telepon"),
        "dob_std": st.column_config.TextColumn("Tanggal lahir"),
        "city_std": st.column_config.TextColumn("Kota"),
        "source": st.column_config.TextColumn("Sumber data"),
    },
)


# ---- tandai salah gabung / salah pecah
# def dulu, baru tombol: Streamlit mengeksekusi script atas-ke-bawah, jadi
# _flag harus sudah terdefinisi pada saat tombol dievaluasi.
FLAGS_PATH = LABELS_DIR / "membership_flags.csv"


def _flag(entity_id: str, kind: str, reviewer: str) -> None:
    """Catat laporan keanggotaan ke file terpisah.

    feedback.csv sengaja TIDAK dipakai: skemanya per-pasangan dengan label
    match/no_match, dan menyisipkan 'wrong_merge' di sana merusak validasi
    feedback dan menumpuk duplikat. File terpisah punya status sendiri
    (open -> resolved) supaya triage bisa dilakukan di halaman retrain.
    """
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame(
        [
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "entity_id": entity_id,
                "issue": kind,
                "reviewer": reviewer or "reviewer",
                "note": "",
                "status": "open",
            }
        ]
    )
    if FLAGS_PATH.exists():
        existing = pd.read_csv(FLAGS_PATH)
        if {"entity_id", "issue"}.issubset(existing.columns):
            already = (existing["entity_id"] == entity_id) & (existing["issue"] == kind)
            if bool(already.any()):
                st.info(f"{entity_id} sudah pernah ditandai '{kind}'.")
                return
        row = pd.concat([existing, row], ignore_index=True)
    row.to_csv(FLAGS_PATH, index=False)
    st.success(f"Ditandai {kind} untuk {entity_id}. Masuk antrean triage di halaman Retrain.")


st.subheader("Tandai masalah keanggotaan")
st.caption(
    "Koreksi nilai di atas tidak mengubah keanggotaan. Kalau entity ini "
    "salah gabung (2 orang jadi 1) atau salah pecah (1 orang jadi 2), "
    "tandai — ini umpan balik untuk retrain, bukan edit manual."
)
reviewer_name = st.text_input("Reviewer untuk penandaan", value="reviewer")
f1, f2 = st.columns(2)
if f1.button("Tandai salah gabung"):
    _flag(entity_id, "wrong_merge", reviewer_name)
if f2.button("Tandai salah pecah"):
    _flag(entity_id, "wrong_split", reviewer_name)


# ---- daftar entity bermasalah (setelah penandaan, supaya daftar selalu mencakup yang baru)
if FLAGS_PATH.exists():
    try:
        _all_flags = pd.read_csv(FLAGS_PATH)
        _all_flags["status"] = _all_flags["status"].fillna("open").astype(str)
        _open = _all_flags[_all_flags["status"] == "open"]
        if not _open.empty:
            st.subheader("Entity yang pernah ditandai masalah")
            st.dataframe(
                _open[["entity_id", "issue", "status", "reviewer", "timestamp"]].rename(
                    columns={
                        "entity_id": "Kode entity",
                        "issue": "Masalah",
                        "status": "Status",
                        "reviewer": "Pelapor",
                        "timestamp": "Waktu",
                    }
                ),
                width="stretch",
                hide_index=True,
            )
    except Exception:
        pass
