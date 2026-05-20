# -*- coding: utf-8 -*-
"""工作流监听配置防呆测试"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from watch_rules import detect_watch_output_conflicts


@dataclass
class MockStep:
    script_path: str | None = None

    def get_args(self) -> list[str]:
        return []


def test_detect_watch_output_conflicts_flags_monthly_workflow_output_dirs():
    conflicts = detect_watch_output_conflicts(
        [
            "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/基础文件/收入成本表",
            "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/月度接收/1账务信息/2026",
        ],
        [
            MockStep(
                script_path=(
                    "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/计算脚本/"
                    "01_月度数据处理/00_月度接收/00_月度接收__月度基础数据刷新.py"
                )
            )
        ],
    )

    assert "D:\\OneDrive - PowerBI学谦\\Data Analysis\\经营分析\\基础文件\\收入成本表" in conflicts
    assert all("月度接收" not in item for item in conflicts)


def test_detect_watch_output_conflicts_allows_monthly_workflow_input_dir():
    conflicts = detect_watch_output_conflicts(
        ["D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/月度接收/1账务信息/2026"],
        [
            MockStep(
                script_path=(
                    "D:/OneDrive - PowerBI学谦/Data Analysis/经营分析/计算脚本/"
                    "01_月度数据处理/00_月度接收/00_月度接收__月度基础数据刷新.py"
                )
            )
        ],
    )

    assert conflicts == []
