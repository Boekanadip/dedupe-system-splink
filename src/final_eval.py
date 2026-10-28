"""Final evaluation: test set terpisah, perbaikan contact + phone standardization."""
import pandas as pd
from sklearn.model_selection import train_test_split
from src.splink_model import train_and_predict, load_data
from src.config import PREDICTIONS_FULL_PATH

df = load_data(full=True)
gold = pd.read_csv('data/labels/gold_labels.csv')

# Split train/test 80/20 (stratified)
gold_train, gold_test = train_test_split(gold, test_size=0.2, stratify=gold['label'], random_state=42)

print(f'Data rows: {len(df):,}')
print(f'Test gold: {len(gold_test):,}')
print(f'Test matches: {(gold_test["label"] == "match").sum():,}')
print()

# Regenerate predictions
pred_df, linker = train_and_predict(df, verbose=True)

# Map pair_id untuk matching
pred_df['pair_id'] = pred_df['record_id_l'].astype(str) + '_' + pred_df['record_id_r'].astype(str)
label_map = dict(zip(gold_test['pair_id'], gold_test['label']))

pred_test = pred_df[pred_df['pair_id'].isin(gold_test['pair_id'])].copy()
pred_test['gold_label'] = pred_test['pair_id'].map(label_map)

# Evaluasi berbagai threshold
thresholds = [0.75, 0.80, 0.85, 0.90, 0.95]
for thr in thresholds:
    tp = int(((pred_test['match_probability'] >= thr) & (pred_test['gold_label'] == 'match')).sum())
    fn = int(((pred_test['match_probability'] < thr) & (pred_test['gold_label'] == 'match')).sum())
    fp = int(((pred_test['match_probability'] >= thr) & (pred_test['gold_label'] != 'match')).sum())
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    print(f'Threshold {thr}:')
    print(f'  TP={tp}, FN={fn}, FP={fp}')
    print(f'  Recall={recall:.4f}, Precision={precision:.4f}')
    print()

# Simpan predictions
pred_test.to_parquet(PREDICTIONS_FULL_PATH, index=False)
print(f'Saved predictions to {PREDICTIONS_FULL_PATH}')