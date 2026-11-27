import urllib.request
import json
import time

PROXY_URL = 'http://localhost:5174'

def test_endpoint(name, path, method='GET', body=None):
    url = f"{PROXY_URL}{path}"
    headers = {'Content-Type': 'application/json'}
    data = json.dumps(body).encode('utf-8') if body else None
    t0 = time.time()
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            elapsed = (time.time() - t0) * 1000
            if path == '/api/download':
                chunk = resp.read(2048)
                return {'endpoint': name, 'path': path, 'status': resp.status, 'ms': round(elapsed, 1), 'data': f"Stream chunk read: {len(chunk)} bytes"}
            res_body = resp.read()
            parsed = json.loads(res_body) if resp.headers.get_content_type() == 'application/json' else f"{len(res_body)} bytes"
            return {'endpoint': name, 'path': path, 'status': resp.status, 'ms': round(elapsed, 1), 'data': parsed}
    except Exception as e:
        return {'endpoint': name, 'path': path, 'error': str(e)}

print("\n=== 1. SIMULASI STREAM POLLING DASHBOARD (INTERVAL SEPERTI USER DI BROWSER) ===")
for cycle in range(1, 4):
    t_start = time.time()
    stats = test_endpoint('Dashboard Live Stats', '/api/stats')
    model = test_endpoint('Model Info', '/api/model/info')
    duration = (time.time() - t_start) * 1000
    if 'error' in stats:
        print(f"[Cycle {cycle}] ERROR: {stats['error']}")
    else:
        st = stats['data']
        print(f"[Cycle {cycle}] Stream Sync OK ({duration:.1f}ms): Total Pairs={st.get('total_pairs')}, Matches={st.get('matches')}, Review={st.get('review')}, Non-matches={st.get('non_matches')}, AvgProb={round(st.get('avg_probability',0), 4)}")
    time.sleep(1)

print("\n=== 2. TEST ENDPOINT DASHBOARD DARI PERSPEKTIF PENGGUNA ===")
tests = [
    ('Overview: Health Status', '/health'),
    ('Overview: Live Stats', '/api/stats'),
    ('Overview: Model Info & Lifecycle', '/api/model/info'),
    ('Review Queue: Review Pairs (status=REVIEW)', '/api/pairs?page=1&per_page=3&status=REVIEW'),
    ('Review Queue: Matches (status=MATCH)', '/api/pairs?page=1&per_page=3&status=MATCH'),
    ('Datasets Management: Dataset Registry', '/api/datasets'),
    ('Audit & Review: Summary Metrics', '/api/reviews/summary'),
    ('Analytics: Activity Trend (7 days)', '/api/activity/trend?days=7'),
    ('Analytics: Activity Feed', '/api/activity'),
    ('Workspace Settings: Configuration', '/api/settings/workspace'),
    ('Database Status: Storage Connection', '/api/database/status'),
    ('Export: Streaming CSV Generator', '/api/download')
]

for name, path in tests:
    res = test_endpoint(name, path)
    if 'error' in res:
        print(f"[FAIL] {name} ({path}): {res['error']}")
    else:
        sample = str(res['data'])
        if len(sample) > 95:
            sample = sample[:95] + '...'
        print(f"[PASS] {name} -> HTTP {res['status']} ({res['ms']} ms)")
        print(f"       Payload: {sample}")

pairs_res = test_endpoint('Pairs', '/api/pairs?page=1&per_page=1&status=REVIEW')
if 'data' in pairs_res and isinstance(pairs_res['data'], dict) and pairs_res['data'].get('pairs'):
    p = pairs_res['data']['pairs'][0]
    id1, id2 = p['record_id_l'], p['record_id_r']
    detail = test_endpoint('Review Detail Evidence', f'/api/pair/{id1}/{id2}')
    print(f"\n[PASS] User Click Detail Evidence ({id1} vs {id2}) -> HTTP {detail.get('status')} ({detail.get('ms')} ms)")
    if 'data' in detail and isinstance(detail['data'], dict):
        match_prob = detail['data'].get('prediction', {}).get('match_probability')
        print(f"       Match Probability: {match_prob}, Records Left & Right loaded successfully.")
