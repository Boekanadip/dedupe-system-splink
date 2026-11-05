import os
import requests
import pandas as pd

print("Testing CRM Entity Resolution System components...")

# Test 1: Environment variables
print("\n1. Testing environment variables:")
try:
    load_dotenv()
    postgres_config = {
        'host': os.environ.get('POSTGRES_HOST', 'localhost'),
        'port': int(os.environ.get('POSTGRES_PORT', 5432)),
        'dbname': os.environ.get('POSTGRES_DB', 'crm'),
        'user': os.environ.get('POSTGRES_USER', 'crm_user'),
        'password': os.environ.get('POSTGRES_PASSWORD', 'crm_password_2026')
    }
    print("  ✓ PostgreSQL configuration loaded")
    print(f"    {os.environ.get('POSTGRES_HOST', 'localhost')}:{os.environ.get('POSTGRES_PORT', '5432')}")
except Exception as e:
    print(f"  ✗ Environment test failed: {e}")

# Test 2: API health check
print("\n2. Testing FastAPI health endpoint:")
try:
    import requests
    response = requests.get("http://localhost:8000/health", timeout=5)
    if response.status_code == 200:
        print("  ✓ API health check: OK")
        print(f"    Response: {response.json()}")
    else:
        print(f"  ✗ API health check failed: {response.status_code}")
except Exception as e:
    print(f"  ✗ API test failed: {e}")

# Test 6: UI dashboard connection
print("\n4. Testing UI dashboard connection:")
try:
    response = requests.get("http://localhost:8501", timeout=5)
    if response.status_code == 200:
        print("  ✓ Streamlit UI is accessible")
    else:
        print(f"  ✗ Streamlit UI not accessible: {response.status_code}")
except Exception as e:
    print(f"  ✗ UI test failed: {e}")

# Test 6: Batch prediction via API
print("\n5. Testing batch prediction API endpoint:")
try:
    files = {'file': ('test.csv', 'test_data', 'text/csv')}
    response = requests.post("http://localhost:8000/api/batch-predict", files=files)
    if response.status_code == 200:
        print("  ✓ Batch prediction API endpoint works")
    else:
        print(f"  ✗ Batch prediction API failed: {response.status_code}")
except Exception as e:
    print(f"  ✗ Batch prediction API test failed: {e}")

print("\n" + "=" * 60)
print("Verification complete!")
print("=" * 60)