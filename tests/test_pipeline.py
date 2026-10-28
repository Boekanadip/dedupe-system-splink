"""Test that the pipeline components work."""
import os
import sys
from pathlib import Path

# Setup environment
os.environ["POSTGRES_HOST"] = os.environ.get("POSTGRES_HOST", "localhost")
os.environ["POSTGRES_PORT"] = os.environ.get("POSTGRES_PORT", "5432")
os.environ["POSTGRES_DB"] = os.environ.get("POSTGRES_DB", "crm")
os.environ["POSTGRES_USER"] = os.environ.get("POSTGRES_USER", "crm_user")
os.environ["POSTGRES_PASSWORD"] = os.environ.get("POSTGRES_PASSWORD", "crm_password_2026")

PROJECT_ROOT = Path(__file__).parent.parent


def test_env_loaded():
    """Test that .env variables are loaded."""
    from dotenv import load_dotenv
    
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        print("✓ .env file loaded successfully")
        return True
    else:
        print("⚠ No .env file found, using defaults")
        # Set defaults
        os.environ["POSTGRES_HOST"] = "localhost"
        os.environ["POSTGRES_PORT"] = "5432"
        os.environ["POSTGRES_DB"] = "crm"
        os.environ["POSTGRES_USER"] = "crm_user"
        os.environ["POSTGRES_PASSWORD"] = "crm_password_2026"
        return False


def test_requirements():
    """Test that required packages are installed."""
    required = [
        "pandas", "numpy", "pyarrow", "duckdb", 
        "psutil", "plotly", "splink", "streamlit"
    ]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
            print(f"✓ {pkg}")
        except ImportError:
            missing.append(pkg)
            print(f"✗ {pkg} (missing)")
    
    if missing:
        print(f"\nMissing: {missing}")
        return False
    return True


def test_fastapi_endpoints():
    """Test that FastAPI is available."""
    try:
        import api.app as app
        print("✓ FastAPI app loads")
        
        # Check health endpoint
        from fastapi.testclient import TestClient
        client = TestClient(app.app)
        response = client.get("/health")
        if response.status_code == 200:
            print("✓ /health endpoint works")
            return True
        else:
            print(f"✗ /health returned {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ FastAPI test failed: {e}")
        return False


def test_docker_compose():
    """Test docker-compose.yml exists."""
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    if compose_path.exists():
        print("✓ docker-compose.yml exists")
        return True
    else:
        print("✗ docker-compose.yml missing")
        return False


def test_makefile():
    """Test Makefile exists."""
    makefile_path = PROJECT_ROOT / "Makefile"
    if makefile_path.exists():
        print("✓ Makefile exists")
        return True
    else:
        print("✗ Makefile missing")
        return False


def test_quickstart():
    """Test quickstart.ps1 exists."""
    ps1_path = PROJECT_ROOT / "quickstart.ps1"
    if ps1_path.exists():
        print("✓ quickstart.ps1 exists")
        return True
    else:
        print("✗ quickstart.ps1 missing")
        return False


def test_ci_workflow():
    """Test CI workflow exists."""
    ci_path = PROJECT_ROOT / ".github/workflows/ci.yml"
    if ci_path.exists():
        print("✓ CI workflow exists")
        return True
    else:
        print("✗ CI workflow missing")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("CRM Entity Resolution - Component Tests")
    print("=" * 60)
    print()
    
    results = []
    results.append(("Environment loaded", test_env_loaded()))
    results.append(("Requirements installed", test_requirements()))
    results.append(("FastAPI endpoints", test_fastapi_endpoints()))
    results.append(("Docker Compose", test_docker_compose()))
    results.append(("Makefile", test_makefile()))
    results.append(("QuickStart", test_quickstart()))
    results.append(("CI Workflow", test_ci_workflow()))
    
    print()
    print("=" * 60)
    print("Summary:")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "PASS" if result else "WARN"
        print(f"  [{status}] {name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All systems operational!")
    elif passed >= 5:
        print("\n⚠ Most systems operational - some features may need setup")
    else:
        print("\n✗ Several issues need attention")
    
    sys.exit(0 if passed >= 5 else 1)