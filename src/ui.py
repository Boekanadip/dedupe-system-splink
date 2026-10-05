# -*- coding: utf-8 -*-
"""Shared Streamlit UI helpers: page header, sidebar context, pagination.

Also holds the single source of truth for user-facing wording (field names,
status names, similarity levels). Every page imports from here so the same
concept is never labelled two different ways, and no reviewer has to learn
that "gamma" is the word for "how similar".
"""
from __future__ import annotations

import math
import re
from typing import Any

import streamlit as st


def page_header(title: str, description: str | None = None) -> None:
    """Title + optional one-line description, same shape on every page."""
    st.title(title)
    if description:
        st.caption(description)


def monitoring_sidebar() -> None:
    """Model aktif, jumlah batch, antrian review, run terakhir — di semua halaman."""
    from src import registry
    from src.config import PROJECT_ROOT

    import json
    import pandas as pd

    LATEST_MODEL = PROJECT_ROOT / "models" / "latest.json"
    REVIEW_QUEUE = PROJECT_ROOT / "data" / "labels" / "review_queue.csv"

    with st.sidebar:
        st.markdown("#### Pencarian Customer Ganda")
        st.caption("Mencari data customer yang sama")
        st.divider()

        st.markdown("#### Model Aktif")
        if LATEST_MODEL.exists():
            try:
                model = json.loads(LATEST_MODEL.read_text(encoding="utf-8"))
                st.caption(f"Versi: `{model['version']}`")
                if model.get("created_at"):
                    st.caption(f"Dibuat: {model['created_at']}")
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                st.caption("Model aktif: (tidak dapat dibaca)")
        else:
            st.caption("Belum ada model aktif")

        reg = registry.load()
        next_idx = reg.get("next_start_index", 0)
        st.caption(
            f"Paket data masuk: {len(reg.get('batches', []))} · "
            f"nomor record 1 s/d {next_idx:,}"
        )

        if REVIEW_QUEUE.exists():
            try:
                queue = pd.read_csv(REVIEW_QUEUE)
                pending = int((queue["review_status"] == "pending").sum())
                st.caption(f"Antrean pemeriksaan: {pending:,} pasangan menunggu")
            except Exception:
                pass

        last = st.session_state.get("last_run")
        if last:
            status = "OK" if last.get("returncode") == 0 else "GAGAL"
            secs = last.get("seconds", 0)
            st.caption(f"Pemrosesan terakhir: {secs}s · {status}")

        st.divider()
        st.markdown("#### Bantuan")

        st.caption("**Baru pakai?** Baca `PANDUAN.md` di folder project.")
        st.caption("Alur: Upload → Ringkasan → Antrean → Pemeriksaan → Daftar Customer")


