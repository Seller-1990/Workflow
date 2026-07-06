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

from watch_rules import (
    collect_workflow_output_roots,
    detect_watch_output_conflicts,
    sanitize_workflow_watch_config,
)


@dataclass
class MockStep:
    script_path: str | None = None
    args: str | None = None
    step_type: str | None = None

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


def test_detect_watch_output_conflicts_flags_watch_parent_of_output_dir():
    conflicts = detect_watch_output_conflicts(
        ["D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件"],
        [_monthly_refresh_step()],
    )

    assert conflicts == ["D:\\OneDrive - PowerBI学谦\\Data Analysis\\经营分析\\基础文件"]


def test_detect_watch_output_conflicts_supports_inline_out_argument():
    output_dir = "D:/tmp/workflow-output"
    conflicts = detect_watch_output_conflicts(
        [output_dir],
        [MockStep(script_path="D:/tmp/job.py", args=json.dumps([f"--out={output_dir}"]))],
    )

    assert conflicts == ["D:\\tmp\\workflow-output"]


def test_detect_watch_output_conflicts_ignores_shallow_monthly_script_path():
    conflicts = detect_watch_output_conflicts(
        ["D:/tmp"],
        [MockStep(script_path="D:/tmp/00_月度接收__月度基础数据刷新.py")],
    )

    assert conflicts == []


def test_collect_workflow_output_roots_includes_excel_powerquery_workbook_dir():
    steps = [MockStep(script_path="D:/data/报表/月报.xlsx", step_type="excel_powerquery")]

    output_roots = collect_workflow_output_roots(steps)

    assert output_roots == [Path("D:/data/报表").resolve()]
    assert detect_watch_output_conflicts(["D:/data/报表"], steps) == ["D:\\data\\报表"]
    assert detect_watch_output_conflicts(["D:/data/输入"], steps) == []


def test_collect_workflow_output_roots_includes_powerbi_refresh_report_dir():
    steps = [MockStep(script_path="D:/data/报表/经营分析.pbix", step_type="powerbi_refresh")]

    output_roots = collect_workflow_output_roots(steps)

    assert output_roots == [Path("D:/data/报表").resolve()]
    assert detect_watch_output_conflicts(["D:/data/报表"], steps) == ["D:\\data\\报表"]
    assert detect_watch_output_conflicts(["D:/data/输入"], steps) == []


def test_collect_workflow_output_roots_ignores_python_step_script_dir():
    steps = [MockStep(script_path="D:/data/报表/处理脚本.py", step_type="python")]

    assert collect_workflow_output_roots(steps) == []
    assert detect_watch_output_conflicts(["D:/data/报表"], steps) == []


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
    from engine import WorkflowEngine

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
    # M1: 监听器按 workflow_id 管理；冲突拒绝后不应留下任何 watcher
    assert engine._watchers == {}


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

# ==================== ROI-2: 显式输出声明优先模型 ====================


@dataclass
class DeclaredOutputStep(MockStep):
    """带显式输出声明的步骤替身（模拟 models.Step.get_output_paths 契约）。"""

    declared_outputs: list[str] | None = None

    def get_output_paths(self) -> list[str]:
        return list(self.declared_outputs or [])


def test_collect_workflow_output_roots_prefers_declared_outputs():
    # (a) 显式声明优先：python 步骤声明输出后，监听该目录冲突，监听其他目录不冲突
    steps = [
        DeclaredOutputStep(
            script_path="D:/x/job.py",
            step_type="python",
            declared_outputs=["D:/x/out"],
        )
    ]

    assert collect_workflow_output_roots(steps) == [Path("D:/x/out").resolve()]
    assert detect_watch_output_conflicts(["D:/x/out"], steps) == [str(Path("D:/x/out").resolve())]
    assert detect_watch_output_conflicts(["D:/x/in"], steps) == []


def test_collect_workflow_output_roots_ignores_blank_declared_entries():
    # 空白声明不得被 resolve 成当前工作目录（避免误判全仓库冲突）
    steps = [DeclaredOutputStep(script_path="D:/x/job.py", declared_outputs=["", "   "])]

    assert collect_workflow_output_roots(steps) == []


def test_collect_workflow_output_roots_excludes_legacy_monthly_hardcode():
    # (b) 月度脚本后缀 + 无显式声明：通用推断路径不再包含 基础文件 业务硬编码
    assert collect_workflow_output_roots([_monthly_refresh_step()]) == []


def test_detect_watch_output_conflicts_keeps_legacy_monthly_net_by_default():
    # (b) 运行期检测默认仍叠加旧版月度兜底（存量库步骤未声明输出，
    # engine.start_watch / 配置保存防呆依赖该兜底）；关闭兜底后为声明+通用推断纯净路径
    folders = ["D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件/收入成本表"]
    steps = [_monthly_refresh_step()]

    assert detect_watch_output_conflicts(folders, steps) == [
        "D:\\OneDrive - PowerBI学谦\\Data Analysis\\经营分析\\基础文件\\收入成本表"
    ]
    assert detect_watch_output_conflicts(folders, steps, include_legacy_monthly=False) == []


def test_declared_outputs_flag_monthly_conflict_without_legacy_net():
    # 迁移路径：月度步骤补齐显式声明后，即使关闭旧版兜底也能识别 基础文件 重叠
    step = DeclaredOutputStep(
        script_path=_monthly_refresh_step().script_path,
        declared_outputs=["D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件"],
    )

    conflicts = detect_watch_output_conflicts(
        ["D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件/收入成本表"],
        [step],
        include_legacy_monthly=False,
    )

    assert conflicts == [
        "D:\\OneDrive - PowerBI学谦\\Data Analysis\\经营分析\\基础文件\\收入成本表"
    ]


def test_sanitize_workflow_watch_config_still_repairs_undeclared_monthly_config():
    # (b) 存量库修复：月度工作流无显式声明时，sanitize 仍识别 基础文件 重叠并改写监听目录
    changed, folders, enabled = sanitize_workflow_watch_config(
        workflow_name="月度数据处理",
        watch_enabled=True,
        watch_folders=["D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件/收入成本表"],
        steps=[_monthly_refresh_step()],
    )

    assert changed is True
    assert enabled is True
    assert folders == [
        "D:\\OneDrive - PowerBI学谦\\Data Analysis\\经营分析\\月度接收\\1账务信息"
    ]


def test_sanitize_workflow_watch_config_disables_when_conflict_has_no_safe_suggestion():
    changed, folders, enabled = sanitize_workflow_watch_config(
        workflow_name="自定义工作流",
        watch_enabled=True,
        watch_folders=["D:/x/out"],
        steps=[DeclaredOutputStep(script_path="D:/x/job.py", declared_outputs=["D:/x/out"])],
    )

    assert changed is True
    assert folders == []
    assert enabled is False
