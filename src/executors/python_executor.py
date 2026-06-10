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
from runtime.process_runner import build_subprocess_kwargs, start_process
from constants import PYTHON_STEP_TIMEOUT


def _get_python_executable() -> Optional[str]:
    """获取 Python 解释器路径

    在打包后的 exe 中，sys.executable 指向 exe 本身，
    需要使用系统的 Python 解释器来运行脚本。
    打包环境下找不到可用解释器时返回 None，由调用方给出明确错误。
    """
    # 检查是否在打包环境中运行
    if getattr(sys, 'frozen', False):
        # 打包环境：查找系统 Python
        for command in ('python', 'python3', 'py'):
            python_path = shutil.which(command)
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
        # 未找到系统 Python：返回 None，由 execute() 返回明确错误而非晦涩的 WinError
        return None
    else:
        # 开发环境：使用当前 Python
        return sys.executable


def _decode_line(raw: bytes) -> str:
    """解码输出行

    L7 修复：移除 latin-1 兜底（会把 UTF-8 字节当 latin-1 解码导致中文乱码）。
    所有候选编码失败后统一使用 utf-8 + replace（不可解码字节渲染为 �），
    避免出现"乱码字符串通过校验"的假阳性。
    """
    for enc in ('utf-8', 'gbk', 'gb2312', 'gb18030'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')


def _stream_pipe(pipe, file_obj, stream, log_errors: bool = True):
    """流式读取管道输出"""
    try:
        for raw_line in iter(pipe.readline, b''):
            if not raw_line:  # 管道已关闭
                break
            decoded = _decode_line(raw_line)
            try:
                file_obj.write(decoded)
                file_obj.flush()
            except IOError as e:
                if log_errors:
                    print(f"[PythonExecutor] 写入日志文件失败: {e}", file=sys.stderr)
                break
            try:
                stream.write(decoded)
                stream.flush()
            except Exception:
                # 控制台写入失败可忽略（如重定向到非TTY）
                pass
    except IOError as e:
        # 管道读取错误（如进程被强制终止）
        if log_errors:
            print(f"[PythonExecutor] 读取管道失败: {e}", file=sys.stderr)
    except Exception as e:
        if log_errors:
            print(f"[PythonExecutor] 输出流处理异常: {e}", file=sys.stderr)


_ENV_REMOVE_KEYS = {
    'PYTHONHOME',
    'PYTHONPATH',
    'PYTHONSTARTUP',
    'PYTHONUSERBASE',
    'PYTHONEXECUTABLE',
}


def _build_subprocess_env(log_dir: Path, chart_theme: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """构建子进程环境，避免继承会污染解释器/模块解析的 Python 变量。"""
    run_env = os.environ.copy()
    for key in _ENV_REMOVE_KEYS:
        run_env.pop(key, None)

    run_env['PYTHONIOENCODING'] = 'utf-8'
    run_env['PYTHONUTF8'] = '1'
    run_env['PYTHONUNBUFFERED'] = '1'
    run_env['WORKFLOW_STEP_LOG_DIR'] = str(log_dir)

    if chart_theme:
        run_env['CHART_THEME'] = chart_theme

    if env:
        for key, value in env.items():
            if key in _ENV_REMOVE_KEYS:
                continue
            run_env[key] = str(value)

    return run_env


def _read_stderr_excerpt(stderr_path: Path, max_lines: int = 8, max_chars: int = 400) -> str:
    """读取 stderr 末尾摘要，用于把真实错误回传到 UI/CLI。"""
    try:
        if not stderr_path.exists() or stderr_path.stat().st_size == 0:
            return ""
        content = stderr_path.read_text(encoding="utf-8-sig", errors="replace")
    except Exception:
        return ""

    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines:
        return ""
    excerpt = "\n".join(lines[-max_lines:]).strip()
    if len(excerpt) > max_chars:
        excerpt = excerpt[-max_chars:].lstrip()
    return excerpt


class PythonExecutor(BaseExecutor):
    """Python 脚本执行器"""

    SUPPORTED_SUFFIXES = {".py", ".pyw"}
    STREAM_JOIN_TIMEOUT_SECONDS = 5
    COMMUNICATE_TIMEOUT_SECONDS = 3

    def _normalize_args(self, args: List[str] = None) -> List[str]:
        """标准化并校验命令行参数。"""
        if args is None:
            return []
        if isinstance(args, str):
            return [args]
        normalized = list(args)
        if not all(isinstance(arg, str) for arg in normalized):
            raise ValueError("参数必须全部为字符串")
        if any("\x00" in arg for arg in normalized):
            raise ValueError("参数中不能包含空字符")
        return normalized

    def _resolve_work_dir(self, script: Path, cwd: str = None) -> Path:
        """解析并校验工作目录。"""
        if cwd:
            work_dir = Path(cwd)
            if not work_dir.is_absolute():
                work_dir = script.parent / cwd
        else:
            work_dir = script.parent
        work_dir = work_dir.resolve()
        if not work_dir.exists():
            raise ValueError(f"工作目录不存在: {work_dir}")
        if not work_dir.is_dir():
            raise ValueError(f"工作目录不是文件夹: {work_dir}")
        return work_dir

    def _cleanup_process_resources(
        self,
        proc: subprocess.Popen,
        t_out: threading.Thread | None,
        t_err: threading.Thread | None,
    ) -> None:
        """终止后尽快清空管道并回收输出线程，避免句柄与后台线程残留。"""
        try:
            proc.communicate(timeout=self.COMMUNICATE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                proc.wait()
            except Exception as e:
                print(f"[PythonExecutor] 等待进程退出失败: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[PythonExecutor] 回收进程管道失败: {e}", file=sys.stderr)
        finally:
            if t_out is not None:
                t_out.join(timeout=self.STREAM_JOIN_TIMEOUT_SECONDS)
            if t_err is not None:
                t_err.join(timeout=self.STREAM_JOIN_TIMEOUT_SECONDS)
    
    def execute(
        self,
        script_path: str,
        args: List[str] = None,
        cwd: str = None,
        env: Dict[str, str] = None,
        log_dir: Path = None,
        timeout: int = None,
        chart_theme: str = None,
        cancel_event: threading.Event = None,
        **kwargs
    ) -> ExecutorResult:
        """执行 Python 脚本
        
        Args:
            script_path: Python 脚本路径
            args: 命令行参数
            cwd: 工作目录
            env: 额外环境变量
            log_dir: 日志目录
            timeout: 超时时间（秒）；None 时使用默认值 PYTHON_STEP_TIMEOUT（7200 秒），
                显式传 0 保持历史语义"不限制"
            chart_theme: 图表主题
            
        Returns:
            ExecutorResult: 执行结果
        """
        # 初始化默认值，防止异常处理中未定义
        stdout_path = None
        stderr_path = None
        
        # 解析路径
        script = self.get_absolute_path(script_path)
        if not script.exists():
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"脚本不存在: {script}"
            )
        if not script.is_file():
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"脚本路径不是文件: {script}"
            )
        if script.suffix.lower() not in self.SUPPORTED_SUFFIXES:
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"不支持的脚本类型: {script.suffix or '无扩展名'}"
            )
        
        try:
            work_dir = self._resolve_work_dir(script, cwd)
            args = self._normalize_args(args)
        except ValueError as e:
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=str(e)
            )
        
        # 准备日志目录
        if log_dir is None:
            from config import LOG_DIR
            log_dir = LOG_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        stdout_path = log_dir / "stdout.txt"
        stderr_path = log_dir / "stderr.txt"

        # 默认超时（M9：来自 constants.py）
        # 仅替换 None（未配置）；显式 timeout=0 沿用历史语义"不限制"，不在此覆盖
        if timeout is None:
            timeout = PYTHON_STEP_TIMEOUT

        # 准备环境变量
        run_env = _build_subprocess_env(log_dir, chart_theme=chart_theme, env=env)
        
        # 构建命令 - 使用 _get_python_executable() 而不是 sys.executable
        python_exe = _get_python_executable()
        if python_exe is None:
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message="未找到系统 Python 解释器：请安装 Python 并加入 PATH，或在打包环境旁提供 python.exe"
            )
        cmd = [python_exe, '-u', str(script)] + list(args)
        
        start_time = datetime.now()
        
        proc = None
        t_out = None
        t_err = None
        try:
            with open(stdout_path, 'w', encoding='utf-8-sig') as f_out, \
                 open(stderr_path, 'w', encoding='utf-8-sig') as f_err:
                # 在日志首行记录实际使用的解释器，便于排查环境问题
                f_out.write(f"[PythonExecutor] interpreter: {python_exe}\n")

                # Windows 下隐藏控制台窗口
                creation_flags = 0
                if sys.platform == 'win32':
                    creation_flags = subprocess.CREATE_NO_WINDOW
                
                proc = start_process(
                    cmd,
                    **build_subprocess_kwargs(
                        cwd=work_dir,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=False,
                        env=run_env,
                        bufsize=0,
                        creationflags=creation_flags,
                    ),
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
                try:
                    t_out.start()
                    t_err.start()
                except Exception:
                    self.kill_process_tree(proc)
                    self._cleanup_process_resources(proc, t_out, t_err)
                    proc = None
                    raise
                
                # 等待完成（支持取消中断 + 超时）
                # MA1: 改用 BaseExecutor.wait_with_cancel 统一等待语义
                try:
                    if cancel_event:
                        normal, cancelled = self.wait_with_cancel(
                            proc, timeout or 0, cancel_event, check_interval=0.5
                        )
                        if cancelled:
                            self.kill_process_tree(proc)
                            self._cleanup_process_resources(proc, t_out, t_err)
                            end_time = datetime.now()
                            return ExecutorResult(
                                success=False,
                                exit_code=-1,
                                start_time=start_time,
                                end_time=end_time,
                                stdout_path=str(stdout_path),
                                stderr_path=str(stderr_path),
                                error_message="用户取消"
                            )
                        if not normal:
                            # 超时：与原 subprocess.TimeoutExpired 路径行为一致
                            raise subprocess.TimeoutExpired(cmd=str(script_path), timeout=timeout)
                    else:
                        if timeout is not None:
                            proc.wait(timeout=timeout)
                        else:
                            proc.wait()
                except subprocess.TimeoutExpired:
                    self.kill_process_tree(proc)
                    self._cleanup_process_resources(proc, t_out, t_err)
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
                
                t_out.join(timeout=10)
                t_err.join(timeout=10)
            
            end_time = datetime.now()
            exit_code = proc.returncode
            
            return ExecutorResult(
                success=(exit_code == 0),
                exit_code=exit_code,
                start_time=start_time,
                end_time=end_time,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                error_message=None
                if exit_code == 0
                else (
                    f"退出码: {exit_code}\n{stderr_excerpt}"
                    if (stderr_excerpt := _read_stderr_excerpt(stderr_path))
                    else f"退出码: {exit_code}"
                )
            )
            
        except Exception as e:
            if proc is not None and proc.poll() is None:
                self.kill_process_tree(proc)
                self._cleanup_process_resources(proc, t_out, t_err)
            end_time = datetime.now()
            return ExecutorResult(
                success=False,
                exit_code=-1,
                start_time=start_time,
                end_time=end_time,
                stdout_path=str(stdout_path) if stdout_path and stdout_path.exists() else None,
                stderr_path=str(stderr_path) if stderr_path and stderr_path.exists() else None,
                error_message=str(e)
            )
