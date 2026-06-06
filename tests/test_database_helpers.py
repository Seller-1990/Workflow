# -*- coding: utf-8 -*-
"""database 拆分 helper 测试。"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database_backup import (
    auto_backup_workflows_impl,
    build_backup_path,
    cleanup_expired_backups,
)
from database_field_guards import validate_update_fields


def test_validate_update_fields_reports_unknown_fields_sorted():
    with pytest.raises(ValueError, match="Workflow 不支持更新字段: aaa, zzz"):
        validate_update_fields(
            "Workflow",
            {"name": "ok", "zzz": 1, "aaa": 2},
            {"name"},
        )


def test_build_backup_path_uses_stable_timestamp_format(tmp_path):
    backup_path = build_backup_path(tmp_path, datetime(2026, 1, 2, 3, 4, 5))

    assert backup_path == tmp_path / "workflows_backup_20260102_030405.json"


def test_cleanup_expired_backups_removes_only_old_valid_backup_files(tmp_path):
    old_file = tmp_path / "workflows_backup_20260101_000000.json"
    old_file.write_text("old", encoding="utf-8")
    fresh_file = tmp_path / "workflows_backup_20260120_000000.json"
    fresh_file.write_text("fresh", encoding="utf-8")
    invalid_file = tmp_path / "workflows_backup_not-a-date.json"
    invalid_file.write_text("invalid", encoding="utf-8")

    removed = cleanup_expired_backups(
        tmp_path,
        now=datetime(2026, 2, 5, 0, 0, 0),
        retention_days=30,
    )

    assert removed == [old_file]
    assert not old_file.exists()
    assert fresh_file.exists()
    assert invalid_file.exists()


def test_auto_backup_workflows_impl_exports_and_cleans_expired_backups(tmp_path):
    old_file = tmp_path / "workflows_backup_20260101_000000.json"
    old_file.write_text("old", encoding="utf-8")
    calls = []

    backup_path = auto_backup_workflows_impl(
        backup_dir=tmp_path,
        default_backup_dir=tmp_path / "default",
        include_secrets=True,
        export_to_json=lambda path, include_secrets: calls.append((path, include_secrets))
        or path.write_text("{}", encoding="utf-8"),
        now=datetime(2026, 2, 5, 1, 2, 3),
    )

    assert backup_path == tmp_path / "workflows_backup_20260205_010203.json"
    assert calls == [(backup_path, True)]
    assert backup_path.exists()
    assert not old_file.exists()
