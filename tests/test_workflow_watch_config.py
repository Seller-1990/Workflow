# -*- coding: utf-8 -*-
"""月度数据处理监听配置回归测试"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
EXPORT_FILE = ROOT / "workflows_export.json"
DB_FILE = ROOT / "data" / "workflows.db"
WORKFLOW_NAME = "月度数据处理"
EXPECTED_WATCH_FOLDERS = [
    "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/月度接收/1账务信息"
]
OUTPUT_SEGMENT = "/基础文件/"

pytestmark = pytest.mark.skipif(
    not EXPORT_FILE.exists() or not DB_FILE.exists(),
    reason="local workflow export/database not available",
)


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _load_export_watch_folders() -> list[str]:
    payload = json.loads(EXPORT_FILE.read_text(encoding="utf-8"))
    for workflow in payload.get("workflows", []):
        if workflow.get("name") == WORKFLOW_NAME:
            watch = workflow.get("watch") or {}
            return [_normalize_path(item) for item in watch.get("folders", [])]
    raise AssertionError(f"未找到工作流: {WORKFLOW_NAME}")


def _load_db_watch_folders() -> list[str]:
    conn = sqlite3.connect(DB_FILE)
    try:
        row = conn.execute(
            "select watch_folders from workflows where name = ?",
            (WORKFLOW_NAME,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise AssertionError(f"数据库中未找到工作流: {WORKFLOW_NAME}")
    raw_value = row[0] or "[]"
    return [_normalize_path(item) for item in json.loads(raw_value)]


def test_monthly_workflow_watch_folders_track_input_not_output():
    export_folders = _load_export_watch_folders()
    db_folders = _load_db_watch_folders()

    assert export_folders == db_folders
    assert export_folders == EXPECTED_WATCH_FOLDERS
    assert all(OUTPUT_SEGMENT not in folder for folder in export_folders)
