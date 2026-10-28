"""Pytest fixtures for CRM entity resolution tests."""
import os
import pytest
from pathlib import Path

# Setup test environment
PROJECT_ROOT = Path(__file__).parent.parent
os.environ["POSTGRES_HOST"] = os.environ.get("POSTGRES_HOST", "localhost")
os.environ["POSTGRES_PORT"] = os.environ.get("POSTGRES_PORT", "5432")
os.environ["POSTGRES_DB"] = os.environ.get("POSTGRES_DB", "crm")
os.environ["POSTGRES_USER"] = os.environ.get("POSTGRES_USER", "crm_user")
os.environ["POSTGRES_PASSWORD"] = os.environ.get("POSTGRES_PASSWORD", "crm_password_2026")


@pytest.fixture
def project_root():
    """Return project root directory."""
    return PROJECT_ROOT


@pytest.fixture
def output_dir(project_root):
    """Return outputs directory."""
    return project_root / "outputs"


@pytest.fixture
def data_dir(project_root):
    """Return data directory."""
    return project_root / "data"


@pytest.fixture
def sample_predictions(output_dir):
    """Load sample predictions for testing."""
    import pandas as pd
    sample_path = output_dir / "splink_predictions_sample.parquet"
    if sample_path.exists():
        return pd.read_parquet(sample_path)
    return None


@pytest.fixture
def db_connection():
    """Provide database connection for tests."""
    from src.db import get_connection
    with get_connection() as conn:
        yield conn