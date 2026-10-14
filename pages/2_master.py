"""Halaman peninjauan catatan master (PRD FR-09, sisi keluaran).

Catatan master adalah keluaran akhir sistem: satu baris per entity dengan nilai
terbaik untuk setiap kolom. Halaman ini memungkinkan pengguna menelusuri entity,
melihat kolom yang bertentangan, memeriksa catatan anggotanya, dan memperbaiki
nilai master.

Perbaikan nilai master ditulis langsung ke master_customers.parquet dan dicatat
terpisah dari keputusan pasangan. Laporan salah-gabung/salah-pecah dapat
diterapkan sebagai koreksi keanggotaan eksplisit setelah pengguna memilih record
atau entity tujuan dan memberi alasan.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import (
    LABELS_DIR,
    MASTER_PATH,
    OUTPUT_DIR,
    PROCESSED_DATA_PATH,
    PROJECT_ROOT,
    pipeline_locked,
)
from src.ui import (
    format_count,
    monitoring_sidebar,
    page_guide,
    page_header,
    workflow_step,
)

st.set_page_config(page_title="Master - Entity Resolution", page_icon="👥", layout="wide")
page_header(
    "Daftar Customer",
    "Hasil akhir: satu baris per orang. Kalau ada datanya yang berbeda-beda, "
    "kolomnya ditandai agar bisa dibetulkan.",
)
monitoring_sidebar()
page_guide(__file__)
workflow_step(__file__)

if not MASTER_PATH.exists() or not PROCESSED_DATA_PATH.exists():
    st.info(
        "Belum ada master record. Jalankan pipeline dari halaman Upload dulu "
        "(clustering + master_record)."
    )
    st.stop()

AUDIT_PATH = LABELS_DIR / "master_corrections.csv"

FLAGS_PATH_ALL = LABELS_DIR / "membership_flags.csv"
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
master["_conflicted"] = master["conflicted_fields"].map(
    lambda v: len(v) > 0 if hasattr(v, "__len__") else bool(v)
)
mode = st.radio(
    "Tampilkan",
    ["Semua (urut record terbanyak)", "Hanya yang ada data konflik", "Hanya yang pernah dilaporkan"],
    horizontal=True,
    key="master_mode",
)

flags_all = pd.DataFrame()
if FLAGS_PATH_ALL.exists():
    try:
        flags_all = pd.read_csv(FLAGS_PATH_ALL)
        flags_all["status"] = flags_all["status"].fillna("open").astype(str)
    except Exception:
        flags_all = pd.DataFrame()
flagged_ids = (
    set(flags_all["entity_id"].astype(str)) if not flags_all.empty else set()
)

query = st.text_input(
    "Cari customer_id / email / entity_id",
    placeholder="misal: rec_000123 atau john@x.com",
)
if query:
    q = query.strip().lower()
    hits = master[
        master["customer_ids"].apply(lambda x: q in str(x).lower())
        | master["master_email_std"].astype(str).str.lower().str.contains(q, na=False)
        | master["entity_id"].astype(str).str.lower().str.contains(q, na=False)
    ]
elif mode.startswith("Hanya yang ada data konflik"):
    hits = master[master["_conflicted"]]
elif mode.startswith("Hanya yang pernah dilaporkan"):
    hits = master[master["entity_id"].astype(str).isin(flagged_ids)]
else:
    hits = master

# Entity bermasalah didahulukan: itulah yang butuh keputusan manusia.
hits = hits.sort_values(
    ["_conflicted", "record_count"], ascending=[False, False]
).head(1000)
st.caption(
    f"{len(hits):,} customer cocok · "
    + ("ditandai konflik didahulukan" if mode != "Semua (urut record terbanyak)" else "urut dari yang record-nya terbanyak")
)
if hits.empty:
    st.info("Tidak ada customer untuk pilihan ini.")
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
        # Perbarui master_customers.parquet.
        mask = master["entity_id"] == entity_id
        for f, (_, v) in changes.items():
            master.loc[mask, f] = v
        master.to_parquet(MASTER_PATH, index=False)
        # Catatan audit.
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

# ---- koreksi keanggotaan yang ditinjau
if not open_flags.empty:
    st.subheader("Tindak lanjuti laporan keanggotaan")
    st.caption(
        "Laporan salah-gabung/salah-pecah bukan label pasangan dan tidak mengubah "
        "entity sendiri. Pilih laporan, tentukan perubahan, dan berikan alasan. "
        "Koreksi yang berhasil tercatat di Riwayat Keputusan dan diterapkan ke "
        "hasil saat ini. Perhatian: full pipeline berikutnya membangun ulang "
        "keanggotaan dan belum memutar ulang koreksi manual dari log."
    )
    flag_index = st.selectbox(
        "Laporan yang ditangani",
        open_flags.index.tolist(),
        format_func=lambda idx: (
            f"{'Salah digabung' if open_flags.loc[idx, 'issue'] == 'wrong_merge' else 'Salah dipecah'}"
            f" · {open_flags.loc[idx, 'timestamp']} · {open_flags.loc[idx, 'reviewer']}"
        ),
        key=f"membership_flag_{entity_id}",
    )
    selected_flag = open_flags.loc[flag_index]
    issue = str(selected_flag["issue"])
    actor = st.text_input(
        "Nama/kode pelaksana koreksi",
        value="reviewer",
        key=f"correction_actor_{entity_id}",
    )
    reason = st.text_input(
        "Alasan koreksi (wajib)",
        value=str(selected_flag.get("note", "") or ""),
        key=f"correction_reason_{entity_id}",
    )
    pipeline_busy = pipeline_locked() is not None or (OUTPUT_DIR / ".retraining").exists()
    if pipeline_busy:
        st.warning("Koreksi keanggotaan dinonaktifkan selama pipeline/retrain berjalan.")

    if issue == "wrong_merge":
        move_records = st.multiselect(
            "Record yang dipisahkan dari entity ini",
            members["record_id"].astype(str).tolist(),
            key=f"split_records_{entity_id}",
        )
        confirm = st.checkbox(
            "Saya paham record terpilih akan dipindahkan ke entity baru.",
            key=f"confirm_split_{entity_id}",
        )
        if st.button(
            "Terapkan pemisahan",
            type="primary",
            disabled=pipeline_busy or not confirm,
            key=f"apply_split_{entity_id}",
        ):
            if not move_records:
                st.error("Pilih setidaknya satu record untuk dipisahkan.")
            elif not reason.strip():
                st.error("Alasan koreksi wajib diisi.")
            else:
                command = [
                    sys.executable, "-m", "src.entity_correction",
                    "--split", str(entity_id), "--records", *move_records,
                    "--reason", reason.strip(), "--actor", actor.strip() or "reviewer",
                ]
                result = subprocess.run(
                    command, cwd=PROJECT_ROOT, text=True, capture_output=True,
                    encoding="utf-8", errors="replace",
                )
                if result.returncode:
                    st.error("Pemisahan ditolak atau gagal; laporan tetap terbuka.")
                    st.code((result.stdout or "") + (result.stderr or ""))
                else:
                    all_flags = pd.read_csv(FLAGS_PATH_ALL)
                    all_flags.loc[flag_index, "status"] = "resolved"
                    all_flags.loc[flag_index, "note"] = reason.strip()
                    all_flags.to_csv(FLAGS_PATH_ALL, index=False)
                    st.success("Pemisahan diterapkan dan dicatat di riwayat koreksi entity.")
                    st.code(result.stdout)
                    st.rerun()
    elif issue == "wrong_split":
        other_entities = sorted(
            set(master["entity_id"].astype(str)) - {str(entity_id)}
        )
        if not other_entities:
            st.info("Belum ada entity lain yang dapat digabungkan.")
        else:
            target_entity = st.selectbox(
                "Gabungkan dengan entity ini",
                other_entities,
                key=f"merge_target_{entity_id}",
            )
            surviving_entity, absorbed_entity = sorted(
                (str(entity_id), target_entity)
            )
            st.caption(
                f"ID yang dipertahankan: `{surviving_entity}`; anggota "
                f"`{absorbed_entity}` akan dipindahkan ke sana."
            )
            confirm = st.checkbox(
                f"Saya paham hasil penggabungan akan memakai ID {surviving_entity}.",
                key=f"confirm_merge_{entity_id}",
            )
            if st.button(
                "Terapkan penggabungan",
                type="primary",
                disabled=pipeline_busy or not confirm,
                key=f"apply_merge_{entity_id}",
            ):
                if not reason.strip():
                    st.error("Alasan koreksi wajib diisi.")
                else:
                    command = [
                        sys.executable, "-m", "src.entity_correction",
                        "--merge", str(entity_id), target_entity,
                        "--reason", reason.strip(), "--actor", actor.strip() or "reviewer",
                    ]
                    result = subprocess.run(
                        command, cwd=PROJECT_ROOT, text=True, capture_output=True,
                        encoding="utf-8", errors="replace",
                    )
                    if result.returncode:
                        st.error("Penggabungan ditolak atau gagal; laporan tetap terbuka.")
                        st.code((result.stdout or "") + (result.stderr or ""))
                    else:
                        all_flags = pd.read_csv(FLAGS_PATH_ALL)
                        all_flags.loc[flag_index, "status"] = "resolved"
                        all_flags.loc[flag_index, "note"] = reason.strip()
                        all_flags.to_csv(FLAGS_PATH_ALL, index=False)
                        st.success("Penggabungan diterapkan dan dicatat di riwayat koreksi entity.")
                        st.code(result.stdout)
                        st.rerun()
    else:
        st.info(f"Jenis laporan `{issue}` belum memiliki tindakan koreksi.")


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
    "Koreksi nilai master di atas hanya mengubah atribut, bukan identitas entity. "
    "Jika keanggotaan salah, tandai laporan; setelah itu gunakan bagian "
    "**Tindak lanjuti laporan keanggotaan** untuk menerapkan split/merge dengan audit."
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
