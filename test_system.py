#!/usr/bin/env python

print("=" * 60)
print("CRM Entity Resolution System - Verification Test")
print("=" * 60)

try:
    # Test 1: Environment
    print("\n1. Testing environment variables:")
    try:
        import os
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        load_dotenv(dotenv_path=env_path)
        print(f"  PostgreSQL: {os.environ.get('POSTGRES_HOST', 'localhost')}:{os.environ.get('POSTGRES_PORT', '5432')}")
        print("  ✓ Environment variables loaded")
    except Exception as e:
        print(f"  ✗ Environment test failed: {e}")

# Test 2: Docker Compose
print("\n2. Testing Docker Compose:")
try:
    import subprocess
    result = subprocess.run(['docker-compose', 'config'], capture_output=True, text=True)
    if result.returncode == 0:
        print("  ✓ docker-compose.yml is valid")
    else:
        print("  ✗ docker-compose.yml invalid")
        print(result.stderr)
except Exception as e:
    print(f"  ✗ Docker test failed: {e}")

# Test 3: FastAPI Health Check
print("\n3. Testing FastAPI health endpoint:")
try:
    import requests
    response = requests.get("http://localhost:8000/health", timeout=5)
    if response.status_code == 200:
        print("  ✓ API health check: OK")
    else:
        print(f"  ✗ API health check failed: {response.status_code}")
except Exception as e:
    print(f"  ✗ API test failed: {e}")

# Test 4: UI Dashboard
print("\n4. Testing UI Dashboard:")
try:
    import requests
    response = requests.get("http://localhost:8501", timeout=3)
    if response.status_code == 200:
        print("  ✓ Streamlit UI is accessible")
    else:
        print(f"  ✗ Streamlit UI not accessible: {response.status_code}")
except Exception as e:
    print(f"  ✗ UI test failed: {e}")

# Test 5: Batch Prediction
print("\n5. Testing batch prediction:")
try:
    import subprocess
    result = subprocess.run(['.venv\\Scripts\\python.exe', 'scripts\\batch_predict.py'], 
                          capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        print("  ✓ Batch prediction script runs successfully")
        print("    Output preview:")
        print("    " + "\n".join(line for line in result.stdout.split('\n') if line and len(line) > 20)[:3])
    else:
        print(f"  ✗ Batch prediction script error: {result.returncode}")
        print("    stdout:", result.stdout[:200])
        print("    stderr:", result.stderr[:200])
except Exception as e:
    print(f"  ✗ Batch prediction test failed: {e}")

# Test 6: Docker Compose
print("\n6. Testing Docker Compose:")
try:
    import subprocess
    result = subprocess.run(['docker-compose', 'config'], capture_output=True, text=True)
    if result.returncode == 0:
        print("  ✓ docker-compose.yml is valid")
    else:
        print("  ✗ docker-compose.yml invalid")
        print(result.stderr)
except Exception as e:
    print(f"  ✗ Docker Compose test failed: {e}")

print("\n" + "=" * 60)
print("Verification complete. Check above for results.")
print("=" * 60)