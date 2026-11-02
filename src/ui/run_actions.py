# -*- coding: utf-8 -*-
"""MainWindow 运行按钮到 WorkflowEngine 的分发逻辑。"""

from __future__ import annotations

from typing import Mapping, Sequence


def _call_run_method(method, *args, run_arg_overrides=None) -> bool:
    kwargs = {} if run_arg_overrides is None else {"run_arg_overrides": run_arg_overrides}
    return bool(method(*args, **kwargs))


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
    methods = {
        "full": "run_all", "from_step": "run_from", "only_step": "run_only",
        "step_range": "run_range", "only_stage": "run_stage", "from_stage": "run_from_stage",
    }
    if mode == "retry_failed":
        # 重试失败不弹窗、不附加临时参数
        return bool(engine.retry_failed(workflow_id))
    method_name = methods.get(mode)
    if method_name is None:
        return False
    params = () if mode == "full" else (param,)
    if mode == "step_range":
        start_step_id, end_step_id = param
        params = (start_step_id, end_step_id)
    return _call_run_method(getattr(engine, method_name), workflow_id, *params, run_arg_overrides=overrides)
