"""UI components for entity resolution dashboard."""
from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.config import (
    DEFAULT_BENCHMARK_RULES,
    MATCH_THRESHOLD,
    NON_MATCH_THRESHOLD,
    OUTPUT_DIR,
    REVIEW_THRESHOLD,
    PROJECT_ROOT,
    FieldConfig,
    get_field_configs,
)
from src.splink_model import predictions_path


def _is_blank(value: Any) -> bool:
    """Check if value is missing or empty string."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return True
    try:
        if math.isnan(float(value)):
            return True
    except (TypeError, ValueError):
        pass
    return False


def workflow_step(path: str) -> None:
    """Progress indicator at top of page."""
    step = {
        "1_review.py": 1,
        "2_master.py": 2,
        "3_dashboard.py": 3,
        "4_retrain.py": 4,
        "5_queue.py": 5,
        "6_batch.py": 6,
        "7_gaps.py": 7,
        "8_explain.py": 8,
        "9_history.py": 9,
    }.get(Path(path).name, 0)

    if step:
        steps = [
            ("1", "Upload + Preprocess"),
            ("2", "Master Data"),
            ("3", "Dashboard"),
            ("4", "Retrain"),
            ("5", "Review Queue"),
            ("6", "Batch Processing"),
            ("7", "Gaps"),
            ("8", "Explain"),
            ("9", "History"),
        ]
        icons = {i: (s := f"s{step}") and ("✅" if i < step else ("🔄" if i == step else "⬜")) for i, s in enumerate(steps)}
        st.caption(" / ".join(f"{icons[i]} {name}" for i, name in steps))


def page_header(title: str, description: str = "") -> None:
    """Standard page header."""
    st.title(title)
    if description:
        st.markdown(f"<small>{description}</small>", unsafe_allow_html=True)


def page_guide(path: str) -> None:
    """Show guide for current page."""
    GUIDE = {
        "1_review.py": "Pilih keputusan (Gabung / Bedakan / Tidak yakin) untuk setiap pasangan.",
        "2_master.py": "Lihat data master yang sudah resolved. Satu baris = satu orang unik.",
        "3_dashboard.py": "Ringkasan metrik: berapa banyak yang sudah digabung, perlu dicek, dll.",
        "4_retrain.py": "Latih ulang model dengan label baru dari review manusia.",
        "5_queue.py": "Daftar pasangan yang perlu dicek manusia, diurutkan oleh priority.",
        "6_batch.py": "Proses batch baru: upload CSV atau konek ke database.",
        "7_gaps.py": "Analisa field mana yang perlu diperbaiki.",
        "8_explain.py": "Lihat why: kenapa sistem berpikir dua record itu sama atau berbeda.",
        "9_history.py": "Riwayat proses dari awal sampai akhir.",
    }
    guide = GUIDE.get(Path(path).name)
    if guide:
        st.caption(f"📖 {guide}")


def monitoring_sidebar() -> None:
    """Sidebar with monitoring links."""
    st.sidebar.title("Monitoring")
    st.sidebar.markdown(
        """
    - [Dashboard](3_dashboard)
    - [Riwayat](9_history)
    - [Model info](4_retrain)
    """
    )
    st.sidebar.title("Proses")
    st.sidebar.markdown(
        """
    - [Upload data](app)
    - [Review queue](5_queue)
    - [Master data](2_master)
    """
    )


def how_to_read() -> None:
    """How to interpret probability."""
    with st.expander("📖 Bagaimana membaca angka-angka di bawah?"):
        st.markdown(
            """
        - **Peluang sama** = probabilitas dua record adalah orang yang sama, 0-100%
        - **Keputusan sistem**:
            - 🟢 **DIGABUNG** = peluang tinggi, otomatis digabung
            - 🔴 **BEDA** = peluang sangat rendah, otomatis disimpan terpisah
            - 🟡 **PERLU DIPERIKSA** = peluang di tengah, butuh keputusan manusia
        - **Bukti** = seberapa kuat masing-masing field mendukung/menolak
            - +angka = mendukung (semakin besar semakin kuat)
            - -angka = menolak
        """
        )


# -----------------------------------------------------------------------------
# Field configuration
# -----------------------------------------------------------------------------


FIELD_LABEL = {
    "first_name": "Nama depan",
    "last_name": "Nama belakang",
    "email": "Email",
    "phone": "Nomor telepon",
    "dob": "Tanggal lahir",
    "address": "Alamat",
    "city": "Kota",
    "state": "Provinsi",
    "country": "Negara",
    "core_identity": "Core identity",
}


def field_label(field: str) -> str:
    """Translate field name to Indonesian."""
    return FIELD_LABEL.get(field, field.replace("_", " ").title())


# Comparison level names (from Splink)
LEVEL_LABELS = {
    # Name levels
    0: ("exact", "persis sama", "mendukung"),
    1: ("fuzzy", "hampir sama", "mendukung"),
    2: ("phonetic", "sama fonetik", "mendukung"),
    3: ("initials", "huruf depan sama", "mendukung"),
    4: ("common", "nama umum", "menolak"),
    5: ("null", "salah satu kosong", "netral"),
    6: ("different", "beda", "menolak"),
    # Contact levels
    0: ("exact", "persis sama", "mendukung"),
    1: ("fuzzy", "hampir sama", "mendukung"),
    2: ("domain_only", "hanya domain", "netral"),
    3: ("null", "salah satu kosong", "netral"),
    4: ("different", "beda", "menolak"),
    # Location levels
    0: ("exact", "persis sama", "mendukung"),
    1: ("fuzzy", "hampir sama", "mendukung"),
    2: ("same_state", "provinsi sama", "mendukung"),
    3: ("same_country", "negara sama", "mendukung"),
    4: ("null", "salah satu kosong", "netral"),
    5: ("different", "beda", "menolak"),
    # DOB levels
    0: ("exact", "persis sama", "mendukung"),
    1: ("year_only", "hanya tahun", "mendukung"),
    2: ("partial", "sebagian sama", "netral"),
    3: ("null", "salah satu kosong", "netral"),
    4: ("different", "beda", "menolak"),
}


def similarity_text(label: str | None, code: int | None) -> str:
    """Convert comparison level to human-readable text."""
    if label is None:
        return "tidak ada data"
    
    # For gamma_name, gamma_contact, gamma_location, gamma_dob
    if code is not None and code >= 0:
        level_info = LEVEL_LABELS.get(code, (None, "tidak diketahui", "netral"))
        return level_info[1]
    
    return str(label) if label else "tidak ada data"


def format_score(weight: float | None) -> str:
    """Format log-odds weight as human-readable string."""
    if weight is None or weight == float("-inf"):
        return "tidak ada data"
    sign = "+" if weight > 0 else ""
    return f"{sign}{weight:.1f} bit"


def field_agreement(left: Any, right: Any) -> str:
    """Describe how two field values compare."""
    if _is_blank(left) and _is_blank(right):
        return "keduanya kosong"
    if _is_blank(left) or _is_blank(right):
        return "salah satu kosong"
    left_s = str(left).strip().lower()
    right_s = str(right).strip().lower()
    if left_s == right_s:
        return "sama"
    return "beda"


# -----------------------------------------------------------------------------
# Evidence display
# -----------------------------------------------------------------------------


def model_levels() -> dict:
    """Load model comparison levels from settings."""
    settings_path = OUTPUT_DIR / "settings.json"
    if not settings_path.exists():
        return {}
    import json

    with open(settings_path) as f:
        settings = json.load(f)
    return settings.get("comparison_levels", {})


def decision_label(decision: str | None) -> str:
    """Translate decision code to human-readable label."""
    return {
        "MATCH": "🟢 DIGABUNG",
        "NON_MATCH": "🔴 BEDA",
        "REVIEW": "🟡 PERLU DIPERIKSA",
    }.get(decision or "", "❓ Tidak diketahui")


def format_probability(prob: float | None) -> str:
    """Format probability as percentage string."""
    if prob is None:
        return "-"
    return f"{prob:.1%}"


def format_rate(count: int, total: int) -> str:
    """Format count/total as percentage."""
    if total == 0:
        return "0%"
    return f"{count/total:.1%}"


def probability_verdict(prob: float) -> str:
    """Get human-readable verdict for probability."""
    if prob >= 0.9:
        return "Sistem sangat yakin: peluang di atas 90%, otomatis digabung."
    if prob <= 0.1:
        return "Sistem sangat yakin: peluang di bawah 10%, otomatis disimpan terpisah."
    return "Sistem kurang yakin: peluang di antara 10%-90%, perlu pemeriksaan manusia."


def verdict_plain(decision: str | None) -> str:
    """Get plain text verdict without emoji."""
    return {
        "MATCH": "Otomatis digabung karena peluang tinggi.",
        "NON_MATCH": "Otomatis disimpan terpisah karena peluang sangat rendah.",
        "REVIEW": "Menunggu keputusan manusia.",
    }.get(decision or "", "Tidak diketahui")


def pair_evidence_frame(row: dict, levels: dict) -> "Any":
    """Tabel perbandingan satu pasangan, sudah diterjemahkan ke bahasa manusia."""
    import pandas as pd

    rows = []
    for field in ("core_identity", *FIELD_LABEL):
        gamma_col = f"gamma_{field}"
        code = row.get(gamma_col)
        code = None if code is None or _is_blank(code) else int(code)
        label, m, u = levels.get(gamma_col, {}).get(code, (None, 0.0, 0.0)) if code is not None else (None, 0.0, 0.0)
        left = row.get(f"{field}_l")
        right = row.get(f"{field}_r")
        weight = math.log2(m / u) if m > 0 and u > 0 else None
        evidence = (
            "tidak ada data"
            if code == -1
            else format_score(weight) if weight is not None else "tidak ada data"
        )
        # Gamma description
        gamma_desc = similarity_text(label, code)
        
        rows.append(
            {
                "informasi": field_label(field),
                "record A": "tidak diisi" if _is_blank(left) else str(left),
                "record B": "tidak diisi" if _is_blank(right) else str(right),
                "perbandingan": field_agreement(left, right),
                "gamma level": f"L{code}" if code is not None and code >= 0 else "-",
                "seberapa mirip": gamma_desc,
                "bukti": evidence,
                "_bobot": weight if weight is not None else float("-inf"),
            }
        )
    return pd.DataFrame(rows).sort_values("_bobot", ascending=False).drop(columns="_bobot")


def show_evidence(row: dict, levels: dict) -> None:
    """Bagian "Kenapa?" yang sama persis di halaman review dan explain."""
    frame = pair_evidence_frame(row, levels)
    st.dataframe(
        frame,
        width="stretch",
        hide_index=True,
        height=460,
        column_config={
            "informasi": st.column_config.TextColumn("Informasi", width="small"),
            "seberapa mirip": st.column_config.TextColumn("Seberapa mirip", width="medium"),
            "bukti": st.column_config.TextColumn("Bukti", width="small"),
        },
    )

    support = frame.loc[frame["bukti"].str.contains("mendukung"), "bukti"]
    against = frame.loc[frame["bukti"].str.contains("menolak"), "bukti"]

    # Peringatan konflik: naive Bayes overconfident, jadi pasangan dengan >= 1
    # field yang menolak tetap bisa mendapat peluang "sangat tinggi". Tanpa
    # peringatan ini peninjau melihat "100%" lalu mempercayainya padahal ada
    # kontradiksi di tabel. Ini adalah penyebab utama salah gabung yang lolos.
    prob = row.get("match_probability")
    try:
        high = prob is not None and not _is_blank(prob) and float(prob) >= 0.9
    except (TypeError, ValueError):
        high = False
    if high and not against.empty:
        fields = ", ".join(frame.loc[frame["bukti"].str.contains("menolak"), "informasi"])
        st.warning(
            f"**Ada {len(against)} field yang menolak** ({fields}) meski peluang "
            "tertinggi. Model kadang terlalu yakin karena menghitung bukti serupa "
            "berkali-kali. **Periksa field yang menolak ini manual sebelum "
            "menganggap pasangan ini benar-benar orang yang sama.**"
        )

    if support.empty and against.empty:
        st.info("Tidak ada bukti kuat ke arah mana pun. Ini memang kasus abu-abu.")
    elif against.empty:
        st.success("Semua bukti mendukung: tidak ada satu pun field yang menolak.")
    elif support.empty:
        st.warning("Semua bukti menolak: tidak ada satu pun field yang mendukung.")
    else:
        st.info("Bukti bercampur — itu sebabnya pasangan ini menunggu keputusan Anda.")


# Catatan teknis di incremental_history.jsonl ditulis dalam bahasa Inggris untuk
# mesin. Petakan setiap frasa secara utuh, bukan sebagai potongan kata, agar
# hasil terjemahan tidak menyisakan koma atau kalimat yang tidak lengkap.
_NOTE_EXACT = {
    "wall-clock between stage and apply, not compute time; left as measured":
        "Durasi ini selisih waktu antara simpan dan terapkan, bukan waktu proses. "
        "Dicatat apa adanya.",
    "total entity count; delta recovered as new_records - match_edges":
        "Angka customer baru dihitung dari selisih: record baru dikurangi pasangan yang lolos.",
}


def translate_note(note: Any) -> str:
    """Ubah catatan riwayat berbahasa Inggris menjadi teks yang mudah dipahami.

    Frasa yang dikenal dipetakan utuh. Teks lain diteruskan apa adanya supaya
    catatan yang tidak dikenali tidak hilang diam-diam.
    """
    text = str(note or "").strip()
    if not text:
        return "-"
    return _NOTE_EXACT.get(text, text)


def format_history_table(frame: Any) -> Any:
    """Riwayat batch jadi tabel yang bisa dibaca siapa pun.

    Kolom mentahnya (`_runtime_note`, `_corrected_from`, ...) untuk mesin, bukan
    untuk manusia, dan satu kolom `timestamp` panjang membuat tabel tidak muat.
    Di sini kolomnya diterjemahkan, catatan teknis disatukan jadi satu kolom
    "Catatan", dan kolom Boolean ditulis Ya/Tidak.
    """
    if frame.empty:
        return frame

    import pandas as pd

    out = frame.copy()

    # Kolom baru
    out["waktu"] = pd.to_datetime(out["timestamp"]).dt.strftime("%Y-%m-%d %H:%M")
    out["catatan"] = out["_runtime_note"].apply(translate_note)
    out["sukses"] = out["_success"].map({True: "Ya", False: "Tidak"})

    # Kolom yang tidak perlu
    drop = {"timestamp", "_runtime_note", "_success", "_error"}
    out = out.drop(columns=[c for c in drop if c in out.columns], errors="ignore")

    # Urutan kolom
    reorder = ["waktu", "batch", "step", "sukses", "catatan"]
    existing = [c for c in reorder if c in out.columns]
    others = [c for c in out.columns if c not in reorder]
    return out[existing + others]


# def _lookup_label(gamma_field: str, code: int, levels: dict) -> str:
#     """Ambil label dari comparison level."""
#     if code < 0:
#         return "tidak ada data"
#     level = levels.get(gamma_field, {}).get(code)
#     if level is None:
#         return f"L{code}"
#     return level[0] if isinstance(level, tuple) else str(level)


# def _gamma_badge(gamma_field: str, code: int, levels: dict) -> str:
#     """Buat badge untuk gamma level."""
#     if code < 0:
#         return "❌"
#     label = _lookup_label(gamma_field, code, levels)
#     if label in ("exact", "persis sama"):
#         return "✅"  # exact match
#     if label in ("fuzzy", "hampir sama"):
#         return "🔶"  # close match
#     if label in ("phonetic", "sama fonetik"):
#         return "🔤"  # phonetic
#     if label in ("different", "beda"):
#         return "❌"  # different
#     if label in ("null", "salah satu kosong"):
#         return "⚪"  # null
#     return f"L{code}"