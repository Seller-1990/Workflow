"""A migration failure stops startup on the same isolated database being upgraded."""
from pathlib import Path
import pytest
from sqlalchemy import create_engine
import database


def test_pending_migration_failure_raises(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "schema.db"
    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)
    database._ensure_schema_version_table(engine)

    def _broken_migration(_engine):
        raise ValueError("boom")

    monkeypatch.setitem(database.__dict__, "_broken_migration_for_test", _broken_migration)
    monkeypatch.setattr(database, "SCHEMA_MIGRATIONS", [(99, "_broken_migration_for_test")])

    with pytest.raises(RuntimeError, match="schema 迁移 v99 失败"):
        database._run_pending_migrations(engine)
