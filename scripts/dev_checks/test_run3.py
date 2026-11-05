import warnings
warnings.filterwarnings('ignore')
import pandas as pd
from src.splink_model import build_dynamic_settings_from_columns, train_and_predict, _validate_fully_trained

df = pd.read_parquet('data/synthetic_review.parquet').head(500)
print(f"Records: {len(df)}")

# Test with minimal columns that previously worked
COLS = ['first_name_std','last_name_std','email_std','phone_std']
print(f"\nTest with {len(COLS)} columns")

settings = build_dynamic_settings_from_columns(COLS)
print(f"Comparisons: {len(settings['comparisons'])}, Blocking: {len(settings['blocking_rules'])}")

try:
    pred, linker = train_and_predict(df, selected_columns=COLS, max_pairs=50000)
    print(f"SUCCESS: Candidates={len(pred)}, Decisions={pred['decision'].value_counts().to_dict()}")
    print(f"Review band: {int(((pred['match_probability']>=0.35)&(pred['match_probability']<0.84)).sum())}")
    
    # Check Bayes factor
    print("\nBayes factor per level:")
    settings_dict = linker._settings_obj.as_dict()
    for c in settings_dict['comparisons']:
        print(f"\nComparison: {c['output_column_name']}")
        for lv in c['comparison_levels']:
            m = lv.get('m_probability')
            u = lv.get('u_probability')
            bf = m/u if m and u and u != 0 else None
            label = lv.get('label_for_charts', '')
            print(f'  {label}: m={m}, u={u}, BF={bf}')
    
    # Check _validate_fully_trained
    print("\n_validated_fully_trained check:")
    try:
        _validate_fully_trained(linker)
        print("  No error - all parameters trained")
    except RuntimeError as e:
        print(f"  RuntimeError: {str(e)[:100]}")
        
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {str(e)[:200]}")