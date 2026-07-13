# -*- coding: utf-8 -*-
"""SQLite snapshots created before schema upgrades."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


MIGRATION_BACKUP_DIR_NAME = "migration_backups"
MIGRATION_BACKUP_RETENTION = 5


def create_migration_snapshot(database_path: Path, target_version: int) -> Path:
    """Create and verify a consistent SQLite snapshot before migration."""
    source_path = Path(database_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Database file not found for migration snapshot: {source_path}")

    backup_dir = source_path.parent / MIGRATION_BACKUP_DIR_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"{source_path.stem}_before_v{target_version}_{timestamp}.db"

    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)

    with sqlite3.connect(backup_path) as snapshot:
        result = snapshot.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        backup_path.unlink(missing_ok=True)
        raise RuntimeError(f"Migration snapshot integrity check failed: {backup_path}")

    _cleanup_old_snapshots(backup_dir, source_path.stem)
    return backup_path


def _cleanup_old_snapshots(backup_dir: Path, database_stem: str) -> None:
    snapshots = sorted(
        backup_dir.glob(f"{database_stem}_before_v*_*.db"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for stale_path in snapshots[MIGRATION_BACKUP_RETENTION:]:
        stale_path.unlink(missing_ok=True)