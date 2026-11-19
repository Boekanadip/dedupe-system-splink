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
    OUTPUT_DIR,
    REVIEW_THRESHOLD,
    PROJECT_ROOT,
)
from src.splink_model import predictions_path

DECISION_LABEL = {
    "MATCH": "Digabung",
    "REVIEW": "Perlu diperiksa",
    "NON_MATCH": "Berbeda",
}


def format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "-"
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}j {minutes}m {seconds}d" if hours else f"{minutes}m {seconds}d"


def format_threshold(value: float | int | None) -> str:
    return "-" if value is None else f"{float(value):.3f}"


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
        icons = {i: ("✅" if i < step else ("🔄" if i == step else "⬜")) for i, _ in enumerate(steps)}
        st.caption(" / ".join(f"{icons[i]} {name}" for i, name in steps))


def page_header(title: str, description: str = "") -> None:
    """Standard page header."""
    st.title(title)
    if description:
        st.markdown(f"<small>{description}</small>", unsafe_allow_html=True)


NAV_PAGES = [
    ("upload", "app_streamlit.py", "Upload Data"),
    ("review", "1_review.py", "Pemeriksaan"),
    ("master", "2_master.py", "Data Master"),
    ("dashboard", "3_dashboard.py", "Ringkasan"),
    ("retrain", "4_retrain.py", "Latih Ulang"),
    ("queue", "5_queue.py", "Antrean"),
    ("batch", "6_batch.py", "Pemrosesan Batch"),
    ("gaps", "7_gaps.py", "Kesenjangan"),
    ("explain", "8_explain.py", "Penjelasan"),
    ("history", "9_history.py", "Riwayat"),
]


def render_sidebar(current_page_key: str) -> None:
    st.sidebar.title("Deduplication")
    st.sidebar.caption("CRM Entity Resolution")
    keys = [key for key, _, _ in NAV_PAGES]
    selected = st.sidebar.selectbox(
        "Pilih halaman", keys, index=keys.index(current_page_key),
        format_func=lambda key: next(title for k, _, title in NAV_PAGES if k == key),
        key=f"app_navigation_{current_page_key}",
    )
    if selected != current_page_key:
        page = st.session_state.get("registered_pages", {}).get(selected)
        if page is None:
            st.error(f"Halaman belum terdaftar: {selected}")
            st.stop()
        st.switch_page(page)
    st.sidebar.divider()
    title = next(title for key, _, title in NAV_PAGES if key == current_page_key)
    st.sidebar.subheader(title)
    st.sidebar.caption("Halaman aktif")
    st.sidebar.divider()
    st.sidebar.subheader("Model Aktif")
    st.sidebar.caption(f"Threshold match: {MATCH_THRESHOLD}")
    st.sidebar.caption(f"Threshold review: {REVIEW_THRESHOLD}")


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


# ponytail: mapping level ini mengikuti urutan level pada build_*_comparison().
# Kalau urutan level model berubah, mapping ini harus ikut berubah.
GAMMA_LEVELS: dict[str, dict[int, tuple[str, str, str]]] = {
    "gamma_name": {
        -1: ("null", "kedua nama kosong", "netral"),
        0: ("different", "nama beda", "menolak"),
        1: ("phonetic", "nama fonetik sama", "mendukung"),
        2: ("fuzzy", "nama hampir sama", "mendukung"),
        3: ("exact", "nama persis sama", "mendukung"),
    },
    "gamma_contact": {
        -1: ("null", "kontak kosong", "netral"),
        0: ("different", "kontak beda", "menolak"),
        1: ("phone_fuzzy", "telepon hampir sama", "mendukung"),
        2: ("email_fuzzy", "email hampir sama", "mendukung"),
        3: ("one_exact", "email atau telepon sama", "mendukung"),
        4: ("both_exact", "email dan telepon sama", "mendukung"),
    },
    "gamma_location": {
        -1: ("null", "lokasi kosong", "netral"),
        0: ("different", "lokasi beda", "menolak"),
        1: ("street", "alamat sama", "mendukung"),
        2: ("state", "provinsi sama", "mendukung"),
        3: ("city", "kota sama", "mendukung"),
        4: ("street_state", "alamat dan provinsi sama", "mendukung"),
        5: ("full", "alamat, kota, dan provinsi sama", "mendukung"),
    },
    "gamma_dob": {
        -1: ("null", "tanggal lahir kosong", "netral"),
        0: ("different", "tanggal lahir beda", "menolak"),
        1: ("year", "tahun lahir sama", "mendukung"),
        2: ("exact", "tanggal lahir persis sama", "mendukung"),
    },
}


