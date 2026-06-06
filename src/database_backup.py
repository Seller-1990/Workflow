# -*- coding: utf-8 -*-
"""工作流 JSON 自动备份文件管理。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

BACKUP_RETENTION_DAYS = 30
BACKUP_FILE_PREFIX = "workflows_backup_"
BACKUP_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


def auto_backup_workflows_impl(
    *,
    backup_dir: Path | None,
    default_backup_dir: Path,
    include_secrets: bool,
    export_to_json: Callable[..., None],
    now: datetime | None = None,
) -> Path:
    """执行自动备份并清理过期备份。"""
    current_time = now or datetime.now()
    resolved_dir = Path(backup_dir) if backup_dir is not None else Path(default_backup_dir)
    resolved_dir.mkdir(parents=True, exist_ok=True)

    backup_path = build_backup_path(resolved_dir, current_time)
    export_to_json(backup_path, include_secrets=include_secrets)
    cleanup_expired_backups(resolved_dir, now=current_time)
    return backup_path


def build_backup_path(backup_dir: Path, timestamp: datetime) -> Path:
    filename = f"{BACKUP_FILE_PREFIX}{timestamp.strftime(BACKUP_TIMESTAMP_FORMAT)}.json"
    return Path(backup_dir) / filename


def cleanup_expired_backups(
    backup_dir: Path,
    *,
    now: datetime | None = None,
    retention_days: int = BACKUP_RETENTION_DAYS,
) -> list[Path]:
    """清理过期备份，返回已删除文件列表。"""
    cutoff = (now or datetime.now()) - timedelta(days=retention_days)
    removed: list[Path] = []
    for backup_file in sorted(Path(backup_dir).glob(f"{BACKUP_FILE_PREFIX}*.json")):
        try:
            timestamp = parse_backup_timestamp(backup_file)
            if timestamp < cutoff:
                backup_file.unlink(missing_ok=True)
                removed.append(backup_file)
        except (ValueError, OSError):
            continue
    return removed


def parse_backup_timestamp(backup_file: Path) -> datetime:
    timestamp_text = Path(backup_file).stem.replace(BACKUP_FILE_PREFIX, "")
    return datetime.strptime(timestamp_text, BACKUP_TIMESTAMP_FORMAT)
