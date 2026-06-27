# -*- coding: utf-8 -*-
"""工作流自定义异常层次结构"""


class WorkflowError(Exception):
    """工作流基础异常"""
    pass


class ConfigurationError(WorkflowError):
    """配置错误（不可恢复）"""
    pass


class ExecutionError(WorkflowError):
    """执行错误（可能可恢复）"""

    def __init__(self, message: str, step_id: int = None, retryable: bool = True):
        super().__init__(message)
        self.step_id = step_id
        self.retryable = retryable


class DependencyError(WorkflowError):
    """依赖错误"""
    pass


class WorkflowTimeoutError(WorkflowError):
    """超时错误"""
    pass
