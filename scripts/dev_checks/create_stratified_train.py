import pandas as pd
import numpy as np

def create_stratified_training_df(
    df: pd.DataFrame,
    target_size: int = 5000,
    email_frac: float = 0.3,
    phone_frac: float = 0.2,
    conflict_frac: float = 0.15,
    random_state: int = 42
) -> pd.DataFrame:
    """
    Buat training dataset yang sengaja diformat untuk memiliki:
    - Banyak duplicate pattern (email, phone, email+phone)
    - Banyak kasus konflik nama (email+sama + phone+bisa + nama berbeda)
    - Kurang random non-duplicate, lebih banyak structured pattern
    
    Args:
        df: DataFrame asli (dipotong sesuai need)
        target_size: Ukuran target training set
        email_frac: Fraksi record yang mesti punya duplicate email
        phone_frac: Fraksi record yang mesti punya duplicate phone
        conflict_frac: Fraksi record yang mesti punya conflict pattern
        random_state: Seed untuk reproduksi
    
    Returns:
        DataFrame training set diformat stratified
    """
    np.random.seed(random_state)
    
    # Ambil subset dari data asli (biasanya sudah di-head)
    # Pastikan kita punya cukup duplicate pattern
    df_work = df.copy()
    
    # 1. Ambil duplicate email
    dup_email = df_work[df_work.duplicated('email_std', keep=False)]
    n_dup_email = int(target_size * email_frac)
    n_dup_email = min(n_dup_email, len(dup_email))
    dup_email_sample = dup_email.sample(n=n_dup_email, random_state=random_state)
    
    # 2. Ambil duplicate phone
    dup_phone = df_work[df_work.duplicated('phone_std', keep=False)]
    n_dup_phone = int(target_size * phone_frac)
    n_dup_phone = min(n_dup_phone, len(dup_phone))
    dup_phone_sample = dup_phone.sample(n=n_dup_phone, random_state=random_state)
    
    # 3. Ambil duplicate email+phone dengan conflict nama
    dup_both = df_work[df_work.duplicated(['email_std','phone_std'], keep=False)]
    # Filter untuk grup yang punya name conflict (first/last name berbeda)
    conflict_groups = []
    for g, idx in dup_both.groupby(['email_std','phone_std']).groups.items():
        subset = dup_both.loc[idx]
        n_unique_names = subset[['first_name_std','last_name_std']].drop_duplicates().shape[0]
        if n_unique_names > 1:  # Hanya grup dengan name conflict
            conflict_groups.append(g)
    
    # Ambil sejumlah grup conflict
    n_conflict_groups = int(target_size * conflict_frac)
    # Setiap grup punya 2 record
    n_conflict_records = min(n_conflict_groups * 2, len(dup_both))
    dup_both_sample = dup_both[dup_both.set_index(['email_std','phone_std']).index.isin(
        set(conflict_groups[:n_conflict_groups//2])  # ambil set setengah grup (masing-masing 2 record)
    )].copy()
    
    # Pastikan kita mendapatkan record yang sesuai
    if len(dup_both_sample) < n_conflict_records:
        # Ambil lebih dari grup standar
        dup_both_sample = dup_both.sample(n=n_conflict_records, random_state=random_state)
    
    # 4. Ambil non-duplicate records untuk balance
    # Dapatkan record ID yang sudah digunakan
    used_ids = set(dup_email_sample['record_id']) | set(dup_phone_sample['record_id']) | set(dup_both_sample['record_id'])
    
    # Ambil non-duplicate
    non_dup = df_work[~df_work['record_id'].isin(used_ids)]
    n_non_dup = target_size - len(dup_email_sample) - len(dup_phone_sample) - len(dup_both_sample)
    n_non_dup = max(0, n_non_dup)
    n_non_dup = min(n_non_dup, len(non_dup))
    non_dup_sample = non_dup.sample(n=n_non_dup, random_state=random_state)
    
    # Gabungkan semua
    train_df = pd.concat([
        dup_email_sample,
        dup_phone_sample, 
        dup_both_sample,
        non_dup_sample
    ]).drop_duplicates(subset='record_id')
    
    # Pastikan ukuran target
    if len(train_df) < target_size:
        # Tambah random record dari sisanya
        remaining = df_work[~df_work['record_id'].isin(train_df['record_id'])]
        extra = remaining.sample(n=target_size - len(train_df), random_state=random_state)
        train_df = pd.concat([train_df, extra]).drop_duplicates(subset='record_id')
    
    # Shuffle
    train_df = train_df.sample(frac=1, random_state=random_state).reset_index(drop=True)
    
    # Print summary
    print('=== Stratified Training Dataset Summary ===')
    print(f'Target size: {target_size}')
    print(f'Final size: {len(train_df)}')
    print(f'Duplicate email: {train_df.duplicated(subset="email_std", keep=False).sum()} rows')
    print(f'Duplicate phone: {train_df.duplicated(subset="phone_std", keep=False).sum()} rows')
    print(f'Duplicate email+phone: {train_df.duplicated(subset=["email_std","phone_std"], keep=False).sum()} rows')
    
    # Cek conflict groups
    dup_both_check = train_df[train_df.duplicated(subset=['email_std','phone_std'], keep=False)]
    conflict_count = 0
    if len(dup_both_check) > 0:
        for g, idx in dup_both_check.groupby(['email_std','phone_std']).groups.items():
            subset = dup_both_check.loc[idx]
            n_unique = subset[['first_name_std','last_name_std']].drop_duplicates().shape[0]
            if n_unique > 1:
                conflict_count += 1
    print(f'Groups dengan name conflict (email+sama+phone+sama+nama berbeda): {conflict_count}')
    
    return train_df


# Contoh penggunaan
if __name__ == "__main__":
    # Load data
    df = pd.read_parquet('data/processed/crm_standardized.parquet').head(5000)
    
    # Buat training set stratified
    train_df = create_stratified_training_df(
        df,
        target_size=5000,
        email_frac=0.35,    # 35% = 175 record duplicate email
        phone_frac=0.18,    # 18% = 90 record duplicate phone
        conflict_frac=0.12, # 12% = 60 record dengan name conflict
        random_state=42
    )
    
    print()
    print('=== Sample records ===')
    print(train_df[['record_id','email_std','phone_std','first_name_std','last_name_std']].head(20).to_string(index=False))