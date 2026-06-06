# -*- coding: utf-8 -*-
"""运行日志目录清理规则测试。"""

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine_core.log_cleanup import cleanup_old_log_dirs


def test_cleanup_old_log_dirs_removes_only_expired_matching_dirs(tmp_path):
    workflow = SimpleNamespace(uid="wf", log_retention_days=7)
    wf_log_dir = tmp_path / "wf"
    wf_log_dir.mkdir()
    old_log = wf_log_dir / "20260101_010203"
    old_log.mkdir()
    fresh_log = wf_log_dir / "20260110_010203"
    fresh_log.mkdir()
    invalid_name = wf_log_dir / "20260101_010203_backup"
    invalid_name.mkdir()
    plain_file = wf_log_dir / "20250101_000000"
    plain_file.write_text("not a dir", encoding="utf-8")
    removed = []

    count = cleanup_old_log_dirs(
        workflow,
        base_log_dir=tmp_path,
        now=datetime(2026, 1, 10, 12, 0, 0),
        remove_tree=lambda path: removed.append(path.name),
    )

    assert count == 1
    assert removed == ["20260101_010203"]


def test_cleanup_old_log_dirs_skips_active_running_log_dir(tmp_path):
    workflow = SimpleNamespace(uid="wf", log_retention_days=1)
    wf_log_dir = tmp_path / "wf"
    wf_log_dir.mkdir()
    active_old_log = wf_log_dir / "20260101_010203_abcd"
    active_old_log.mkdir()
    removed = []

    count = cleanup_old_log_dirs(
        workflow,
        base_log_dir=tmp_path,
        active_dir_names={active_old_log.name},
        now=datetime(2026, 1, 10, 12, 0, 0),
        remove_tree=lambda path: removed.append(path.name),
    )

    assert count == 0
    assert removed == []


def test_cleanup_old_log_dirs_missing_workflow_dir_is_noop(tmp_path):
    workflow = SimpleNamespace(uid="missing", log_retention_days=1)

    assert cleanup_old_log_dirs(workflow, base_log_dir=tmp_path) == 0
