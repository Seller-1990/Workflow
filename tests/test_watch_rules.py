# -*- coding: utf-8 -*-
"""监听规则与旧配置自修复测试"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from engine import WorkflowEngine
from watch_rules import detect_watch_output_conflicts, sanitize_workflow_watch_config


@dataclass
class MockStep:
    script_path: str | None = None
    args: str | None = None

    def get_args(self) -> list[str]:
        if not self.args:
            return []
        return json.loads(self.args)


@dataclass
class MockWorkflow:
    id: int = 5
    name: str = "月度数据处理"
    watch_enabled: bool = True
    cooldown_seconds: int = 10
    settle_seconds: int = 0
    watch_mode: str = "any_change"
    folders: list[str] | None = None

    def get_watch_folders(self) -> list[str]:
        return list(self.folders or [])


def _monthly_refresh_step() -> MockStep:
    return MockStep(
        script_path=(
            "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/计算脚本/"
            "01_月度数据处理/00_月度接收/00_月度接收__月度基础数据刷新.py"
        )
    )


def test_detect_watch_output_conflicts_flags_monthly_output_dirs():
    conflicts = detect_watch_output_conflicts(
        [
            "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件/收入成本表",
            "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/月度接收/1账务信息/2026",
        ],
        [_monthly_refresh_step()],
    )

    assert "D:\\OneDrive - PowerBI学谦\\Data Analysis\\经营分析\\基础文件\\收入成本表" in conflicts
    assert all("月度接收" not in item for item in conflicts)


def test_sanitize_workflow_watch_config_rewrites_monthly_output_watchers():
    changed, sanitized_folders, enabled = sanitize_workflow_watch_config(
        workflow_name="月度数据处理",
        watch_enabled=True,
        watch_folders=[
            "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件/收入成本表",
            "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件/辅助帐明细",
        ],
        steps=[_monthly_refresh_step()],
    )

    assert changed is True
    assert enabled is True
    assert sanitized_folders == [
        "D:\\OneDrive - PowerBI学谦\\Data Analysis\\经营分析\\月度接收\\1账务信息"
    ]


def test_start_watch_rejects_output_directory_overlap(monkeypatch, tmp_path: Path):
    engine = WorkflowEngine()
    watched = tmp_path / "基础文件" / "收入成本表"
    watched.mkdir(parents=True)
    workflow = MockWorkflow(folders=[str(watched)])

    monkeypatch.setattr(
        "engine.get_steps_by_workflow",
        lambda workflow_id: [MockStep(script_path=str(tmp_path / "00_月度接收__月度基础数据刷新.py"))],
    )
    monkeypatch.setattr(
        "engine.detect_watch_output_conflicts",
        lambda folders, steps: [str(watched.resolve())],
    )

    started = engine.start_watch(workflow)

    assert started is False
    assert engine._watcher._thread is None


def test_sanitize_workflow_watch_config_updates_sqlite_row(tmp_path: Path):
    db_path = tmp_path / "workflows.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE workflows (id INTEGER PRIMARY KEY, name TEXT, watch_enabled INTEGER, watch_folders TEXT)"
        )
        conn.execute(
            "INSERT INTO workflows(id, name, watch_enabled, watch_folders) VALUES(5, '月度数据处理', 1, ?)",
            (
                json.dumps(
                    [
                        "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件/收入成本表",
                        "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件/辅助帐明细",
                    ],
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()

        changed, folders, enabled = sanitize_workflow_watch_config(
            workflow_name="月度数据处理",
            watch_enabled=True,
            watch_folders=json.loads(
                conn.execute("select watch_folders from workflows where id = 5").fetchone()[0]
            ),
            steps=[_monthly_refresh_step()],
        )

        assert changed is True
        conn.execute(
            "update workflows set watch_enabled = ?, watch_folders = ? where id = 5",
            (1 if enabled else 0, json.dumps(folders, ensure_ascii=False)),
        )
        conn.commit()

        row = conn.execute("select watch_enabled, watch_folders from workflows where id = 5").fetchone()
        assert row[0] == 1
        assert json.loads(row[1]) == [
            "D:\\OneDrive - PowerBI学谦\\Data Analysis\\经营分析\\月度接收\\1账务信息"
        ]
    finally:
        conn.close()
