import importlib

from sqlalchemy import inspect


def test_ensure_calendar_schema_creates_table(monkeypatch, tmp_path):
    db_path = tmp_path / "staging_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")

    # Reload modules so the new DATABASE_URL is picked up
    import app.appdb as appdb

    importlib.reload(appdb)

    # Ensure the orgs table exists for the FK constraint
    with appdb.engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS orgs (org_id INTEGER PRIMARY KEY);")

    import app.db_schema as db_schema

    importlib.reload(db_schema)

    db_schema.ensure_calendar_schema()

    inspector = inspect(appdb.engine)
    assert "staging_events" in inspector.get_table_names()

    import app.repositories as repositories

    importlib.reload(repositories)

    repo = repositories.StagingEventRepository()

    # Should not raise UndefinedTable once the schema is ensured
    repo.clear_all(org_id=1)
