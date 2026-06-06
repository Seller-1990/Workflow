# -*- coding: utf-8 -*-
"""MainWindow 运行按钮到 WorkflowEngine 的分发逻辑。"""

from __future__ import annotations


def run_engine_mode(engine, *, workflow_id: int, mode: str, param=None) -> bool:
    """按 UI 运行模式调用对应引擎方法。"""
    if mode == "full":
        return bool(engine.run_all(workflow_id))
    if mode == "from_step":
        return bool(engine.run_from(workflow_id, param))
    if mode == "only_step":
        return bool(engine.run_only(workflow_id, param))
    if mode == "only_stage":
        return bool(engine.run_stage(workflow_id, param))
    if mode == "from_stage":
        return bool(engine.run_from_stage(workflow_id, param))
    if mode == "retry_failed":
        return bool(engine.retry_failed(workflow_id))
    return False
