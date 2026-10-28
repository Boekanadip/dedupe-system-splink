import pandas as pd
from sklearn.model_selection import train_test_split
from src.splink_model import train_and_predict, load_data

df = load_data(full=False)
gold = pd.read_csv('data/labels/gold_labels.csv')
train_gold, test_gold = train_test_split(gold, test_size=0.2, random_state=42)
print(f'Train gold: {len(train_gold):,} | Test gold: {len(test_gold):,}')

pred_df, linker = train_and_predict(df, verbose=False)

test_ids = set(test_gold['pair_id'])
pred_test = pred_df[pred_df['pair_id'].isin(test_ids)]

total_pos = len(test_gold[test_gold['is_duplicate']==1])
tp = int(((pred_test['match_probability'] >= 0.9) & (pred_test['decision'] == 'MATCH')).sum()) if not pred_test.empty else 0
fn = int((pred_test['match_probability'] < 0.9).sum()) if not pred_test.empty else 0

recall = tp / total_pos if total_pos > 0 else 0
print(f'Total positive in test: {total_pos}')
print(f'TP @ 0.9: {tp}')
print(f'FN @ 0.9: {fn}')
print(f'Recall @ 0.9: {recall:.4f}')