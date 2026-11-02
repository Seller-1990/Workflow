# -*- coding: utf-8 -*-
"""Immutable execution data copied before lifecycle commits can expire ORM rows."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from typing import Optional

from exceptions import ConfigurationError

logger = logging.getLogger("risk_path_review")


def _snapshot_logger():
    """Resolve late-bound facade patches without introducing an import cycle."""
    facade = sys.modules.get("risk_path_review")
    return getattr(facade, "logger", logger)


@dataclass(frozen=True)
class StepSnapshot:
    """执行期不可变步骤拷贝（H4: 校验后执行链路只消费本拷贝）。

    - 覆盖执行链路读取的全部字段（id/workflow_id/uid/order/name/stage_uid/
      step_type/script_path/cwd/timeout_seconds/retry_count/chart_theme/
      is_gate/skip_on_success/args/saved_run_args/depends_on）。
    - get_args() / get_saved_run_args() / get_depends_on() 与 ORM Step 同签名
      同行为；属性访问不触达数据库（修复 expire_on_commit 过期后执行期
      重新 SELECT 最新值的 TOCTOU）。
    - args / saved_run_args / depends_on 保留原始 JSON 串，解析延迟到访问期：
      快照构建 lenient；depends_on 损坏数据在访问期抛 ConfigurationError，
      保留「阻止错误调度」语义（与 models.Step.get_depends_on 一致）。
    """

    id: int
    workflow_id: int
    uid: str
    order: int
    name: str
    stage_uid: Optional[str]
    step_type: str
    script_path: Optional[str]
    cwd: Optional[str]
    timeout_seconds: Optional[int]
    retry_count: int
    chart_theme: Optional[str]
    is_gate: bool
    skip_on_success: bool
    args: Optional[str]
    saved_run_args: Optional[str]
    depends_on: Optional[str]

    def get_args(self) -> list:
        """与 ORM Step.get_args() 同签名同行为（损坏 JSON 宽容降级为 []）。"""
        if self.args:
            try:
                return json.loads(self.args)
            except json.JSONDecodeError as exc:
                _snapshot_logger().warning("步骤参数 JSON 解析失败: step=%s", self.uid)
        return []

    def get_saved_run_args(self) -> list:
        """与 ORM Step.get_saved_run_args() 同签名同行为。"""
        if self.saved_run_args:
            try:
                value = json.loads(self.saved_run_args)
                if isinstance(value, list) and all(isinstance(arg, str) for arg in value):
                    return value
                _snapshot_logger().warning("步骤已保存运行参数不是字符串数组: step=%s", self.uid)
            except json.JSONDecodeError as exc:
                _snapshot_logger().warning("步骤已保存运行参数 JSON 解析失败: %s", exc)
        return []

    def get_depends_on(self) -> list:
        """与 ORM Step.get_depends_on() 同签名同行为（损坏数据抛 ConfigurationError）。"""
        if not self.depends_on:
            return []
        try:
            value = json.loads(self.depends_on)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"步骤依赖 JSON 损坏: step={self.uid}") from exc
        if not isinstance(value, list) or not all(isinstance(uid, str) for uid in value):
            raise ConfigurationError(f"步骤依赖格式无效: step={self.uid}")
        return value


@dataclass(frozen=True)
class WorkflowView:
    """执行期不可变工作流视图（H4: 执行链路读取本拷贝，避免 ORM 过期重查）。"""

    id: int
    uid: str
    name: str
    parallel_enabled: bool
    max_workers: int
    chart_theme: str


def build_step_snapshot(step, *, snapshot_type=StepSnapshot) -> StepSnapshot:
    """由 ORM Step（或同构对象）物化不可变 StepSnapshot（构建 lenient）。

    使用 getattr 兼容测试中的 SimpleNamespace 替身。
    """
    return snapshot_type(
        id=getattr(step, "id", 0) or 0,
        workflow_id=getattr(step, "workflow_id", 0) or 0,
        uid=str(getattr(step, "uid", "") or ""),
        order=getattr(step, "order", 0) or 0,
        name=str(getattr(step, "name", "") or ""),
        stage_uid=getattr(step, "stage_uid", None),
        step_type=str(getattr(step, "step_type", "python") or "python"),
        script_path=getattr(step, "script_path", None),
        cwd=getattr(step, "cwd", None),
        timeout_seconds=getattr(step, "timeout_seconds", None),
        retry_count=getattr(step, "retry_count", 0) or 0,
        chart_theme=getattr(step, "chart_theme", None),
        is_gate=bool(getattr(step, "is_gate", False)),
        skip_on_success=bool(getattr(step, "skip_on_success", False)),
        args=getattr(step, "args", None),
        saved_run_args=getattr(step, "saved_run_args", None),
        depends_on=getattr(step, "depends_on", None),
    )


def build_workflow_view(workflow, *, view_type=WorkflowView) -> Optional[WorkflowView]:
    """由 ORM Workflow（或同构对象）物化不可变 WorkflowView。"""
    if workflow is None:
        return None
    return view_type(
        id=getattr(workflow, "id", 0) or 0,
        uid=str(getattr(workflow, "uid", "") or ""),
        name=str(getattr(workflow, "name", "") or ""),
        parallel_enabled=bool(getattr(workflow, "parallel_enabled", False)),
        max_workers=getattr(workflow, "max_workers", 0) or 0,
        chart_theme=str(getattr(workflow, "chart_theme", "") or ""),
    )
