# -*- coding: utf-8 -*-
"""Power BI Desktop 刷新执行器"""

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from executors.base import BaseExecutor, ExecutorResult


class PowerBIExecutor(BaseExecutor):
    """Power BI Desktop 刷新执行器
    
    通过打开 .pbix 文件触发刷新，然后关闭。
    """
    
    # Power BI Desktop 默认安装路径
    PBIDESKTOP_PATHS = [
        r"C:\Program Files\Microsoft Power BI Desktop\bin\PBIDesktop.exe",
        r"C:\Program Files (x86)\Microsoft Power BI Desktop\bin\PBIDesktop.exe",
        # Microsoft Store 版本
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\PBIDesktop.exe"),
    ]
    
    def find_pbidesktop(self) -> Optional[str]:
        """查找 Power BI Desktop 可执行文件"""
        for path in self.PBIDESKTOP_PATHS:
            if os.path.exists(path):
                return path
        return None
    
    def execute(
        self,
        script_path: str,
        args: List[str] = None,
        cwd: str = None,
        env: Dict[str, str] = None,
        log_dir: Path = None,
        timeout: int = None,
        auto_close: bool = True,
        auto_refresh: bool = True,
        **kwargs
    ) -> ExecutorResult:
        """刷新 Power BI 文件
        
        Args:
            script_path: Power BI 文件路径 (.pbix)
            args: 未使用
            cwd: 未使用
            env: 未使用
            log_dir: 日志目录
            timeout: 超时时间（秒），默认 600 秒
            auto_close: 刷新后是否自动关闭（默认 True）
            
        Returns:
            ExecutorResult: 执行结果
            
        Note:
            Power BI Desktop 不支持命令行刷新，此执行器仅打开文件。
            建议手动刷新或使用 Power BI Service API。
        """
        # 解析路径
        pbix_path = self.get_absolute_path(script_path)
        if not pbix_path.exists():
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"Power BI 文件不存在: {pbix_path}"
            )
        
        # 检查文件扩展名
        if pbix_path.suffix.lower() != '.pbix':
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"不支持的文件格式: {pbix_path.suffix}"
            )
        
        # 查找 Power BI Desktop
        pbidesktop = self.find_pbidesktop()
        if not pbidesktop:
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message="未找到 Power BI Desktop，请确保已安装"
            )
        
        # 准备日志目录
        if log_dir is None:
            from config import LOG_DIR
            log_dir = LOG_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        stdout_path = log_dir / "stdout.txt"
        stderr_path = log_dir / "stderr.txt"
        
        # 解析参数
        if args:
            for arg in args:
                if arg == "--no-auto-close":
                    auto_close = False
                if arg == "--no-auto-refresh":
                    auto_refresh = False

        # 默认超时 10 分钟
        if timeout is None:
            timeout = 600
        
        start_time = datetime.now()
        log_messages = []
        error_messages = []
        
        try:
            log_messages.append(f"[{datetime.now().isoformat()}] 开始刷新 Power BI: {pbix_path}")
            log_messages.append(f"[{datetime.now().isoformat()}] Power BI Desktop: {pbidesktop}")
            log_messages.append(f"[{datetime.now().isoformat()}] 超时设置: {timeout} 秒")
            
            # 启动 Power BI Desktop 并打开文件
            # 注意：Power BI Desktop 不支持静默刷新，需要用户交互
            log_messages.append(f"[{datetime.now().isoformat()}] 正在打开文件...")
            
            # 使用 shell 打开（调用默认程序）
            proc = subprocess.Popen(
                [pbidesktop, str(pbix_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # 等待一段时间让 Power BI 加载
            wait_time = min(30, timeout)
            log_messages.append(f"[{datetime.now().isoformat()}] 等待 Power BI 加载 ({wait_time}秒)...")
            time.sleep(wait_time)
            
            # 检查进程是否仍在运行
            if proc.poll() is not None:
                # 进程已结束，可能是打开失败
                stdout, stderr = proc.communicate()
                if proc.returncode != 0:
                    error_messages.append(f"Power BI 启动失败，退出码: {proc.returncode}")
                    if stderr:
                        error_messages.append(stderr.decode('utf-8', errors='replace'))
                    
                    end_time = datetime.now()
                    with open(stdout_path, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(log_messages))
                    with open(stderr_path, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(error_messages))
                    
                    return ExecutorResult(
                        success=False,
                        exit_code=proc.returncode,
                        start_time=start_time,
                        end_time=end_time,
                        stdout_path=str(stdout_path),
                        stderr_path=str(stderr_path),
                        error_message='\n'.join(error_messages)
                    )
            
            log_messages.append(f"[{datetime.now().isoformat()}] Power BI 已启动")
            log_messages.append("")
            if auto_refresh:
                log_messages.append("尝试自动触发刷新...")
                self._try_auto_refresh(pbidesktop, log_messages, error_messages)
            else:
                log_messages.append("已关闭自动刷新（--no-auto-refresh）")
                log_messages.append("请在 Power BI Desktop 中手动点击'刷新'按钮。")
                log_messages.append("刷新完成后请保存并关闭文件。")
            
            if auto_close:
                log_messages.append("")
                log_messages.append(f"[{datetime.now().isoformat()}] 等待用户完成刷新并关闭 Power BI...")
                
                # 等待进程结束或超时
                try:
                    proc.wait(timeout=timeout - wait_time)
                    log_messages.append(f"[{datetime.now().isoformat()}] Power BI 已关闭")
                except subprocess.TimeoutExpired:
                    log_messages.append(f"[{datetime.now().isoformat()}] 等待超时，Power BI 仍在运行")
                    # 不强制终止，让用户自行关闭
            
            end_time = datetime.now()
            
            # 写入日志
            with open(stdout_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(log_messages))
            
            note = "Power BI 可能需要手动刷新"
            if auto_refresh and not error_messages:
                note = "已尝试自动刷新"
            return ExecutorResult(
                success=True,
                exit_code=0,
                start_time=start_time,
                end_time=end_time,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                extra={"note": note}
            )
            
        except Exception as e:
            error_messages.append(f"执行失败: {e}")
        
        end_time = datetime.now()
        
        # 写入日志
        with open(stdout_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(log_messages))
        with open(stderr_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(error_messages))
        
        return ExecutorResult(
            success=False,
            exit_code=1,
            start_time=start_time,
            end_time=end_time,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error_message='\n'.join(error_messages)
        )
    
    def validate(self, script_path: str) -> bool:
        """验证 Power BI 文件路径"""
        if not script_path:
            return False
        path = Path(script_path)
        if not path.exists():
            return False
        return path.suffix.lower() == '.pbix'

    def _try_auto_refresh(self, pbidesktop: str, log_messages: list, error_messages: list):
        """尝试自动刷新（需要 pywinauto）"""
        try:
            from pywinauto import Application
            app = Application(backend="uia").connect(path=pbidesktop, timeout=10)
            window = app.top_window()
            window.set_focus()
            window.type_keys("{F5}")
            log_messages.append("已发送刷新快捷键(F5)")
        except ImportError:
            error_messages.append("未安装 pywinauto，无法自动刷新")
        except Exception as e:
            error_messages.append(f"自动刷新失败: {e}")