def format_score(weight: float | None) -> str:
    """Format log-odds weight as human-readable string."""
    if weight is None:
        return "tidak ada data"
    # Weight tak terhingga (u = 0): bobot maksimal
    if weight == float("inf"):
        return "+∞ bit"
    if weight == float("-inf"):
        return "-∞ bit"
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
    comparison_levels = settings.get("comparison_levels", {})
    # JSON round-trip converts integer keys to strings;
    # convert gamma code sub-keys back to int so assertions work
    for name in comparison_levels:
        inner = comparison_levels[name]
        if isinstance(inner, dict):
            comparison_levels[name] = {int(k) if isinstance(k, str) and k.lstrip('-').isdigit() else k: v
                                       for k, v in inner.items()}
    return comparison_levels


def label_label(label: str | None) -> str:
    return {"match": "Gabung", "no_match": "Bedakan", "unsure": "Tidak yakin", "": "Belum diputuskan"}.get(str(label or ""), str(label or "-"))


def review_status_label(status: str | None) -> str:
    return {"pending": "Menunggu", "reviewed": "Sudah diperiksa", "completed": "Selesai"}.get(str(status or ""), str(status or "-"))


def stratum_label(value: str | None) -> str:
    return str(value or "Tidak diketahui").replace("_", " ").title()


def probability_band_help() -> str:
    return "Di bawah threshold review = berbeda; di antara threshold = perlu diperiksa; di atas threshold match = sama."


def decision_label(decision: str | None) -> str:
    """Translate decision code to human-readable label."""
    return {
        "MATCH": "🟢 DIGABUNG",
        "NON_MATCH": "🔴 BEDA",
        "REVIEW": "🟡 PERLU DIPERIKSA",
    }.get(decision or "", "❓ Tidak diketahui")


def format_count(value: int | float | None) -> str:
    return "-" if value is None else f"{int(value):,}"


