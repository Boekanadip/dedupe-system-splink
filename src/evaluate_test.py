import pandas as pd
from sklearn.model_selection import train_test_split
from src.splink_model import train_and_predict, load_data

df = load_data(full=True)
gold = pd.read_csv('data/labels/gold_labels.csv')
print('Data rows:', len(df))
print('Gold rows:', len(gold))

# Split gold: 80% train (untuk kalibrasi jika diperlukan), 20% test
_, test_gold = train_test_split(gold, test_size=0.2, random_state=42)
print('Test gold:', len(test_gold))

pred_df, linker = train_and_predict(df, verbose=True)

test_ids = set(test_gold['pair_id'])
pred_df['pair_id'] = pred_df['record_id_l'].astype(str) + '_' + pred_df['record_id_r'].astype(str)

pred_test = pred_df[pred_df['pair_id'].isin(test_ids)]
label_map = dict(zip(test_gold['pair_id'], test_gold['label']))
pred_test = pred_test.copy()
pred_test['gold_label'] = pred_test['pair_id'].map(label_map)

total_pos = int((pred_test['gold_label'] == 'match').sum())
tp = int(((pred_test['match_probability'] >= 0.9) & (pred_test['gold_label'] == 'match')).sum())
fn = int(((pred_test['match_probability'] < 0.9) & (pred_test['gold_label'] == 'match')).sum())
fp = int(((pred_test['match_probability'] >= 0.9) & (pred_test['gold_label'] != 'match')).sum())

recall = tp / total_pos if total_pos > 0 else 0
precision = tp / (tp + fp) if (tp + fp) > 0 else 0

print(f'Total positive (match) in test: {total_pos}')
print(f'TP @ 0.9: {tp}')
print(f'FN @ 0.9: {fn}')
print(f'FP @ 0.9: {fp}')
print(f'Recall @ 0.9: {recall:.4f}')
print(f'Precision @ 0.9: {precision:.4f}')
print(f'Test pairs evaluated: {len(pred_test)}')