PAGE_GUIDE: dict[str, tuple[str, list[str]]] = {
    "app.py": (
        "Mulai dari sini kalau pertama kali pakai.",
        [
            "Unggah file CSV data customer.",
            "Jawab pertanyaan tanggal kalau muncul — itu penting.",
            "Klik Analisis batch, tunggu sampai selesai.",
        ],
    ),
    "pages/1_review.py": (
        "Halaman kerja utama: Anda yang memutuskan.",
        [
            "Baca bagian 'Kenapa sistem berpikir begitu?' tiap pasangan.",
            "Klik 'Orang yang sama' atau 'Berbeda orang'.",
            "Jangan buru-buru. Salah gabung lebih merusak daripada lupa gabung.",
        ],
    ),
    "pages/2_master.py": (
        "Hasil akhir: satu baris per orang.",
        [
            "Cari customer yang salah datanya, lalu betulkan.",
            "Kalau ada 2 orang berbeda yang jadi 1, tandai 'Salah gabung'.",
        ],
    ),
    "pages/5_queue.py": (
        "Semua pasangan yang perlu diperiksa manusia.",
        [
            "Antrean kerja hanya sampel kecil; halaman ini menampilkan semuanya.",
            "Saring, lalu klik 'Tambahkan yang disaring ke antrean'.",
        ],
    ),
    "pages/8_explain.py": (
        "Pelajari cara sistem berpikir, supaya bisa menilai sendiri.",
        [
            "Pilih dua record, lihat perbandingan tiap field.",
            "Kalau tidak paham bobotnya, pakai untuk belajar.",
        ],
    ),
    "pages/3_dashboard.py": (
        "Hanya untuk melihat. Tidak ada tombol untuk mengubah apa pun.",
        [
            "Klik Refresh kalau datanya baru saja diperbarui.",
            "Lihat berapa yang digabung otomatis vs perlu diperiksa.",
        ],
    ),
    "pages/6_batch.py": (
        "Periksa data baru sebelum dipakai.",
        [
            "Centang baris yang tidak boleh digabung dengan customer mana pun.",
            "Klik 'Simpan persetujuan', lalu 'Terapkan'.",
            "Baris yang tidak disetujui tetap masuk sebagai customer sendiri.",
        ],
    ),
    "pages/7_gaps.py": (
        "Untuk mencari data yang mungkin terlewat.",
        [
            "Record sendirian = belum pernah cocok dengan siapa pun.",
            "Bisa saja memang unik, bisa saja duplikat yang terlewat.",
            "Cari satu record, lalu lihat siapa saja yang sistem bandingkan dengan dia.",
        ],
    ),
    "pages/9_history.py": (
        "Jejak audit: siapa mengubah apa dan kapan.",
        [
            "Ketik nomor record untuk melihat semua jejaknya.",
            "Dipakai saat ada yang bertanya 'kenapa customer ini digabung?'.",
        ],
    ),
    "pages/4_retrain.py": (
        "Halaman ini hanya untuk yang sudah paham. Hampir tidak perlu disentuh.",
        [
            "Kalau tidak ada masalah, biarkan saja — sistemnya sudah jalan.",
            "Ubah batas kepastian hanya kalau ada alasan yang jelas.",
            "Latih ulang model hanya setelah data dan keputusan manual sudah bersih.",
        ],
    ),
}


def page_guide(page_file: str) -> None:
    """Bantuan singkat di halaman ini, sesuai halaman mana yang sedang dibuka."""
    import os

    key = page_file.replace("\\", "/")
    guide = PAGE_GUIDE.get(key) or PAGE_GUIDE.get(os.path.basename(key))
    if not guide:
        return
    judul, langkah = guide
    with st.expander("💡 Apa yang harus saya lakukan di halaman ini?"):
        st.markdown(f"**{judul}**")
        for item in langkah:
            st.markdown(f"- {item}")