def paginate(frame: Any, page_size: int = 25, key: str = "page"):
    total = len(frame)
    pages = max(1, (total + page_size - 1) // page_size)
    page = st.number_input("Halaman", min_value=1, max_value=pages, value=1, step=1, key=key)
    start = (page - 1) * page_size
    return frame.iloc[start:start + page_size], page


def format_probability(prob: float | None) -> str:
    """Format probability as percentage string."""
    if prob is None:
        return "-"
    return f"{prob:.1%}"


def format_rate(count: int, total: int | None = None) -> str:
    """Format count/total or a proportion as percentage."""
    if total is None:
        return f"{float(count):.1%}"
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
    gamma_fields = {
        "first_name": "gamma_name",
        "last_name": "gamma_name",
        "email": "gamma_contact",
        "phone": "gamma_contact",
        "dob": "gamma_dob",
        "address": "gamma_location",
        "city": "gamma_location",
        "state": "gamma_location",
        "country": "gamma_location",
    }
    source_fields = {
        "first_name": "first_name_std",
        "last_name": "last_name_std",
        "email": "email_std",
        "phone": "phone_std",
        "dob": "dob_std",
        "address": "address_std",
        "city": "city_std",
        "state": "state_std",
        "country": "country_std",
    }
    for field in (field for field in FIELD_LABEL if field != "core_identity"):
        gamma_col = gamma_fields.get(field, f"gamma_{field}")
        code = row.get(gamma_col)
        code = None if code is None or _is_blank(code) else int(code)
        
        # Gunakan mapping GAMMA_LEVELS untuk deskripsi tingkat banding
        level_info = GAMMA_LEVELS.get(gamma_col, {}).get(code) if code is not None else None

        # Ambil bobot dari settings.json jika struktur valid (3 elemen label/m/u)
        weight = None
        setting = levels.get(gamma_col, {}).get(code) if code is not None else None
        if isinstance(setting, (list, tuple)) and len(setting) == 3:
            _label, m, u = setting
            if m > 0 and u > 0:
                weight = math.log2(m / u)

        # Arah mendukung/menolak dari mapping; fallback jika mapping kosong
        label = None
        fallback_direction = None
        if level_info:
            label = level_info[0]
            fallback_direction = level_info[2]
        else:
            # Kode di luar mapping: jangan mengarang arah. Bobot tetap dipakai
            # kalau tersedia dari settings.json.
            fallback_direction = None

        # Buat kolom evidence
        evidence = (
            "tidak ada data"
            if code == -1
            else format_score(weight) if weight is not None
            else f"{fallback_direction} (bobot belum tersedia)" if fallback_direction
            else "tidak ada data"
        )
        # Deskripsi "Seberapa mirip" menggunakan level_info
        gamma_desc = level_info[1] if level_info else (
            "tidak ada data" if code == -1 else f"level perbandingan L{code}"
        )
        # Simpan arah untuk ringkasan "menolak/mendukung"
        arah = level_info[2] if level_info else ""

        source_field = source_fields.get(field)
        left = row.get(f"{source_field}_l") if source_field else row.get("first_name_std_l")
        right = row.get(f"{source_field}_r") if source_field else row.get("first_name_std_r")
        evidence_raw = evidence
        # Gamma contact adalah level gabungan email + telepon. Jangan salin
        # label gabungan ke kedua baris: bukti tiap field harus mencerminkan nilainya.
        if field in ("email", "phone") and code is not None and code >= 0:
            same = not _is_blank(left) and not _is_blank(right) and str(left) == str(right)
            if same:
                arah, gamma_desc = "mendukung", f"{field_label(field)} sama"
            elif code == 0:
                arah, gamma_desc = "menolak", f"{field_label(field)} beda"
            elif field == "email" and code in (2, 3):
                arah, gamma_desc = "mendukung", "email hampir sama"
            else:
                arah, gamma_desc = "menolak", f"{field_label(field)} beda"
            fallback_direction = arah
            evidence_raw = f"{arah} (bobot belum tersedia)" if weight is None else format_score(weight)

        rows.append(
            {
                "informasi": field_label(field),
                "record A": "tidak diisi" if _is_blank(left) else str(left),
                "record B": "tidak diisi" if _is_blank(right) else str(right),
                "perbandingan": field_agreement(left, right),
                "seberapa mirip": gamma_desc,
                "bukti": evidence_raw,
                "_bobot": weight if weight is not None else float("-inf"),
                "_arah": arah,
            }
        )
    return pd.DataFrame(rows).sort_values("_bobot", ascending=False).drop(columns="_bobot")


def show_evidence(row: dict, levels: dict) -> None:
    """Bagian "Kenapa?" yang sama persis di halaman review dan explain."""
    frame = pair_evidence_frame(row, levels)
    # Gunakan kolom _arah (arah mendukung/menolak) untuk menghitung ringkasan
    # agar tidak bergantung pada format teks evidence yang bisa berubah.
    support = frame.loc[frame["_arah"] == "mendukung"]
    against = frame.loc[frame["_arah"] == "menolak"]
    # pilih kolom yang boleh tampil; tidak bergantung pada ada/tidaknya _bobot
    display_cols = [
        c for c in frame.columns if c not in {"_arah", "_bobot", "bukti"}
    ]
    display_frame = frame[display_cols]

    st.dataframe(
        display_frame,
        width="stretch",
        hide_index=True,
        height=460,
        column_config={
            "informasi": st.column_config.TextColumn("Informasi", width="small"),
            "seberapa mirip": st.column_config.TextColumn("Seberapa mirip", width="medium"),
        },
    )

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
        fields = ", ".join(against["informasi"])
        st.warning(
            f"**Ada {len(against)} field yang menolak** ({fields}) meski peluang "
            "tertinggi. Model kadang terlalu yakin karena menghitung bukti serupa "
            "berkali-kali. **Periksa field yang menolak ini manual sebelum "
            "menganggap pasangan ini benar-benar orang yang sama.**"
        )

    if support.empty and against.empty:
        return
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
    if "_runtime_note" not in out.columns:
        out["_runtime_note"] = ""
    if "_success" not in out.columns:
        out["_success"] = True
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