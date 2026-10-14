"""Buat batch CRM sintetis dengan jawaban benar yang diketahui sejak awal.

Alasan pembuatan
    Berkas pengembangan berisi 51.555 baris tidak dapat menjawab apakah sistem
    menangani salah ketik atau keliru menggabungkan dua orang yang berbagi email,
    karena tidak ada berkas yang mencatat baris mana yang seharusnya mewakili
    orang yang sama. Di berkas itu, `device_id(s)` berpasangan satu-ke-satu
    dengan customer_id, sehingga evaluasi yang ada hanya membuktikan bahwa
    pipeline meniru pengelompokan sumber, bukan bahwa pengelompokan itu benar.

    Berkas ini berisi jawaban acuan. Setiap kategori sengaja dibuat agar hasil
    proses dapat dihitung, bukan hanya diperiksa sekilas.

Komposisi (200 baris)
    150     pelanggan unik tanpa kerusakan                 data dasar
     10  5% baris dari berkas asli                         5 pasang: asli + salinan salah ketik
     10  5% baris dengan nilai kosong                      termasuk 3 tanpa kontak
     20 10% duplikat
           4  2 pasang identik pada semua kolom              harus digabung
           6  3 pasang dengan salah ketik papan ketik        harus digabung
           4  2 pasang dengan email SAMA, orang berbeda      TIDAK boleh digabung
           6  3 pasang orang sama, kontak atau nama berubah
                                                             harus digabung dan konfliknya ditandai
     10  5% pasang yang sengaja dibuat ambigu
           nama + dob + city sama, semua kolom kontak berbeda.
           Orangnya berbeda: TIDAK boleh digabung dan perlu dapat ditinjau.

Label acuan
    `device_id(s)` menyimpan kunci jawaban: device id yang sama berarti orang
    nyata yang sama. Setiap kategori "orang berbeda" mendapat device id
    tersendiri, sehingga penggabungan mereka terukur sebagai salah gabung,
    bukan sekadar penilaian subjektif.

    Setiap duplikat yang dibuat hanya boleh memiliki dua baris dengan device id
    yang sama. Dengan demikian berkas dapat memeriksa dirinya sendiri: jika
    jumlah pasangan dengan device yang sama melebihi duplikat yang ditanam,
    generator bermasalah dan hasil proses tidak boleh dinilai.

Berkas keluaran
    data/raw/synthetic_200.csv         batch yang dibaca pipeline
    data/raw/synthetic_200_truth.csv   kategori + device per baris untuk penilaian

Keduanya disimpan di data/raw/ TANPA didaftarkan, sehingga dataset asli di
data/processed/ tidak berubah sampai seseorang sengaja menjalankan unggahan.

Jalankan:  python notebooks/make_synthetic_batch.py
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEST = PROJECT_ROOT / "data" / "raw" / "synthetic_200.csv"
TRUTH = PROJECT_ROOT / "data" / "raw" / "synthetic_200_truth.csv"
# Opsional: baris yang disalin persis dari berkas pengembangan asli. Jika berkas
# tidak ditemukan, kategori ini dilewati dan proses tetap berjalan.
REAL_RAW = PROJECT_ROOT / "data" / "raw" / "crm_50000_customers_dirty_v3.csv"

SEED = 20260905
UNIQUE = 150
# Tiap pasangan terdiri atas dua baris.
OLD_DATA_PAIRS = 5
MISSING_ROWS = 10
DUP_EXACT_PAIRS = 2
DUP_TYPO_PAIRS = 3
EMAIL_SHARE_PAIRS = 2
CONFLICT_PAIRS = 2
CONFLICT_MAIDEN = 1
AMBIGUOUS_PAIRS = 5
TOTAL = UNIQUE + OLD_DATA_PAIRS * 2 + MISSING_ROWS + (
    (DUP_EXACT_PAIRS + DUP_TYPO_PAIRS + EMAIL_SHARE_PAIRS + CONFLICT_PAIRS + CONFLICT_MAIDEN) * 2
) + AMBIGUOUS_PAIRS * 2

# Nama sengaja dipilih agar tidak umum. Dengan begitu, tabrakan blocking yang
# tidak disengaja menunjukkan kemiripan nyata, bukan dua nama keluarga umum
# dengan tiga huruf awal yang sama.
FIRST_NAMES = [
    "Balthazar", "Clementine", "Dieter", "Esperanza", "Fyodor", "Genoveva",
    "Halvard", "Isolde", "Joachim", "Katarzyna", "Leopoldo", "Marguerite",
    "Nikodemus", "Ottilie", "Percival", "Quirin", "Rosamunde", "Salvatore",
    "Theodora", "Ulrich", "Valentine", "Wilhelmina", "Xanthe", "Yolande",
    "Zsigmond", "Anneliese", "Bertrand", "Cordelia", "Dagmar", "Emerald",
]
LAST_NAMES = [
    "Achterberg", "Bellweather", "Castellanos", "Duxbury", "Ellingsworth",
    "Fairweather", "Gottfriedsen", "Hallowell", "Ivanovna", "Jorgensen",
    "Kirchhoff", "Lindqvist", "Montgomery", "Nordstrom", "Ostrowski",
    "Pendleton", "Quarles", "Ravensworth", "Sinclair", "Thackeray",
    "Underwood", "Vandermeer", "Wexford", "Yarborough", "Ziegenfuss",
]
CITIES = [
    ("Norwich", "East Anglia"), ("Ghent", "Flanders"), ("Trieste", "Friuli"),
    ("Kumasi", "Ashanti"), ("Tarragona", "Catalonia"), ("Ushuaia", "Tierra del Fuego"),
    ("Windhoek", "Khomas"), ("Kanazawa", "Hokuriku"), ("Valparaiso", "Valparaiso"),
    ("Salerno", "Campania"),
]
STREETS = ["Kerkstraat", "Rue Lafayette", "Via Roma", "High Street", "Nørregade"]
EMAIL_DOMAINS = ["protonmail.com", "yandex.com", "gmx.net", "zoho.com"]
SOURCES = ["branch_form", "call_center", "mobile_app", "partner_api"]

# Angka yang tercetak pada tombol yang sama saat Shift tidak ditekan. Kunci
# blocking prefiks dirancang agar tetap menemukan catatan dengan salah ketik ini.
KEYBOARD_TYPO = {"o": "5", "i": "1", "s": "5", "n": "8", "l": "1", "e": "3", "a": "4"}


def typo_word(text: str, rng: random.Random) -> str:
    """Ganti satu huruf dengan angka pada tombol yang sama.

    Jika tidak ada huruf yang cocok, tambahkan akhiran agar selalu ada salah
    ketik yang diterapkan.
    """
    spots = [i for i, ch in enumerate(text) if ch.lower() in KEYBOARD_TYPO]
    if not spots:
        return text + rng.choice("qxzv")
    i = rng.choice(spots)
    return text[:i] + KEYBOARD_TYPO[text[i].lower()] + text[i + 1:]


def build() -> pd.DataFrame:
    rng = random.Random(SEED)
    used_email: set[str] = set()
    used_phone: set[str] = set()
    rows: list[dict] = []

    def new_email(first: str, last: str) -> str:
        for _ in range(500):
            candidate = f"{first}.{last}{rng.randrange(1000, 9999)}@{rng.choice(EMAIL_DOMAINS)}"
            if candidate not in used_email:
                used_email.add(candidate)
                return candidate
        raise RuntimeError("email space exhausted; widen EMAIL_DOMAINS or the name pool")

    def new_phone() -> str:
        for _ in range(500):
            candidate = "9" + "".join(str(rng.randrange(10)) for _ in range(10))
            if candidate not in used_phone:
                used_phone.add(candidate)
                return candidate
        raise RuntimeError("phone space exhausted")

    # Satu penghitung dinaikkan tepat sekali per baris. Membuat ID dari len(rows)
    # akan menghasilkan tabrakan jika dua baris dibuat sebelum salah satunya
    # ditambahkan.
    serial = {"n": 0}

    def next_id() -> int:
        serial["n"] += 1
        return serial["n"]

    def fresh_device(prefix: str) -> str:
        return f"dev_{prefix}{next_id():04d}"

    def fresh_customer_id() -> str:
        return f"SYN{next_id():05d}"

    def base_row(device: str, note: str) -> dict:
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        city, state = rng.choice(CITIES)
        return {
            "customer_id": fresh_customer_id(),
            "first_name": first,
            "last_name": last,
            "email": new_email(first.lower(), last.lower()),
            "phone_number": new_phone(),
            "gender": rng.choice(["M", "F", "X"]),
            "dob": f"{rng.randrange(1, 29):02d}/{rng.randrange(1, 13):02d}/{rng.randrange(1948, 2007)}",
            "signup_date": f"{rng.randrange(1, 28):02d}/{rng.randrange(1, 13):02d}/{rng.randrange(2016, 2026)}",
            "address": f"{rng.randrange(1, 900)} {rng.choice(STREETS)}",
            "city": city,
            "state": state,
            "country": "International",
            "device_id(s)": device,
            "source": rng.choice(SOURCES),
            "_truth_note": note,
        }

    def clone(src: dict, device: str, note: str, mutate=None) -> dict:
        row = dict(src)
        row["customer_id"] = fresh_customer_id()
        row["device_id(s)"] = device
        row["_truth_note"] = note
        if mutate:
            mutate(row)
        return row

    # ---- 150 pelanggan unik tanpa kerusakan
    for _ in range(UNIQUE):
        rows.append(base_row(fresh_device("uni"), "unique"))

    # ---- 10 baris (5%) dari berkas asli: 5 pasang, asli + salah ketik.
    # Satu catatan asli per pasangan; device id memang sama.
    planted_old = 0
    if REAL_RAW.exists():
        real = pd.read_csv(REAL_RAW, sep=";", low_memory=False)
        real = real.drop_duplicates(subset=["customer_id"]).reset_index(drop=True)
        keep = ("first_name", "last_name", "email", "phone_number", "gender", "dob",
                "signup_date", "address", "city", "state", "country", "device_id(s)", "source")
        for _, src in real.sample(n=OLD_DATA_PAIRS, random_state=SEED).iterrows():
            original = {c: src[c] for c in keep if c in real.columns}
            original["customer_id"] = fresh_customer_id()
            original["_truth_note"] = "carried-over-original"
            rows.append(original)
            rows.append(clone(original, src["device_id(s)"], "carried-over-typo",
                              lambda r: r.__setitem__("first_name",
                                                      typo_word(str(r["first_name"]), rng))))
            planted_old += 1
    if not planted_old:
        print(f"CATATAN: {REAL_RAW.name} tidak ditemukan; kategori dari berkas asli dilewati.")

    # ---- 10 baris (5%) dengan nilai kosong.
    # Tiga baris kehilangan email DAN telepon: tidak ada kunci kontak yang dapat
    # menjadikannya pasangan kandidat.
    missing_specs = [
        ("missing-email", ("email",)),
        ("missing-email", ("email",)),
        ("missing-phone", ("phone_number",)),
        ("missing-phone", ("phone_number",)),
        ("missing-all-contact", ("email", "phone_number")),
        ("missing-all-contact", ("email", "phone_number")),
        ("missing-dob", ("dob",)),
        ("missing-address", ("address",)),
        ("missing-city-state", ("city", "state")),
        ("missing-all-contact", ("email", "phone_number")),
    ]
    for note, blanks in missing_specs:
        row = base_row(fresh_device("mis"), note)
        for column in blanks:
            row[column] = None
        rows.append(row)

    # ---- 20 baris (10%) duplikat. Setiap pasangan berbagi SATU device id.
    def mut_exact(row: dict) -> None:
        pass

    def mut_typo(row: dict) -> None:
        row["first_name"] = typo_word(row["first_name"], rng)

    def mut_contact(row: dict) -> None:
        row["phone_number"] = new_phone()
        row["address"] = f"{rng.randrange(1, 900)} {rng.choice(STREETS)}"

    def mut_maiden_name(row: dict) -> None:
        row["first_name"] = rng.choice(FIRST_NAMES)
        row["email"] = new_email(row["first_name"].lower(), row["last_name"].lower())

    dup_plan = (
        [("duplicate-exact", mut_exact)] * DUP_EXACT_PAIRS
        + [("duplicate-typo", mut_typo)] * DUP_TYPO_PAIRS
        + [("duplicate-contact-changed", mut_contact)] * CONFLICT_PAIRS
        + [("duplicate-maiden-name", mut_maiden_name)] * CONFLICT_MAIDEN
    )
    for note, mutate in dup_plan:
        device = fresh_device("dup")
        rows.append(base_row(device, f"{note}-a"))
        rows.append(clone(rows[-1], device, f"{note}-b", mutate))

    # ---- 4 baris: email SAMA, orang BERBEDA, device id berbeda.
    # Menggabungkannya adalah salah gabung yang terukur, bukan perkara pendapat.
    for _ in range(EMAIL_SHARE_PAIRS):
        shared_email = new_email("household", "shared")
        person_a = base_row(fresh_device("shr"), "email-shared-a")
        person_b = base_row(fresh_device("shr"), "email-shared-b")
        person_a["email"] = person_b["email"] = shared_email
        rows.append(person_a)
        rows.append(person_b)

    # ---- 10 baris (5%) sengaja dibuat ambigu: nama + dob + city sama, tetapi
    # semua kolom kontak berbeda. Device id berbeda: keduanya tidak boleh digabung.
    for _ in range(AMBIGUOUS_PAIRS):
        person_a = base_row(fresh_device("amb"), "ambiguous-a")
        person_b = base_row(fresh_device("amb"), "ambiguous-b")
        for column in ("first_name", "last_name", "dob", "city", "state"):
            person_b[column] = person_a[column]
        rows.append(person_a)
        rows.append(person_b)

    return pd.DataFrame(rows)


def main() -> None:
    frame = build()

    if len(frame) != TOTAL:
        raise SystemExit(f"generator built {len(frame)} rows, expected {TOTAL}")
    if len(set(frame["customer_id"])) != len(frame):
        raise SystemExit("customer_id collision: the serial counter is wrong")

    counts = frame["_truth_note"].str.replace(r"-[ab]$", "", regex=True).value_counts()
    shared_devices = frame["device_id(s)"].value_counts()
    planted_pairs = int((shared_devices > 1).sum())
    dup_pairs = DUP_EXACT_PAIRS + DUP_TYPO_PAIRS + CONFLICT_PAIRS + CONFLICT_MAIDEN
    carried = int(counts.get("carried-over-original", 0))

    if planted_pairs != dup_pairs + carried:
        raise SystemExit(
            f"answer key is inconsistent: {planted_pairs} device ids are shared but "
            f"{dup_pairs + carried} duplicate pairs were planted. Do not score this file."
        )

    DEST.parent.mkdir(parents=True, exist_ok=True)
    frame[["customer_id", "device_id(s)", "_truth_note"]].to_csv(TRUTH, index=False)
    frame.drop(columns=["_truth_note"]).to_csv(DEST, sep=";", index=False, encoding="utf-8")

    print(f"Wrote {len(frame)} rows -> {DEST}")
    print(f"Answer key         -> {TRUTH}")
    print()
    print(f"distinct device ids: {frame['device_id(s)'].nunique()}")
    print(f"device ids on 2+ rows: {planted_pairs} (duplicates planted: {dup_pairs})")
    print(f"pairs that must merge: {planted_pairs}")
    print()
    print("composition:")
    print(counts.to_string())
    print()
    print("Not registered: run an upload in the app, or seed the registry with")
    print(f"  python -m src.registry --seed {DEST.name}")


if __name__ == "__main__":
    main()
