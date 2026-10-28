"""Flask dashboard for CRM entity resolution."""
from flask import Flask, render_template, jsonify, request
from pathlib import Path
import pandas as pd

app = Flask(__name__)

# Paths
PROJECT_DIR = Path(__file__).parent.parent
PREDICTIONS_PATH = PROJECT_DIR / "outputs" / "splink_predictions.parquet"

# Load predictions
_predictions_df = None

def get_predictions():
    global _predictions_df
    if _predictions_df is None and PREDICTIONS_PATH.exists():
        _predictions_df = pd.read_parquet(PREDICTIONS_PATH)
    return _predictions_df

@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('index.html')

@app.route('/api/stats')
def stats():
    """Get statistics."""
    df = get_predictions()
    if df is None:
        return jsonify({'error': 'No predictions found'})
    
    return jsonify({
        'total_pairs': len(df),
        'matches': int(len(df[df['decision'] == 'MATCH'])),
        'review': int(len(df[df['decision'] == 'REVIEW'])),
        'non_matches': int(len(df[df['decision'] == 'NON_MATCH'])),
        'avg_probability': float(df['match_probability'].mean()),
    })

@app.route('/api/pairs')
def pairs():
    """Get pairs with pagination."""
    df = get_predictions()
    if df is None:
        return jsonify({'error': 'No predictions found'})
    
    status = request.args.get('status')
    if status:
        df = df[df['decision'] == status.upper()]
    
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    start = (page - 1) * per_page
    end = start + per_page
    
    df_page = df.iloc[start:end]
    
    # Include gamma columns for evidence
    result = []
    for _, row in df_page.iterrows():
        result.append({
            'record_id_l': row['record_id_l'],
            'record_id_r': row['record_id_r'],
            'match_probability': float(row['match_probability']),
            'decision': row['decision'],
            'gamma_name': int(row.get('gamma_name', -1)) if pd.notna(row.get('gamma_name')) else -1,
            'gamma_contact': int(row.get('gamma_contact', -1)) if pd.notna(row.get('gamma_contact')) else -1,
            'gamma_location': int(row.get('gamma_location', -1)) if pd.notna(row.get('gamma_location')) else -1,
            'gamma_dob': int(row.get('gamma_dob', -1)) if pd.notna(row.get('gamma_dob')) else -1,
        })
    
    return jsonify({
        'pairs': result,
        'total': len(df),
        'page': page,
        'per_page': per_page
    })

@app.route('/api/pair/<id1>/<id2>')
def pair_detail(id1, id2):
    """Get detail for specific pair."""
    df = get_predictions()
    if df is None:
        return jsonify({'error': 'No predictions found'})
    
    mask = (
        (df['record_id_l'] == id1) & (df['record_id_r'] == id2) |
        (df['record_id_l'] == id2) & (df['record_id_r'] == id1)
    )
    row = df[mask]
    if row.empty:
        return jsonify({'error': 'Pair not found'}), 404
    
    row = row.iloc[0]
    
    # Build full evidence with gamma levels
    evidence = {}
    for field in ['first_name', 'last_name', 'email', 'phone', 'dob', 'address', 'city', 'state', 'country']:
        gamma_col = f'gamma_{field}'
        std_l = f'{field}_std_l'
        std_r = f'{field}_std_r'
        evidence[field] = {
            'value_l': str(row.get(std_l, '')) if pd.notna(row.get(std_l)) else None,
            'value_r': str(row.get(std_r, '')) if pd.notna(row.get(std_r)) else None,
            'gamma': int(row.get(gamma_col, -1)) if pd.notna(row.get(gamma_col)) else -1,
        }
    
    return jsonify({
        'record_id_l': row['record_id_l'],
        'record_id_r': row['record_id_r'],
        'match_probability': float(row['match_probability']),
        'decision': row['decision'],
        'evidence': evidence,
    })

@app.route('/api/search')
def search():
    """Search customer by ID."""
    df = get_predictions()
    if df is None:
        return jsonify({'error': 'No predictions found'})
    
    query = request.args.get('q', '')
    if not query:
        return jsonify({'results': []})
    
    mask = (df['record_id_l'].str.contains(query, na=False)) | (df['record_id_r'].str.contains(query, na=False))
    results = df[mask].head(20)
    
    return jsonify({
        'results': [
            {
                'record_id_l': row['record_id_l'],
                'record_id_r': row['record_id_r'],
                'match_probability': float(row['match_probability']),
                'decision': row['decision']
            }
            for _, row in results.iterrows()
        ]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)