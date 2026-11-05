"""Entity clustering: MATCH pairs → entity_id mapping."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import networkx as nx
from src.db import get_connection
from psycopg2.extras import execute_values


def cluster_matches(predictions_df: pd.DataFrame, all_record_ids=None, max_cluster_size: int = 5):
    """Buat cluster tervalidasi; cluster mencurigakan masuk review, bukan merge permanen."""
    matches = predictions_df[predictions_df['decision'] == 'MATCH'].copy()
    G = nx.Graph()
    if all_record_ids is not None:
        G.add_nodes_from(all_record_ids)
    for _, row in matches.iterrows():
        G.add_edge(row['record_id_l'], row['record_id_r'])

    components = list(nx.connected_components(G))
    entity_map, reviews = [], []
    entity_no = 1
    for component in components:
        members = sorted(component)
        internal = predictions_df[
            predictions_df['record_id_l'].isin(members)
            & predictions_df['record_id_r'].isin(members)
        ]
        contradictions = int((internal['decision'] == 'NON_MATCH').sum())
        suspicious = len(members) > max_cluster_size or contradictions > 0
        if suspicious and len(members) > 1:
            reviews.append({'cluster_key': f"cluster_{entity_no:06d}",
                            'record_ids': members, 'reason':
                            f"size={len(members)}, contradictions={contradictions}"})
            for record_id in members:
                entity_map.append({'record_id': record_id, 'entity_id': f"ent_{record_id}", 'cluster_status': 'REVIEW'})
        else:
            entity_id = f"ent_{entity_no:06d}"
            status = 'MATCHED' if len(members) > 1 else 'SINGLETON'
            for record_id in members:
                entity_map.append({'record_id': record_id, 'entity_id': entity_id, 'cluster_status': status})
        entity_no += 1

    return pd.DataFrame(entity_map), pd.DataFrame(reviews)



def add_singleton_entities(entity_map_df: pd.DataFrame, all_record_ids: list):
    """Tambah singleton entity untuk record yang belum punya entity_id."""
    mapped = set(entity_map_df['record_id'])
    unmapped = [r for r in all_record_ids if r not in mapped]
    if not unmapped:
        # Semua sudah punya entity_id dari cluster_matches.
        # Tandai yang bukan dari MATCH sebagai SINGLETON.
        entity_map_df['cluster_status'] = entity_map_df['cluster_status'].fillna('SINGLETON')
        return entity_map_df
    singleton = pd.DataFrame([
        {'record_id': r, 'entity_id': f"ent_{r}", 'cluster_status': 'SINGLETON'}
        for r in unmapped
    ])
    return pd.concat([entity_map_df, singleton], ignore_index=True)


def save_entity_map_to_db(entity_map_df: pd.DataFrame):
    """Save entity_map ke database dengan UPSERT, bukan TRUNCATE."""
    if len(entity_map_df) == 0:
        print("No entity mappings to save")
        return
    
    records = entity_map_df[['record_id', 'entity_id', 'cluster_status']].values.tolist()
    print(f"Saving {len(records)} entity mappings to splink_data.entity_map (UPSERT)...")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            execute_values(cursor, """
                INSERT INTO splink_data.entity_map (record_id, entity_id)
                VALUES %s
                ON CONFLICT (record_id) DO UPDATE SET entity_id = EXCLUDED.entity_id
            """, [(r[0], r[1]) for r in records])
            conn.commit()
    print(f"[OK] Saved {len(records)} entity mappings")


def main():
    print("=" * 60)
    print("Entity Clustering")
    print("=" * 60)
    
    # Load predictions
    pred_path = PROJECT_ROOT / "outputs" / "splink_predictions.parquet"
    if not pred_path.exists():
        print(f"ERROR: {pred_path} not found")
        return
    
    predictions = pd.read_parquet(pred_path)
    print(f"Loaded {len(predictions)} predictions")
    
    standardized = pd.read_parquet(PROJECT_ROOT / "data" / "processed" / "crm_standardized.parquet")
    all_record_ids = standardized['record_id'].tolist()
    entity_map, reviews = cluster_matches(predictions, all_record_ids)
    entity_map = add_singleton_entities(entity_map, all_record_ids)
    print(f"Created {entity_map['entity_id'].nunique()} entities from {len(entity_map)} records")
    print(f"Clusters requiring review: {len(reviews)}")
    print(f"Singleton entities added: {len(entity_map) - len(standardized) + entity_map[entity_map['cluster_status'] != 'SINGLETON'].shape[0]}")

    save_entity_map_to_db(entity_map)
    backup_path = PROJECT_ROOT / "outputs" / "entity_map.parquet"
    entity_map.to_parquet(backup_path, index=False)
    reviews.to_parquet(PROJECT_ROOT / "outputs" / "cluster_review.parquet", index=False)
    print(f"[OK] Backup saved: {backup_path}")
    
    print("\n" + "=" * 60)
    print(f"Clustering complete: {len(entity_map['entity_id'].unique())} entities")
    print("=" * 60)


if __name__ == "__main__":
    main()
