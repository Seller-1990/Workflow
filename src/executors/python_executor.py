# -*- coding: utf-8 -*-
"""Python 脚本执行器"""

import os
import sys
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from executors.base import BaseExecutor, ExecutorResult


def _get_python_executable() -> str:
    """获取 Python 解释器路径
    
    在打包后的 exe 中，sys.executable 指向 exe 本身，
    需要使用系统的 Python 解释器来运行脚本。
    """
    # 检查是否在打包环境中运行
    if getattr(sys, 'frozen', False):
        # 打包环境：查找系统 Python
        python_path = shutil.which('python')
        if python_path:
            return python_path
        # 备选：尝试常见路径
        for candidate in [
            r'C:\Python312\python.exe',
            r'C:\Python311\python.exe',
            r'C:\Python310\python.exe',
            os.path.expandvars(r'%LOCALAPPDATA%\Programs\Python\Python312\python.exe'),
            os.path.expandvars(r'%LOCALAPPDATA%\Programs\Python\Python311\python.exe'),
        ]:
            if os.path.exists(candidate):
                return candidate
        # 最后尝试：直接使用 'python' 命令
        return 'python'
    else:
        # 开发环境：使用当前 Python
        return sys.executable


def _decode_line(raw: bytes) -> str:
    """解码输出行"""
    for enc in ('utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')


def _stream_pipe(pipe, file_obj, stream):
    """流式读取管道输出"""
    try:
        for raw_line in iter(pipe.readline, b''):
            decoded = _decode_line(raw_line)
            file_obj.write(decoded)
            file_obj.flush()
            try:
                stream.write(decoded)
                stream.flush()
            except Exception:
                pass
    except Exception:
        pass


class PythonExecutor(BaseExecutor):
    """Python 脚本执行器"""
    
    def execute(
        self,
        script_path: str,
        args: List[str] = None,
        cwd: str = None,
        env: Dict[str, str] = None,
        log_dir: Path = None,
        timeout: int = None,
        chart_theme: str = None,
        **kwargs
    ) -> ExecutorResult:
        """执行 Python 脚本
        
        Args:
            script_path: Python 脚本路径
            args: 命令行参数
            cwd: 工作目录
            env: 额外环境变量
            log_dir: 日志目录
            timeout: 超时时间（秒）
            chart_theme: 图表主题
            
        Returns:
            ExecutorResult: 执行结果
        """
        # 解析路径
        script = self.get_absolute_path(script_path)
        if not script.exists():
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"脚本不存在: {script}"
            )
        
        # 工作目录
        if cwd:
            work_dir = Path(cwd)
            if not work_dir.is_absolute():
                work_dir = script.parent / cwd
        else:
            work_dir = script.parent
        
        # 准备日志目录
        if log_dir is None:
            from config import LOG_DIR
            log_dir = LOG_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        stdout_path = log_dir / "stdout.txt"
        stderr_path = log_dir / "stderr.txt"
        
        # 准备环境变量
        run_env = os.environ.copy()
        run_env['PYTHONIOENCODING'] = 'utf-8'
        run_env['PYTHONUTF8'] = '1'
        run_env['PYTHONUNBUFFERED'] = '1'
        run_env['WORKFLOW_STEP_LOG_DIR'] = str(log_dir)
        
        if chart_theme:
            run_env['CHART_THEME'] = chart_theme
        
        if env:
            run_env.update(env)
        
        # 准备参数
        if args is None:
            args = []
        elif isinstance(args, str):
            args = [args]
        
        # 构建命令 - 使用 _get_python_executable() 而不是 sys.executable
        python_exe = _get_python_executable()
        cmd = [python_exe, '-u', str(script)] + list(args)
        
        start_time = datetime.now()
        
        try:
            with open(stdout_path, 'w', encoding='utf-8-sig') as f_out, \
                 open(stderr_path, 'w', encoding='utf-8-sig') as f_err:
                
                # Windows 下隐藏控制台窗口
                creation_flags = 0
                if sys.platform == 'win32':
                    creation_flags = subprocess.CREATE_NO_WINDOW
                
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(work_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                    env=run_env,
                    bufsize=0,
                    creationflags=creation_flags
                )
                
                # 启动输出线程
                t_out = threading.Thread(
                    target=_stream_pipe,
                    args=(proc.stdout, f_out, sys.stdout)
                )
                t_err = threading.Thread(
                    target=_stream_pipe,
                    args=(proc.stderr, f_err, sys.stderr)
                )
                t_out.start()
                t_err.start()
                
                # 等待完成
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    end_time = datetime.now()
                    return ExecutorResult(
                        success=False,
                        exit_code=-1,
                        start_time=start_time,
                        end_time=end_time,
                        stdout_path=str(stdout_path),
                        stderr_path=str(stderr_path),
                        error_message=f"执行超时 ({timeout}秒)"
                    )
                
                t_out.join()
                t_err.join()
            
            end_time = datetime.now()
            exit_code = proc.returncode
            
            return ExecutorResult(
                success=(exit_code == 0),
                exit_code=exit_code,
                start_time=start_time,
                end_time=end_time,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                error_message=None if exit_code == 0 else f"退出码: {exit_code}"
            )
            
        except Exception as e:
            end_time = datetime.now()
            return ExecutorResult(
                success=False,
                exit_code=-1,
                start_time=start_time,
                end_time=end_time,
                stdout_path=str(stdout_path) if stdout_path.exists() else None,
                stderr_path=str(stderr_path) if stderr_path.exists() else None,
                error_message=str(e)
            )
