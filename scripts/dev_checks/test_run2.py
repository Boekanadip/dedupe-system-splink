import warnings
warnings.filterwarnings('ignore')
import pandas as pd
from src.splink_model import build_dynamic_settings_from_columns, train_and_predict

df = pd.read_parquet('data/synthetic_review.parquet').head(100)

# Test 1: No blocking, minimal columns
print("Test 1: Minimal config, no extra blocking")
settings = build_dynamic_settings_from_columns(['first_name_std','last_name_std','email_std','phone_std'])
print(f"  Comparisons: {len(settings['comparisons'])}, Blocking: {len(settings['blocking_rules'])}")

COLS = ['first_name_std','last_name_std','email_std','phone_std']
try:
    pred, linker = train_and_predict(df, selected_columns=COLS, max_pairs=2000)
    print(f"  SUCCESS: Candidates={len(pred)}, Decisions={pred['decision'].value_counts().to_dict()}")
    print(f"  Review band: {int(((pred['match_probability']>=0.35)&(pred['match_probability']<0.84)).sum())}")
except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {str(e)[:150]}")

# Test 2: With city_std
print("\nTest 2: Adding city_std")
settings2 = build_dynamic_settings_from_columns(['first_name_std','last_name_std','email_std','phone_std','city_std'])
print(f"  Comparisons: {len(settings2['comparisons'])}, Blocking: {len(settings2['blocking_rules'])}")
try:
    pred2, linker2 = train_and_predict(df, selected_columns=['first_name_std','last_name_std','email_std','phone_std','city_std'], max_pairs=2000)
    print(f"  SUCCESS: Candidates={len(pred2)}, Decisions={pred2['decision'].value_counts().to_dict()}")
except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {str(e)[:150]}")

# Test 3: Verify _validate_fully_trained catches empty u_probability
print("\nTest 3: Verify validation catches missing parameters")
from src.splink_model import _validate_fully_trained
try:
    _validate_fully_trained(linker2 if 'linker2' in dir() else linker)
    print("  No error raised (u values are trained)")
except RuntimeError as e:
    print(f"  RuntimeError raised (expected): {str(e)[:100]}")