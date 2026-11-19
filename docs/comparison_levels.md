# Comparison Levels — m-Probabilities (Splink)

## Contact Field (`contact`)

Three comparison levels with updated m-probabilities:

| Level | Condition | m-probability | Purpose |
|---|---|---|---|
| `email dan telepon` | Both email AND phone standardised & equal | **0.75** (↑ from 0.60) | Strong evidence: agreement on both contact methods |
| `email atau telepon` | Email XOR phone match (one matches) | **0.60** | Moderate evidence: one contact method agrees |
| `email mirip / telepon mirip` | Fuzzy similarity (Jaro-Winkler, Levenshtein) | 0.45 / 0.40 | Typo-tolerant fallbacks |
| Else | No contact agreement | 0.10 | Default |

**Why 0.75 for "email atau telepon"?**
FN analysis shows 12 pairs below threshold 0.9 had contact agreement but low overall score. Raising m from 0.60 → 0.75 increases weight of contact agreement, pulling these pairs above threshold without inflating false matches.

---

## Location Field (`location`) — `build_location_comparison` (fixed, `src/splink_model.py`)

| Level (label) | Kondisi | m-probability |
|---|---|---|
| `lokasi kosong` | address & city kosong di salah satu sisi (null level) | — (null) |
| `alamat lengkap (3 field)` | address + city + state sama | **0.40** |
| `street cocok` | address sama | **0.20** |
| `city cocok` | city sama | **0.25** |
| `state cocok` | state sama | **0.30** |
| `2 dari 3 field cocok` | dua dari {address, city, state} sama | **0.15** |
| Else | tidak ada kecocokan lokasi di atas | **0.10** |

Catatan: level dievaluasi berurutan; nilai m-probability adalah konfigurasi di kode (bukan hasil evaluasi yang diverifikasi di dokumen ini). Mode dinamis (`build_dynamic_settings_from_columns`) memakai struktur/label lokasi berbeda.

---

## DOB Field (`dob`)

| Level | Condition | m-probability | Purpose |
|---|---|---|---|
| `tanggal lahir persis` | DOB matches exactly | **0.30** (↓ from 0.50) | Strong: exact date of birth |
| `tanggal lahir mendekat (year)` | DOB within 1 year (fuzzy) | **0.25** | Moderate: approximate birth year |
| Else | No DOB agreement | **0.12** (unchanged) | Default |

**Why decrease Exact from 0.50 → 0.30?**
FN analysis revealed that 12 pairs below threshold 0.9 had DOB agreement but last_name typo penalty dragging score down. Lowering the exact DOB m-probability from 0.50 → 0.30 reduces the "penalty" effect of DOB mismatch on pairs where DOB *does* match but other fields (name) have typos. The fuzzy level (0.25) is unchanged.

## Gamma Probabilities (Two-Record Agreement)

Gamma values represent the background probability that two random records agree on a field by chance. These are estimated u-probabilities transformed via `m = 1 - u` and `gamma = 1 - m`.

| Comparison | Typical gamma range | Interpretation |
|---|---|---|
| `name` | gamma ≈ 0.7–0.9 | Most random name pairs disagree |
| `contact` | gamma ≈ 0.25–0.75 | Contact agreement is moderately informative |
| `location` | gamma ≈ 0.5–0.8 | Location agreement varies by geographic clustering |
| `dob` | gamma ≈ 0.5–0.7 | DOB agreement is fairly discriminative |