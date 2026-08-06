# -*- coding: utf-8 -*-
"""工作流运行日志目录清理规则。"""

from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

LOG_DIR_PATTERN = re.compile(r"^\d{8}_\d{6}(?:_[0-9a-fA-F]{4,8})?$")

MAX_LOG_DIRS_PER_WORKFLOW = 500
MAX_LOG_SIZE_BYTES_PER_WORKFLOW = 500 * 1024 * 1024  # 500MB


def cleanup_old_log_dirs(
    workflow,
    *,
    base_log_dir: Path,
    active_dir_names: Iterable[str] | None = None,
    now: datetime | None = None,
    remove_tree: Callable[[Path], None] | None = None,
) -> int:
    """清理过期运行日志目录，返回删除数量。

    清理策略（按优先级）：
    1. 时间保留：超过 log_retention_days 的目录
    2. 数量上限：单工作流超过 MAX_LOG_DIRS_PER_WORKFLOW 个目录时删除最旧的
    3. 容量上限：单工作流日志总大小超过 MAX_LOG_SIZE_BYTES_PER_WORKFLOW 时删除最旧的
    """
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

    # Collect all eligible log directories (oldest first)
    eligible_dirs: list[Path] = []
    for subdir in sorted(workflow_log_dir.iterdir()):
        if not subdir.is_dir():
            continue
        if not LOG_DIR_PATTERN.match(subdir.name):
            continue
        if subdir.name in active_names:
            continue
        resolved_subdir = subdir.resolve()
        try:
            resolved_subdir.relative_to(workflow_log_dir)
        except ValueError:
            continue
        eligible_dirs.append(resolved_subdir)

    removed = 0

    # Pass 1: Remove time-expired directories
    surviving: list[Path] = []
    for subdir in eligible_dirs:
        try:
            dir_time = datetime.strptime(subdir.name[:15], "%Y%m%d_%H%M%S")
        except (ValueError, IndexError):
            surviving.append(subdir)
            continue
        if dir_time < cutoff:
            remover(subdir)
            removed += 1
        else:
            surviving.append(subdir)

    # Pass 2: Enforce count cap (delete oldest when exceeding MAX_LOG_DIRS_PER_WORKFLOW)
    while len(surviving) > MAX_LOG_DIRS_PER_WORKFLOW:
        remover(surviving.pop(0))
        removed += 1

    # Pass 3: Enforce size cap
    total_size = 0
    dir_sizes: list[tuple[Path, int]] = []
    for subdir in surviving:
        try:
            size = sum(f.stat().st_size for f in subdir.rglob("*") if f.is_file())
        except OSError:
            size = 0
        dir_sizes.append((subdir, size))
        total_size += size

    idx = 0
    while total_size > MAX_LOG_SIZE_BYTES_PER_WORKFLOW and idx < len(dir_sizes):
        path, size = dir_sizes[idx]
        remover(path)
        removed += 1
        total_size -= size
        idx += 1

    return removed


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
