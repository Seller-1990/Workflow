# -*- coding: utf-8 -*-
"""工作流自定义异常层次结构"""


class WorkflowError(Exception):
    """工作流基础异常"""
    pass


class ConfigurationError(WorkflowError):
    """配置错误（不可恢复）"""
    pass


class DependencyError(WorkflowError):
    """依赖错误"""
    pass


class WorkflowTimeoutError(WorkflowError):
    """超时错误"""
    pass
