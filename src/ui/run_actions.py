# -*- coding: utf-8 -*-
"""MainWindow 运行按钮到 WorkflowEngine 的分发逻辑。"""

from __future__ import annotations

from typing import Mapping, Sequence


def _call_run_method(method, *args, run_arg_overrides=None) -> bool:
    if run_arg_overrides is not None:
        return bool(method(*args, run_arg_overrides=run_arg_overrides))
    return bool(method(*args))


def run_engine_mode(
    engine,
    *,
    workflow_id: int,
    mode: str,
    param=None,
    run_arg_overrides: Mapping[str, Sequence[str]] | None = None,
) -> bool:
    """按 UI 运行模式调用对应引擎方法。"""
    overrides = None if run_arg_overrides is None else dict(run_arg_overrides)
    if mode == "full":
        return _call_run_method(engine.run_all, workflow_id, run_arg_overrides=overrides)
    if mode == "from_step":
        return _call_run_method(engine.run_from, workflow_id, param, run_arg_overrides=overrides)
    if mode == "only_step":
        return _call_run_method(engine.run_only, workflow_id, param, run_arg_overrides=overrides)
    if mode == "only_stage":
        return _call_run_method(engine.run_stage, workflow_id, param, run_arg_overrides=overrides)
    if mode == "from_stage":
        return _call_run_method(engine.run_from_stage, workflow_id, param, run_arg_overrides=overrides)
    if mode == "retry_failed":
        # 重试失败不弹窗、不附加临时参数
        return bool(engine.retry_failed(workflow_id))
    return False
