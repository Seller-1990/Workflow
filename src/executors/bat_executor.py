# -*- coding: utf-8 -*-
"""批处理脚本执行器（.bat / .cmd）"""

import os
import sys
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from executors.base import BaseExecutor, ExecutorResult
from executors.result_policy import build_cancelled_extra
from runtime.process_runner import build_subprocess_kwargs, start_process
from constants import BAT_STEP_TIMEOUT


def _decode_line(raw: bytes) -> str:
    """解码输出行（Windows cmd 默认 GBK/CP936）"""
    for enc in ('gbk', 'cp936', 'utf-8', 'gb18030'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode('utf-8', errors='replace')


def _stream_pipe(pipe, file_obj, stream):
    """流式读取管道输出"""
    try:
        for raw_line in iter(pipe.readline, b''):
            if not raw_line:
                break
            decoded = _decode_line(raw_line)
            try:
                file_obj.write(decoded)
                file_obj.flush()
            except IOError:
                break
            try:
                stream.write(decoded)
                stream.flush()
            except Exception:
                pass
    except (IOError, OSError):
        pass


def _read_stderr_excerpt(stderr_path: Path, max_lines: int = 8, max_chars: int = 400) -> str:
    """读取 stderr 末尾摘要"""
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


class BatExecutor(BaseExecutor):
    """批处理脚本执行器（.bat / .cmd）"""

    SUPPORTED_SUFFIXES = {".bat", ".cmd"}
    STREAM_JOIN_TIMEOUT_SECONDS = 5
    COMMUNICATE_TIMEOUT_SECONDS = 3

    def _normalize_args(self, args: List[str] = None) -> List[str]:
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
        try:
            proc.communicate(timeout=self.COMMUNICATE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                proc.wait()
            except Exception:
                pass
        except Exception:
            pass
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
        cancel_event: threading.Event = None,
        **kwargs
    ) -> ExecutorResult:
        """执行批处理脚本

        Args:
            script_path: .bat/.cmd 脚本路径
            args: 命令行参数
            cwd: 工作目录
            env: 额外环境变量
            log_dir: 日志目录
            timeout: 超时时间（秒）；None 使用默认 BAT_STEP_TIMEOUT，0 不限制
            cancel_event: 取消事件

        Returns:
            ExecutorResult
        """
        stdout_path = None
        stderr_path = None

        script = self.get_absolute_path(script_path)
        if not script.exists():
            return ExecutorResult(success=False, exit_code=1, error_message=f"脚本不存在: {script}")
        if not script.is_file():
            return ExecutorResult(success=False, exit_code=1, error_message=f"脚本路径不是文件: {script}")
        if script.suffix.lower() not in self.SUPPORTED_SUFFIXES:
            return ExecutorResult(
                success=False, exit_code=1,
                error_message=f"不支持的脚本类型: {script.suffix or '无扩展名'}（需要 .bat 或 .cmd）",
            )

        try:
            work_dir = self._resolve_work_dir(script, cwd)
            args = self._normalize_args(args)
        except ValueError as e:
            return ExecutorResult(success=False, exit_code=1, error_message=str(e))

        log_dir, stdout_path, stderr_path = self.build_log_dir(log_dir)

        if timeout is None:
            timeout = BAT_STEP_TIMEOUT

        # 构建环境变量
        run_env = os.environ.copy()
        run_env['WORKFLOW_STEP_LOG_DIR'] = str(log_dir)
        if env:
            run_env.update(env)

        # cmd.exe /c 执行批处理
        cmd = ["cmd.exe", "/c", str(script)] + list(args)

        start_time = datetime.now()
        proc = None
        t_out = None
        t_err = None

        try:
            with open(stdout_path, 'w', encoding='utf-8-sig') as f_out, \
                 open(stderr_path, 'w', encoding='utf-8-sig') as f_err:
                f_out.write(f"[BatExecutor] script: {script}\n")

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

                t_out = threading.Thread(target=_stream_pipe, args=(proc.stdout, f_out, sys.stdout))
                t_err = threading.Thread(target=_stream_pipe, args=(proc.stderr, f_err, sys.stderr))
                try:
                    t_out.start()
                    t_err.start()
                except Exception:
                    self.kill_process_tree(proc)
                    self._cleanup_process_resources(proc, t_out, t_err)
                    proc = None
                    raise

                try:
                    if cancel_event:
                        normal, cancelled = self.wait_with_cancel(
                            proc, timeout or 0, cancel_event, check_interval=0.5
                        )
                        if cancelled:
                            self.kill_process_tree(proc)
                            self._cleanup_process_resources(proc, t_out, t_err)
                            return ExecutorResult(
                                success=False, exit_code=-1,
                                start_time=start_time, end_time=datetime.now(),
                                stdout_path=str(stdout_path), stderr_path=str(stderr_path),
                                error_message="用户取消",
                                extra=build_cancelled_extra(),
                            )
                        if not normal:
                            raise subprocess.TimeoutExpired(cmd=str(script_path), timeout=timeout)
                    else:
                        if timeout:
                            proc.wait(timeout=timeout)
                        else:
                            proc.wait()
                except subprocess.TimeoutExpired:
                    self.kill_process_tree(proc)
                    self._cleanup_process_resources(proc, t_out, t_err)
                    return ExecutorResult(
                        success=False, exit_code=-1,
                        start_time=start_time, end_time=datetime.now(),
                        stdout_path=str(stdout_path), stderr_path=str(stderr_path),
                        error_message=f"执行超时 ({timeout}秒)",
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
                ),
            )

        except Exception as e:
            if proc is not None and proc.poll() is None:
                self.kill_process_tree(proc)
                self._cleanup_process_resources(proc, t_out, t_err)
            return ExecutorResult(
                success=False, exit_code=-1,
                start_time=start_time, end_time=datetime.now(),
                stdout_path=str(stdout_path) if stdout_path and stdout_path.exists() else None,
                stderr_path=str(stderr_path) if stderr_path and stderr_path.exists() else None,
                error_message=str(e),
            )
