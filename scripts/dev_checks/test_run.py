import warnings
warnings.filterwarnings('ignore')
import pandas as pd
from src.splink_model import train_and_predict

df = pd.read_parquet('data/synthetic_review.parquet').head(100)
COLS = ['first_name_std','last_name_std','email_std','phone_std']

try:
    pred, linker = train_and_predict(df, selected_columns=COLS, max_pairs=50000)
    print('Training succeeded!')
    print('Candidates:', len(pred))
    print('Decisions:', pred['decision'].value_counts().to_dict())
    print('Review band:', int(((pred['match_probability']>=0.35)&(pred['match_probability']<0.84)).sum()))
    # Check Bayes factor
    settings = linker._settings_obj.as_dict()
    print("\nBayes factor per level:")
    for c in settings['comparisons']:
        print(f"\nComparison: {c['output_column_name']}")
        for lv in c['comparison_levels']:
            m = lv.get('m_probability')
            label = lv.get('label_for_charts', '')
            print(f'  {label}: m={m}')
except Exception as e:
    print(f'Training failed: {type(e).__name__}: {str(e)[:200]}')