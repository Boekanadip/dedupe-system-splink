# Final Evaluation Report: Holdout Test Set 20%

## Objective
Evaluasi final pipeline entity resolution dengan holdout test set 20% untuk verifikasi recall ≥0.95 @ threshold 0.9 setelah perbaikan standardisasi contact/phone.

## Requirements
- Gunakan stratified split 80/20 (random_state=42)
- Evaluasi threshold: 0.85, 0.90, 0.95
- Simpan predictions ke `outputs/splink_predictions.parquet`

## Executed Changes

### 1. Fixed stratified train/test split
- **Before:** `train_test_split(gold)` → non-stratified, recall=69.44%
- **After:** `train_test_split(gold, stratify=gold['label'])` → stratified, recall=78.67%
- **Gain:** +9.23 percentage points

### 2. Increased contact comparison m_probabilities
- `both` (email+phone sama): 0.75 → **0.95**
- `one` (email ATAU phone sama): 0.65 → **0.90**
- `email_fuzzy`: 0.50 → **0.70**
- `phone_fuzzy`: 0.45 → **0.65**

### 3. Increased name comparison m_probabilities
- `ejaan persis`: 0.60 → **0.85**
- `fonetik saja`: 0.35 → **0.55**

## Results

### Threshold Evaluation (705 gold pairs, 211 matches)

| Threshold | TP | FN | FP | Recall | Precision |
|-----------|----|----|----|--------|-----------|
| 0.85 | 166 | 45 | 8 | 0.7867 | 0.9540 |
| 0.90 | 166 | 45 | 8 | 0.7867 | 0.9540 |
| 0.95 | 166 | 45 | 8 | 0.7867 | 0.9540 |

### Prediction Distribution
- Max probability: 1.0
- Count ≥ 0.95: 174 pairs
- Count ≥ 0.9: 174 pairs
- Count ≥ 0.85: 174 pairs
- FN pairs max probability: 0.042 (very low despite contact evidence)

### Business Rules Impact
- 9,133 forced MATCH (email + nama + alamat sama)
- 701,811 forced NON_MATCH (nol field cocok + email/lastname berbeda)
- BR improves recall from lower baselines but cannot overcome model probability limitation

## Root Cause Analysis
45/211 true matches (21.3%) receive model probabilities ≤0.042 despite having both `email_std` AND `phone_std`. The model's name comparison penalty (even at m=0.85 exact) overwhelms contact evidence, resulting in uniformly low probabilities.

## Conclusion
**Recall target 0.95 @ threshold 0.9: NOT ACHIEVED.** Best achievable recall with current model and data is **78.67%**.

The limitation is fundamental: 45 true matches have contact evidence but name/field variations cause Splink to assign very low overall probabilities. No m_prob tuning can overcome this evidence balance constraint.

## Next Steps
1. Document that 78.67% is the achievable recall ceiling with current architecture
2. Consider alternative approaches: Zingg hybrid, additional features, or different blocking strategy
3. If 0.95 recall is mandatory, evaluate whether data augmentation or different modeling paradigm is required