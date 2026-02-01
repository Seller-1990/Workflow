# -*- coding: utf-8 -*-
"""执行器基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List


@dataclass
class ExecutorResult:
    """执行结果"""
    success: bool
    exit_code: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    error_message: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """计算执行时长"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class BaseExecutor(ABC):
    """执行器基类"""
    
    def __init__(self):
        self.name = self.__class__.__name__
    
    @abstractmethod
    def execute(
        self,
        script_path: str,
        args: List[str] = None,
        cwd: str = None,
        env: Dict[str, str] = None,
        log_dir: Path = None,
        timeout: int = None,
        **kwargs
    ) -> ExecutorResult:
        """执行步骤
        
        Args:
            script_path: 脚本或文件路径
            args: 命令行参数
            cwd: 工作目录
            env: 环境变量
            log_dir: 日志目录
            timeout: 超时时间（秒）
            **kwargs: 其他参数
            
        Returns:
            ExecutorResult: 执行结果
        """
        pass
    
    def validate(self, script_path: str) -> bool:
        """验证脚本路径是否有效
        
        Args:
            script_path: 脚本路径
            
        Returns:
            是否有效
        """
        if not script_path:
            return False
        path = Path(script_path)
        return path.exists() and path.is_file()
    
    def get_absolute_path(self, path_value: str, base_dir: Path = None) -> Path:
        """获取绝对路径
        
        Args:
            path_value: 路径值（可能是相对路径）
            base_dir: 基准目录
            
        Returns:
            绝对路径
        """
        path = Path(path_value)
        if path.is_absolute():
            return path
        
        if base_dir:
            return (base_dir / path).resolve()
        
        # 默认使用项目根目录
        from config import ROOT_DIR
        return (ROOT_DIR.parent / path).resolve()