def paginate(df, page_size: int = 50, key: str = "page") -> tuple[Any, int]:
    """Halaman DataFrame. Returns (page_df, total_pages)."""
    import pandas as pd

    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return df, 1

    n = len(df)
    total_pages = max(1, (n + page_size - 1) // page_size)
    page = st.number_input(
        "Halaman",
        min_value=1,
        max_value=total_pages,
        value=1,
        key=key,
    )
    start = (page - 1) * page_size
    return df.iloc[start : start + page_size].copy(), total_pages


# --- User-facing wording -------------------------------------------------
# One place, so a reviewer learns "Tingkat kesamaan" once and sees it
# everywhere. Sourced from the real comparison set in src/splink_model.py.

FIELD_LABEL: dict[str, str] = {
    "first_name_std": "Nama depan",
    "last_name_std": "Nama belakang",
    "email_std": "Email",
    "phone_std": "Nomor telepon",
    "dob_std": "Tanggal lahir",
    "address_std": "Alamat",
    "city_std": "Kota",
    "state_std": "Provinsi",
    "country_std": "Negara",
}

# Model verdicts, in the words a reviewer actually thinks in.
DECISION_LABEL: dict[str, str] = {
    "MATCH": "Digabung otomatis",
    "REVIEW": "Perlu diperiksa",
    "NON_MATCH": "Bukan orang yang sama",
}

DECISION_HELP: dict[str, str] = {
    "MATCH": "Sistem yakin ini orang yang sama, jadi sudah digabung sendiri.",
    "REVIEW": "Sistem tidak cukup yakin. Anda yang memutuskan.",
    "NON_MATCH": "Sistem yakin ini dua orang berbeda.",
}

# Warna badge per status supaya mata bisa menangkap tanpa membaca teks.
DECISION_STYLE: dict[str, tuple[str, str]] = {
    "MATCH": ("green", "✅"),
    "REVIEW": ("orange", "⏳"),
    "NON_MATCH": ("gray", "🚫"),
}

LABEL_LABEL: dict[str, str] = {
    "match": "Orang yang sama",
    "no_match": "Berbeda orang",
    "": "Belum diputuskan",
    None: "Belum diputuskan",
}

REVIEW_STATUS_LABEL: dict[str, str] = {
    "pending": "Menunggu",
    "reviewed": "Sudah diperiksa",
}

# Where a queued pair came from. The raw stratum codes are meaningless to a
# reviewer, so every one seen on disk gets a plain-language description.
STRATUM_LABEL: dict[str, str] = {
    "match_precision_check": "Cek ketepatan hasil gabung otomatis",
    "device_truth_positive_topup": "Duplikat yang sudah diketahui pasti",
    "review_band_random": "Sampel acak yang perlu diperiksa",
    "manual_review": "Ditambahkan dari halaman Antrean",
    "singleton_candidate": "Kandidat untuk record sendirian",
    "uncovered_review": "Belum pernah masuk antrean",
}


def field_label(field: str) -> str:
    """Nama field dalam bahasa manusia. Unknown columns keep their own name."""
    return FIELD_LABEL.get(field, field.replace("_std", "").replace("_", " "))


def field_labels(fields) -> list[str]:
    return [field_label(f) for f in fields]


def decision_label(decision: Any) -> str:
    return DECISION_LABEL.get(str(decision), "Belum dinilai")


def decision_badge(decision: Any) -> Any:
    """Badge berwarna untuk status keputusan, supaya cepat dibaca sekilas."""
    color, icon = DECISION_STYLE.get(str(decision), ("blue", "❔"))
    return st.badge(decision_label(decision), icon=icon, color=color)


def label_label(label: Any) -> str:
    if label is None or (isinstance(label, float) and math.isnan(label)):
        return LABEL_LABEL[None]
    text = str(label).strip()
    return LABEL_LABEL.get(text, text or LABEL_LABEL[None])


def review_status_label(status: Any) -> str:
    return REVIEW_STATUS_LABEL.get(str(status), str(status))


def stratum_label(stratum: Any) -> str:
    text = str(stratum)
    return STRATUM_LABEL.get(text, text.replace("_", " "))


def verdict_plain(decision: Any) -> str:
    """Status model dalam kalimat satu baris, bukan kode."""
    return DECISION_HELP.get(str(decision), "Status belum diketahui.")


def format_probability(prob: Any) -> str:
    """Peluang sebagai persentase bulat tanpa notasi ilmiah.

    Skor di bawah ambang baca tetap ditulis dengan jumlah yang sama, tapi
    dibulatkan agar tidak ada "1e-10" di layar.
    """
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return "tidak tersedia"
    if math.isnan(p):
        return "tidak tersedia"
    if p <= 0:
        return "0%"
    if p >= 0.99999:
        return "100%"
    if p >= 0.01:
        return _pct(p, 0)
    # Di bawah 0,01%: 1e-10 dan 1e-4 sama-sama tidak terbaca orang, jadi
    # tulis batas baca, bukan angka presisi tinggi.
    return "kurang dari 0,01%"


def _pct(value: float, digits: int) -> str:
    """Persentase dengan pembulatan Indonesia (koma desimal)."""
    return f"{value * 100:.{digits}f}%".replace(".", ",")


def format_rate(rate: Any, digits: int = 2) -> str:
    """Rasio 0..1 jadi persentase bulat, mis. 0.1477 -> 14,77%."""
    try:
        value = float(rate)
    except (TypeError, ValueError):
        return "tidak tersedia"
    if math.isnan(value):
        return "tidak tersedia"
    return _pct(value, digits)


def format_count(value: Any, suffix: str = "") -> str:
    """Angka pecah jadi pemisah ribuan Indonesia, mis. 48380 -> 48.380."""
    try:
        return f"{int(value):,}".replace(",", ".") + suffix
    except (TypeError, ValueError):
        return str(value) + suffix


def format_threshold(value: Any) -> str:
    """Ambang keputusan sebagai persentase, bukan notasi ilmiah.

    Angka 1e-10 di layar tidak bisa dibaca siapa pun, dan lebih buruk: terlihat
    seperti presisi yang tidak perlu. Yang penting hanya "di bawah sini berarti
    pasti berbeda orang", jadi cukup ditulis "hampir 0%".
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "tidak tersedia"
    if math.isnan(v):
        return "tidak tersedia"
    if v <= 0:
        return "0%"
    if v < 0.0001:
        # 1e-10, 1e-300: semua ini secara fungsional "hampir nol".
        return "hampir 0%"
    if v >= 0.99999:
        return "100%"
    return f"{v * 100:.2f}%".replace(".", ",")


def format_duration(seconds: Any) -> str:
    """Detik jadi kalimat pendek: 4.8 dtk / 90 dtk / 45 mnt / 3 jam."""
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "-"
    if math.isnan(s):
        return "-"
    if s < 60:
        return f"{s:.1f} dtk".replace(".", ",")
    if s < 3600:
        return f"{s / 60:.0f} mnt"
    if s < 86400:
        return f"{s / 3600:.1f} jam".replace(".", ",")
    return f"{s / 86400:.0f} hari"


def format_timestamp(value: Any) -> str:
    """ISO timestamp -> '05 Okt 2026, 14:15'."""
    import pandas as pd

    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    text = str(value)
    try:
        stamp = pd.Timestamp(text)
    except (ValueError, TypeError):
        return text
    if pd.isna(stamp):
        return text
    bulan = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
             "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
    return f"{stamp.day:02d} {bulan[stamp.month - 1]} {stamp.year}, {stamp:%H:%M}"


def format_bool(value: Any) -> str:
    """True/False -> Ya/Tidak/- supaya tabel tidak penuh checkbox."""
    if value is None:
        return "-"
    if isinstance(value, float) and math.isnan(value):
        return "-"
    if isinstance(value, bool):
        return "Ya" if value else "Tidak"
    return str(value)


def probability_verdict(prob: Any) -> str:
    """Kesimpulan satu kalimat dari angka peluang, untuk yang bukan analis data."""
    try:
        p = float(prob)
    except (TypeError, ValueError):
        return "Peluang tidak tersedia."
    if math.isnan(p):
        return "Peluang tidak tersedia."
    if p >= 0.9:
        return "Sistem sangat yakin: **kemungkinan besar orang yang sama**."
    if p >= 0.5:
        return "Sistem cenderung yakin, tapi belum cukup untuk digabung sendiri."
    if p >= 0.01:
        return "Sistem tidak yakin. Ada beberapa yang cocok, tapi bukan semua."
    if p > 0:
        return (
            "Sistem cenderung yakin ini **dua orang berbeda**. "
            "Kalau ini keliru, biasanya karena satu field berubah saja "
            "(misal nama ganti karena menikah)."
        )
    return "Peluang nol: tidak ada satu pun field yang cocok."


def format_score(score: Any) -> str:
    """Bukti bertanda +/- jadi kalimat, bukan angka murni."""
    try:
        w = float(score)
    except (TypeError, ValueError):
        return "tidak tersedia"
    if math.isnan(w):
        return "tidak tersedia"
    if w >= 8:
        return "sangat kuat mendukung"
    if w >= 3:
        return "cukup mendukung"
    if w >= 1:
        return "lembut mendukung"
    if w >= -1:
        return "tidak ada arah"
    if w >= -3:
        return "lembut menolak"
    if w >= -8:
        return "cukup menolak"
    return "sangat kuat menolak"


def field_agreement(left: Any, right: Any) -> str:
    """Status satu field: sama / mirip handled elsewhere / beda / ada yang kosong."""
    if left is None or right is None:
        return "tidak ada data"
    ls = "" if _is_blank(left) else str(left)
    rs = "" if _is_blank(right) else str(right)
    if not ls and not rs:
        return "tidak ada data"
    if not ls or not rs:
        return "hanya ada di salah satu"
    if ls == rs:
        return "sama persis"
    return "berbeda"


def _is_blank(value: Any) -> bool:
    try:
        import pandas as pd

        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def similarity_text(level_label: Any, level_code: Any) -> str:
    """Terjemahkan label level model (bahasa Inggris) ke bahasa reviewer.

    Level 0 adalah yang paling mirip; kode tertinggi = "tidak ada yang cocok".
    """
    if level_code is None or _is_blank(level_code):
        return "tidak ada data di field ini"
    text = str(level_label or "").lower()
    if "all other" in text:
        return "tidak ada yang cocok"
    if "damerau" in text:
        return "sangat mirip, beda 1 karakter saja (kemungkinan salah ketik)"
    if "exact match on date of birth" in text or "exact match on dob" in text:
        return "sama persis"
    if "exact match on username" in text:
        return "bagian sebelum @ sama, domain beda"
    if "exact match" in text:
        return "sama persis"
    match = re.search(r">=\s*([\d.]+)", text)
    if match:
        pct = round(float(match.group(1)) * 100)
        if pct >= 90:
            return f"sangat mirip (sekitar {pct}% mirip)"
        if pct >= 80:
            return f"mirip (sekitar {pct}% mirip)"
        return f"agak mirip (sekitar {pct}% mirip)"
    month = re.search(r"<=\s*(\d+)\s*month", text)
    if month:
        return f"selisih paling lama {month.group(1)} bulan"
    year = re.search(r"<=\s*(\d+)\s*year", text)
    if year:
        return f"selisih paling lama {year.group(1)} tahun"
    return str(level_label) if level_label else "tidak dapat dijelaskan"


def how_to_read() -> None:
    """Penjelasan satu kali pakai, untuk orang yang belum pernah dengar probabilitas."""
    with st.expander("Cara membaca halaman ini"):
        st.markdown(
            """
Setiap pasangan record diberi satu **angka peluang dari 0% sampai 100%** yang
menjawab satu pertanyaan: *"Kedua record ini orang yang sama atau bukan?"*

- **Mendekati 100%** -> sistem sangat yakin ini orang yang sama
- **Sekitar 50%** -> sistem tidak bisa memutuskan, silakan menilai sendiri
- **Mendekati 0%** -> sistem yakin ini dua orang berbeda

Aturan yang dipakai sistem:

| Angka peluang | Yang dilakukan sistem |
|---|---|
| 90% ke atas | Digabung otomatis |
| Di antara 0% dan 90% | Masuk antrean, menunggu keputusan Anda |
| Mendekati 0% | Dianggap dua orang berbeda |

Kalau ada yang terdengar tidak masuk akal, buka bagian **"Kenapa?"** di bawah
tiap pasangan. Di situ tiap field dibandingkan satu per satu, jadi bisa dicek
sendiri tanpa perlu percaya pada angka.
"""
        )


# --- "Kenapa?" table, shared by the review page and the explain page -----

def model_levels() -> dict[str, dict[int, tuple[str, float, float]]]:
    """Tingkat kesamaan per field dari model aktif: {gamma_col: {kode: (label, m, u)}}.

    Splink memberi kode level terbalik dari urutan di model.json: kode 0 adalah
    level "All other comparisons" (paling tidak mirip), kode tertinggi adalah
    exact match. Dipetakan di sini sekali saja supaya tidak ada halaman yang
    salah baca arah.
    """
    from src import model_lifecycle

    latest = model_lifecycle.latest()
    if latest is None:
        return {}
    settings = model_lifecycle.load_model_json(latest)
    settings = settings.get("settings", settings)

    levels: dict[str, dict[int, tuple[str, float, float]]] = {}
    for comp in settings.get("comparisons", []):
        gamma_col = "gamma_" + comp.get("output_column_name", "")
        ordered = [
            (
                str(lvl.get("label_for_charts", f"level {i}")),
                float(lvl.get("m_probability", 0) or 0),
                float(lvl.get("u_probability", 0) or 0),
            )
            for i, lvl in enumerate(comp.get("comparison_levels", []))
        ]
        last = len(ordered) - 1
        levels[gamma_col] = {last - i: entry for i, entry in enumerate(ordered)}
    return levels


def pair_evidence_frame(row: dict, levels: dict) -> "Any":
    """Tabel perbandingan satu pasangan, sudah diterjemahkan ke bahasa manusia."""
    import pandas as pd

    rows = []
    for field in FIELD_LABEL:
        gamma_col = f"gamma_gamma_{field}"
        code = row.get(gamma_col)
        code = None if code is None or _is_blank(code) else int(code)
        label, m, u = levels.get(gamma_col, {}).get(code, (None, 0.0, 0.0)) if code is not None else (None, 0.0, 0.0)
        left = row.get(f"{field}_l")
        right = row.get(f"{field}_r")
        weight = math.log2(m / u) if m > 0 and u > 0 else None
        rows.append(
            {
                "informasi": field_label(field),
                "record A": "tidak diisi" if _is_blank(left) else str(left),
                "record B": "tidak diisi" if _is_blank(right) else str(right),
                "perbandingan": field_agreement(left, right),
                "seberapa mirip": similarity_text(label, code),
                "bukti": format_score(weight) if weight is not None else "tidak ada data",
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
    if support.empty and against.empty:
        st.info("Tidak ada bukti kuat ke arah mana pun. Ini memang kasus abu-abu.")
    elif against.empty:
        st.success("Semua bukti mendukung: tidak ada satu pun field yang menolak.")
    elif support.empty:
        st.warning("Semua bukti menolak: tidak ada satu pun field yang mendukung.")
    else:
        st.info("Bukti bercampur — itu sebabnya pasangan ini menunggu keputusan Anda.")


# Catatan teknis di incremental_history.jsonl ditulis bahasa Inggris untuk mesin.
# Dipetakan sebagai frasa utuh, bukan potongan kata: mengganti potongan
# menyisakan koma menggantung dan kalimat setengah jadi.
_NOTE_EXACT = {
    "wall-clock between stage and apply, not compute time; left as measured":
        "Durasi ini selisih waktu antara simpan dan terapkan, bukan waktu proses. "
        "Dicatat apa adanya.",
    "total entity count; delta recovered as new_records - match_edges":
        "Angka customer baru dihitung dari selisih: record baru dikurangi pasangan yang lolos.",
}


def translate_note(note: Any) -> str:
    """Catatan riwayat bahasa Inggris -> bahasa manusia.

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
    import pandas as pd

    if frame is None or (hasattr(frame, "empty") and frame.empty):
        return frame if frame is not None else pd.DataFrame()

    df = frame.copy()

    # Catatan teknis disatukan jadi satu kolom, bukan sebar di 4 kolom.
    notes = []
    for col in ("_runtime_note", "_correction"):
        if col in df.columns:
            notes.append(df[col].fillna("").astype(str))
    if notes:
        df["Catatan"] = pd.concat(notes, axis=1).apply(
            lambda row: " · ".join(part.strip() for part in row if part.strip()), axis=1
        )
        df["Catatan"] = df["Catatan"].map(translate_note).replace("", "-")

    rename = {
        "timestamp": "Waktu",
        "batch": "Paket data",
        "rows": "Baris",
        "new_records": "Record baru",
        "new_entities": "Customer baru",
        "entity_merges": "Digabung",
        "affected_entities": "Tersentuh",
        "match_edges": "Pasangan cocok",
        "review_pairs_added": "Perlu diperiksa",
        "runtime_seconds": "Durasi",
        "applied_from_staging": "Dari antrean",
        "_runtime_outlier": "Anomali waktu",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    if "Waktu" in df.columns:
        df["Waktu"] = df["Waktu"].map(format_timestamp)
    if "Durasi" in df.columns:
        df["Durasi"] = df["Durasi"].map(format_duration)
    if "Anomali waktu" in df.columns:
        df["Anomali waktu"] = df["Anomali waktu"].map(format_bool)
    if "Dari antrean" in df.columns:
        df["Dari antrean"] = df["Dari antrean"].map(format_bool)

    # Kolom bantu sisanya dibuang: sudah masuk Catatan.
    df = df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")

    for col in ("Baris", "Record baru", "Customer baru", "Tersentuh", "Pasangan cocok"):
        if col in df.columns:
            df[col] = df[col].map(format_count)
    if "Digabung" in df.columns:
        df["Digabung"] = df["Digabung"].map(
            lambda v: str(len(v)) if isinstance(v, list) else str(v)
        )
    if "Perlu diperiksa" in df.columns:
        df["Perlu diperiksa"] = df["Perlu diperiksa"].map(format_count)

    return df

