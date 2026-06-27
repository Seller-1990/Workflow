# -*- coding: utf-8 -*-
"""执行器模块 - 插件化注册表架构

使用方式:
    # 获取执行器（内置类型自动注册）
    executor = get_executor("python")

    # 注册自定义执行器（插件扩展）
    from executors import register_executor, BaseExecutor
    class MyExecutor(BaseExecutor):
        def execute(self, ...): ...
    register_executor("my_type", MyExecutor)

    # 查询所有已注册类型
    types = list_registered_types()
"""

from typing import Dict, List, Optional, Type

from executors.base import BaseExecutor, ExecutorResult
from executors.python_executor import PythonExecutor
from executors.excel_executor import ExcelExecutor
from executors.powerbi_executor import PowerBIExecutor
from executors.result_policy import (
    ResultPolicyKeys,
    build_policy_extra,
    has_non_retryable_policy,
)
from executors.sub_workflow_executor import SubWorkflowExecutor


# ============================================================
# 执行器注册表
# ============================================================

_registry: Dict[str, Type[BaseExecutor]] = {}
_type_labels: Dict[str, str] = {}  # step_type -> 中文标签


def register_executor(
    step_type: str,
    executor_class: Type[BaseExecutor],
    label: Optional[str] = None
):
    """注册执行器到注册表

    Args:
        step_type: 步骤类型标识（如 "python"）
        executor_class: 执行器类（必须继承 BaseExecutor）
        label: 中文标签（如 "Python 脚本"），用于 UI 显示
    """
    if not issubclass(executor_class, BaseExecutor):
        raise TypeError(
            f"{executor_class.__name__} 必须继承 BaseExecutor"
        )
    _registry[step_type] = executor_class
    if label:
        _type_labels[step_type] = label


def get_executor(step_type: str) -> BaseExecutor:
    """获取执行器实例

    Args:
        step_type: 步骤类型标识

    Returns:
        对应的执行器实例

    Raises:
        ValueError: 不支持的步骤类型
    """
    executor_class = _registry.get(step_type)
    if executor_class is None:
        supported = ", ".join(sorted(_registry.keys()))
        raise ValueError(
            f"不支持的步骤类型: {step_type}（已注册: {supported}）"
        )
    return executor_class()


def list_registered_types() -> List[str]:
    """返回所有已注册的步骤类型标识"""
    return sorted(_registry.keys())


def get_type_label(step_type: str) -> str:
    """获取步骤类型的中文标签"""
    return _type_labels.get(step_type, step_type)


def get_type_choices() -> List[tuple]:
    """返回 (step_type, label) 列表，用于 UI 下拉框"""
    return [(t, _type_labels.get(t, t)) for t in sorted(_registry.keys())]


# ============================================================
# 内置执行器自动注册
# ============================================================

register_executor("python", PythonExecutor, label="Python 脚本")
register_executor("excel_powerquery", ExcelExecutor, label="Excel 刷新")
register_executor("powerbi_refresh", PowerBIExecutor, label="PowerBI 刷新")
register_executor("sub_workflow", SubWorkflowExecutor, label="子工作流")


__all__ = [
    "BaseExecutor",
    "ExecutorResult",
    "PythonExecutor",
    "ExcelExecutor",
    "PowerBIExecutor",
    "ResultPolicyKeys",
    "SubWorkflowExecutor",
    "build_policy_extra",
    "get_executor",
    "has_non_retryable_policy",
    "register_executor",
    "list_registered_types",
    "get_type_label",
    "get_type_choices",
]
