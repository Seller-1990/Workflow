# -*- coding: utf-8 -*-
"""执行器模块"""

from executors.base import BaseExecutor, ExecutorResult
from executors.python_executor import PythonExecutor
from executors.excel_executor import ExcelExecutor
from executors.powerbi_executor import PowerBIExecutor
from executors.sub_workflow_executor import SubWorkflowExecutor


def get_executor(step_type: str) -> BaseExecutor:
    """获取执行器实例
    
    Args:
        step_type: 步骤类型 (python, excel_powerquery, powerbi_refresh)
        
    Returns:
        对应的执行器实例
    """
    executors = {
        "python": PythonExecutor,
        "excel_powerquery": ExcelExecutor,
        "powerbi_refresh": PowerBIExecutor,
        "sub_workflow": SubWorkflowExecutor,
    }
    
    executor_class = executors.get(step_type)
    if executor_class is None:
        raise ValueError(f"不支持的步骤类型: {step_type}")
    
    return executor_class()


__all__ = [
    "BaseExecutor",
    "ExecutorResult", 
    "PythonExecutor",
    "ExcelExecutor",
    "PowerBIExecutor",
    "SubWorkflowExecutor",
    "get_executor",
]
