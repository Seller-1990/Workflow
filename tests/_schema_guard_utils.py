# -*- coding: utf-8 -*-
"""schema 守卫测试共享辅助：临时测试数据库装配。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import database


def _use_temp_database(monkeypatch, tmp_path: Path):
    database.cleanup_session()
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workflows.db")
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_SessionFactory", None)
    monkeypatch.setattr(database, "_scoped_session", None)
    monkeypatch.setattr(database, "_init_done", False)
    database.init_db()
    return database
