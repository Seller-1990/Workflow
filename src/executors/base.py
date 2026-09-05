# -*- coding: utf-8 -*-
"""执行器基类"""

import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import threading

from runtime.process_runner import run_process


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
    
    @staticmethod
    def wait_with_cancel(
        proc,
        timeout: int,
        cancel_event: threading.Event = None,
        check_interval: float = 0.5
    ) -> tuple[bool, bool]:
        """统一的取消感知等待

        Args:
            proc: subprocess.Popen 进程对象
            timeout: 超时时间（秒）
            cancel_event: 取消事件，设置后应尽早中断（在等待间隔上阻塞，
                set 后立即唤醒，取消感知延迟不再受 check_interval 限制）
            check_interval: 检查间隔（秒）

        Returns:
            tuple[bool, bool]: (是否正常结束, 是否被取消)
            - (True, False): 进程正常结束
            - (True, True): 进程被取消中断
            - (False, False): 进程超时
        """
        start = time.monotonic()
        while proc.poll() is None:
            if cancel_event and cancel_event.wait(check_interval):
                return (True, True)  # 被取消（wait 返回 True = 事件已 set）
            if timeout and time.monotonic() - start > timeout:
                return (False, False)  # 超时
        return (True, False)  # 进程正常结束

    @staticmethod
    def sleep_with_cancel(
        duration: float,
        cancel_event: threading.Event = None,
        chunk: float = 0.5,
    ) -> bool:
        """MA1: 取消感知的固定时长等待

        用于"启动后等待若干秒让外部应用初始化"的场景。

        Returns:
            bool: True = 期间被取消；False = 正常等待完成
        """
        if duration <= 0:
            return bool(cancel_event and cancel_event.is_set())
        remaining = float(duration)
        while remaining > 0:
            if cancel_event and cancel_event.is_set():
                return True
            step = chunk if remaining > chunk else remaining
            time.sleep(step)
            remaining -= step
        return bool(cancel_event and cancel_event.is_set())

    @staticmethod
    def kill_process_tree(proc, taskkill_timeout: int = 10, wait_timeout: int = 5) -> None:
        """MA1: 统一的进程树终止逻辑（Windows: taskkill /F /T，POSIX: killpg 进程组）

        子类如果有更激进的兜底（如 psutil 扫描特定进程名），可以在调用本方法后追加。

        F-05: POSIX 子进程经 build_subprocess_kwargs 的 start_new_session=True
        启动在自己的进程组中，用 os.killpg 对整组发 SIGKILL；进程组已消失
        （或老进程未带新会话启动）时回退到 proc.kill() 只杀直接子进程。
        """
        if proc is None:
            return
        if sys.platform == "win32":
            try:
                run_process(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=taskkill_timeout,
                )
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        else:
            killed_group = False
            try:
                import os
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                killed_group = True
            except (PermissionError, ProcessLookupError):
                # 进程组已消失或无权限：回退 proc.kill() 兜底
                killed_group = False
            if not killed_group:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            proc.wait(timeout=wait_timeout)
        except (subprocess.TimeoutExpired, Exception):
            try:
                proc.kill()
                proc.wait(timeout=wait_timeout)
            except Exception:
                pass

    def build_log_dir(self, log_dir: Path = None) -> tuple[Path, Path, Path]:
        """统一的日志目录引导（P2：消 4× 重复的 excel/powerbi×2/python 引导块）。

        - log_dir 缺省时用全局 LOG_DIR + ``%Y%m%d_%H%M%S`` 时间戳子目录
        - 确保目录已创建（``exist_ok``），推导 stdout/stderr 路径

        Returns:
            tuple[Path, Path, Path]: (log_dir, stdout_path, stderr_path)
        """
        if log_dir is None:
            from config import LOG_DIR
            log_dir = LOG_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "stdout.txt"
        stderr_path = log_dir / "stderr.txt"
        return log_dir, stdout_path, stderr_path

    @abstractmethod
    def execute(
        self,
        script_path: str,
        args: List[str] = None,
        cwd: str = None,
        env: Dict[str, str] = None,
        log_dir: Path = None,
        timeout: int = None,
        cancel_event: threading.Event = None,
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
            cancel_event: 取消事件，设置后执行器应尽早中断并返回
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
        if not path_value:
            return Path()
        
        path = Path(path_value)
        if path.is_absolute():
            return path
        
        if base_dir:
            return (base_dir / path).resolve()
        
        # 检测是否在打包环境中
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            # PyInstaller 打包环境
            base_dir = Path(sys._MEIPASS)
        else:
            # 开发环境：使用项目根目录
            from config import ROOT_DIR
            base_dir = ROOT_DIR.parent
        
        return (base_dir / path).resolve()
