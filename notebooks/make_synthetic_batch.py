"""Generate a synthetic CRM batch whose correct answers are known in advance.

Why this exists
    The 51,555-row development file cannot answer "did it catch the typo, or did
    it wrongly merge two people who share an email", because no file records
    which rows are supposed to be the same person. `device_id(s)` is 1:1 with
    customer_id there, so the existing evaluation can only prove the pipeline
    reproduces the source grouping — never that it is right.

    This file is the answer key. Every category is planted on purpose, so the
    run can be scored instead of eyeballed.

Composition (200 rows)
    150  unique, clean customers                  baseline
     10  5%  rows carried over from the real file   5 pairs: original + typo copy
     10  5%  rows with missing values              incl. 3 with no contact at all
     20 10%  duplicates
           4  2 pairs  identical in every field        must merge
           6  3 pairs  one field with a keyboard typo  must merge
           4  2 pairs  SAME email, two different people must NOT merge
           6  3 pairs  same person, contact or name changed
                                                      must merge, and flag a conflict
     10  5%  deliberately ambiguous pairs
           same name + dob + city, every contact field different.
           Two different people: must NOT merge, and should be reviewable.

Ground truth
    `device_id(s)` carries the answer key: the same device id means the same real
    person. Every "these are different people" category gets its OWN device id,
    so a merge between them is a measured false merge rather than an opinion.

    Exactly two rows may share a device id per planted duplicate, so the file is
    self-checking: if more pairs share a device than were planted, the generator
    is broken and the run must not be scored.

Writes
    data/raw/synthetic_200.csv         the batch the pipeline reads
    data/raw/synthetic_200_truth.csv   category + device per row, for scoring

Both land in data/raw/ WITHOUT being registered, so the real dataset in
data/processed/ is untouched until someone runs an upload on purpose.

Run:  python notebooks/make_synthetic_batch.py
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEST = PROJECT_ROOT / "data" / "raw" / "synthetic_200.csv"
TRUTH = PROJECT_ROOT / "data" / "raw" / "synthetic_200_truth.csv"
# Optional: rows copied verbatim out of the real development file. Missing file
# simply drops that category instead of failing the run.
REAL_RAW = PROJECT_ROOT / "data" / "raw" / "crm_50000_customers_dirty_v3.csv"

SEED = 20260905
UNIQUE = 150
OLD_DATA_PAIRS = 5          # x2 rows = 10  (5%)
MISSING_ROWS = 10            #      10      (5%)
DUP_EXACT_PAIRS = 2          # x2 rows = 4
DUP_TYPO_PAIRS = 3           # x2 rows = 6
EMAIL_SHARE_PAIRS = 2        # x2 rows = 4
CONFLICT_PAIRS = 2           # x2 rows = 4   (contact changed)
CONFLICT_MAIDEN = 1          # x2 rows = 2   (first name changed)
AMBIGUOUS_PAIRS = 5          # x2 rows = 10   (5%)
TOTAL = UNIQUE + OLD_DATA_PAIRS * 2 + MISSING_ROWS + (
    (DUP_EXACT_PAIRS + DUP_TYPO_PAIRS + EMAIL_SHARE_PAIRS + CONFLICT_PAIRS + CONFLICT_MAIDEN) * 2
) + AMBIGUOUS_PAIRS * 2

# Names are deliberately uncommon, so an accidental block collision means a real
# near-duplicate and not two common surnames sharing three letters.
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

# Digit for the letter on the same key with Shift released. This is the failure
# mode the prefix blocking keys exist to survive.
KEYBOARD_TYPO = {"o": "5", "i": "1", "s": "5", "n": "8", "l": "1", "e": "3", "a": "4"}


def typo_word(text: str, rng: random.Random) -> str:
    """Replace one letter with the digit typed on its key. Falls back to a
    suffix when the word contains none of them, so a typo is always applied."""
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

    # One counter, advanced exactly once per row. Deriving ids from len(rows)
    # collides whenever two rows are built before either is appended.
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

    # ---- 150 unique, clean customers
    for _ in range(UNIQUE):
        rows.append(base_row(fresh_device("uni"), "unique"))

    # ---- 10 rows (5%) carried over from the real file: 5 pairs, original + typo.
    # One real record per pair, so the device id is genuinely shared.
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
        print(f"NOTE: {REAL_RAW.name} not found, skipping the carried-over category.")

    # ---- 10 rows (5%) with missing values.
    # 3 lose BOTH email and phone: no contact key can ever reach them.
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

    # ---- 20 rows (10%) duplicates. Each pair shares ONE device id.
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

    # ---- 4 rows: SAME email, two DIFFERENT people, two device ids.
    # Merging these would be a real false merge, not a judgement call.
    for _ in range(EMAIL_SHARE_PAIRS):
        shared_email = new_email("household", "shared")
        person_a = base_row(fresh_device("shr"), "email-shared-a")
        person_b = base_row(fresh_device("shr"), "email-shared-b")
        person_a["email"] = person_b["email"] = shared_email
        rows.append(person_a)
        rows.append(person_b)

    # ---- 10 rows (5%) deliberately ambiguous: same name + dob + city, every
    # contact field different. Two device ids: they must not merge.
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
