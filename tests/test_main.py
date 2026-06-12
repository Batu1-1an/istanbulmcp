from starlette.testclient import TestClient

from app.main import create_app


def test_healthz_returns_ok():
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_readyz_initializes_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    from app.core.settings import get_settings

    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["ready"] is True
