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

## Location Field (`location`)

| Level | Condition | m-probability | Purpose |
|---|---|---|---|
| `alamat lengkap (4 field)` | address + city + state all match | **0.40** | Very strong: full address agreement |
| `street cocok` | Street address matches | **0.20** | Strong: street-level agreement |
| `city cocok` | City matches | **0.25** | Moderate: city-level agreement |
| `state cocok` | State matches | **0.30** | Moderate-high: state agreement |
| `3 dari 4 field cocok` | 3 of 4 address fields match | **0.15** | Weak-moderate |
| Else | No location agreement | **0.10** (↓ from 0.15) | Default |

**Why decrease Else from 0.15 → 0.10?**
Lowering the Else m-probability makes the model *more conservative* — pairs with no location agreement receive less default penalty, which indirectly increases overall match weights for pairs that do have partial agreement. This helps recover FN pairs where location is partially agreed but other fields dominate.

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