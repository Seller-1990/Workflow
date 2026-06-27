# -*- coding: utf-8 -*-
"""工作流运行日志目录清理规则。"""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

LOG_DIR_PATTERN = re.compile(r"^\d{8}_\d{6}(?:_[0-9a-fA-F]{4,8})?$")


def cleanup_old_log_dirs(
    workflow,
    *,
    base_log_dir: Path,
    active_dir_names: Iterable[str] | None = None,
    now: datetime | None = None,
    remove_tree: Callable[[Path], None] | None = None,
) -> int:
    """清理过期运行日志目录，返回删除数量。"""
    retention_days = getattr(workflow, "log_retention_days", 30) or 30
    base_dir = Path(base_log_dir).resolve()
    workflow_log_dir = (base_dir / workflow.uid).resolve()
    try:
        workflow_log_dir.relative_to(base_dir)
    except ValueError:
        return 0
    if not workflow_log_dir.exists():
        return 0

    cutoff = (now or datetime.now()) - timedelta(days=retention_days)
    active_names = set(active_dir_names or [])
    remover = remove_tree or _remove_tree

    removed = 0
    for subdir in sorted(workflow_log_dir.iterdir()):
        if not subdir.is_dir():
            continue
        if not LOG_DIR_PATTERN.match(subdir.name):
            continue
        if subdir.name in active_names:
            continue
        try:
            dir_time = datetime.strptime(subdir.name[:15], "%Y%m%d_%H%M%S")
        except (ValueError, IndexError):
            continue
        if dir_time < cutoff:
            resolved_subdir = subdir.resolve()
            try:
                resolved_subdir.relative_to(workflow_log_dir)
            except ValueError:
                continue
            remover(resolved_subdir)
            removed += 1
    return removed


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
