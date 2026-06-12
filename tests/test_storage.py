from app.storage.db import init_database, readiness


def test_init_database_enables_wal_and_schema(tmp_path):
    db_path = tmp_path / "istanbul.sqlite3"

    status = init_database(db_path)

    assert status["journal_mode"] == "wal"
    assert status["schema_version"] == 1
    assert db_path.exists()


def test_readiness_reports_ready(tmp_path):
    status = readiness(tmp_path / "istanbul.sqlite3")

    assert status["ready"] is True
    assert status["journal_mode"] == "wal"
