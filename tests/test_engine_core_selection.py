# -*- coding: utf-8 -*-
"""运行模式步骤筛选逻辑测试。"""

import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine_core.selection import select_steps
from exceptions import ConfigurationError


@dataclass
class StepLike:
    id: int
    name: str
    stage_uid: str | None = None


@dataclass
class StepLogLike:
    step_id: int
    status: str


def _workflow(**kwargs):
    defaults = {"id": 9, "single_script_enabled": False}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _select(
    all_steps,
    mode_value,
    *,
    step_id=None,
    workflow=None,
    stage_uid=None,
    stage_map=None,
    latest_run=None,
    step_logs=None,
    log_messages=None,
):
    return select_steps(
        all_steps=all_steps,
        mode_value=mode_value,
        step_id=step_id,
        workflow=workflow or _workflow(),
        stage_uid=stage_uid,
        get_stage_order_map=lambda _workflow_id: stage_map or {},
        get_latest_run_history=lambda *args, **kwargs: latest_run,
        get_step_logs_by_run=lambda _run_id: step_logs or [],
        running_status_value="running",
        pending_status_value="pending",
        log_cb=(log_messages.append if log_messages is not None else None),
    )


def test_select_from_stage_returns_target_and_later_stage_steps():
    steps = [
        StepLike(1, "抽取", "extract"),
        StepLike(2, "清洗", "transform"),
        StepLike(3, "报表", "report"),
    ]

    selected = _select(
        steps,
        "from_stage",
        stage_uid="transform",
        stage_map={"extract": 0, "transform": 1, "report": 2},
    )

    assert [step.id for step in selected] == [2, 3]


def test_select_retry_failed_uses_latest_finished_run_logs():
    steps = [StepLike(1, "A"), StepLike(2, "B"), StepLike(3, "C")]

    selected = _select(
        steps,
        "retry_failed",
        latest_run=SimpleNamespace(id=33),
        step_logs=[
            StepLogLike(1, "success"),
            StepLogLike(2, "failure"),
            StepLogLike(3, "failure"),
        ],
    )

    assert [step.id for step in selected] == [2, 3]


def test_select_retry_failed_logs_when_previous_run_has_no_failures():
    messages = []

    selected = _select(
        [StepLike(1, "A")],
        "retry_failed",
        latest_run=SimpleNamespace(id=33),
        step_logs=[StepLogLike(1, "success")],
        log_messages=messages,
    )

    assert selected == []
    assert messages == ["上次运行没有失败的步骤"]


def test_single_script_enabled_flag_ignored_by_selection():
    """退役字段 single_script_enabled=1 不影响普通选择路径（按步骤表正常执行）。"""
    workflow = _workflow(single_script_enabled=True)

    # 普通工作流为空步骤表时按普通路径处理：only_step 找不到步骤报错（不再走单脚本分支）
    with pytest.raises(ConfigurationError, match="未找到步骤"):
        _select(
            [StepLike(1, "A")],
            "only_step",
            step_id=2,
            workflow=workflow,
        )

    # 找到步骤则正常返回（旧单脚本工作流中的步骤表内容照常被选择）
    selected = _select(
        [StepLike(1, "A"), StepLike(2, "B")],
        "only_step",
        step_id=2,
        workflow=workflow,
    )
    assert [step.id for step in selected] == [2]
