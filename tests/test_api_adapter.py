"""Adapter REST API (src/api.py): endpoint, auth, dan fallback data.

Read-only: tidak menulis ke database, queue, atau artefak produksi.
"""
import importlib

import pytest
from starlette.testclient import TestClient


def _client(key: str | None = "secret-test-key"):
    import src.api as api

    if key is None:
        import os

        os.environ.pop("DEDUP_API_KEY", None)
        os.environ["DEDUP_API_DEV_MODE"] = "0"
    else:
        import os

        os.environ["DEDUP_API_KEY"] = key
        os.environ.pop("DEDUP_API_DEV_MODE", None)
    api = importlib.reload(api)
    return TestClient(api.app)


@pytest.mark.parametrize("path", ["/status", "/review-queue"])
def test_protected_endpoints_require_key(path):
    client = _client("secret-test-key")
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", ["/health", "/metrics"])
def test_public_endpoints_open(path):
    client = _client("secret-test-key")
    assert client.get(path).status_code == 200


def test_protected_endpoints_accept_key():
    client = _client("secret-test-key")
    for path in ("/health", "/status", "/review-queue"):
        r = client.get(path, headers={"X-API-Key": "secret-test-key"})
        assert r.status_code == 200, (path, r.status_code, r.text[:200])


def test_wrong_key_rejected():
    client = _client("secret-test-key")
    assert client.get("/status", headers={"X-API-Key": "salah"}).status_code == 401


def test_missing_key_config_denies_access():
    """Tanpa API key dan tanpa dev mode, request tidak boleh lolos."""
    client = _client(None)
    assert client.get("/status").status_code == 401


def test_dev_mode_opt_in_allows_access():
    import os

    os.environ["DEDUP_API_DEV_MODE"] = "1"
    os.environ.pop("DEDUP_API_KEY", None)
    import src.api as api

    api = importlib.reload(api)
    assert TestClient(api.app).get("/status").status_code == 200
    os.environ["DEDUP_API_DEV_MODE"] = "0"


def test_entity_and_record_lookup():
    client = _client("secret-test-key")
    headers = {"X-API-Key": "secret-test-key"}
    for path in ("/entities/tidak-ada", "/records/tidak-ada"):
        r = client.get(path, headers=headers)
        assert r.status_code in (200, 404), (path, r.status_code)


def test_public_health_has_thresholds():
    client = _client("secret-test-key")
    body = client.get("/health").json()
    assert "thresholds" in body
