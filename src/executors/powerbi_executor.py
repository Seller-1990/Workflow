# -*- coding: utf-8 -*-
"""Power BI Desktop 刷新执行器"""

import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from executors.base import BaseExecutor, ExecutorResult
from executors.result_policy import ResultPolicyKeys, build_policy_extra
from runtime.process_runner import start_process
from constants import POWERBI_REFRESH_TIMEOUT


def _kill_process_tree(proc):
    """终止进程及其所有子进程

    M5 修复：Power BI Desktop 启动后会 fork msmdsrv / Microsoft.Mashup.Container 子进程；
    若 launcher 已退出，子进程成为孤儿仍占文件锁。先用 taskkill /T 杀进程树，
    再按当前进程树中捕获到的子进程做有限兜底，避免误杀其它 Power BI 实例。

    MA1：通用 taskkill / proc.kill 已迁移到 BaseExecutor.kill_process_tree；
    本函数仅保留 Power BI 特定的树内残余进程兜底。
    """
    child_pids = []
    if sys.platform == "win32":
        try:
            import psutil

            parent = psutil.Process(proc.pid)
            child_pids = [child.pid for child in parent.children(recursive=True)]
        except Exception:
            child_pids = []

    BaseExecutor.kill_process_tree(proc)

    if sys.platform == "win32" and child_pids:
        try:
            import psutil

            for pid in child_pids:
                try:
                    child = psutil.Process(pid)
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except ImportError:
            pass
        except Exception:
            pass


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

    @staticmethod
    def _read_pbix_mtime_ns(pbix_path: Path) -> tuple[Optional[int], Optional[str]]:
        """读取 PBIX 文件 mtime（纳秒）用于保存证明。"""
        try:
            return pbix_path.stat().st_mtime_ns, None
        except OSError as exc:
            return None, str(exc)

    def _evaluate_success_proof(
        self,
        pbix_path: Path,
        initial_mtime_ns: Optional[int],
        mtime_proof_enabled: bool,
    ) -> Dict[str, object]:
        """评估 Power BI 刷新后的成功证明。"""
        if not mtime_proof_enabled:
            return {
                "verified": False,
                "proof_reason": "pbix_mtime_proof_disabled",
                "message": "Power BI 已关闭，但当前步骤已禁用 PBIX 保存证明",
                "note": "已禁用 PBIX mtime 成功证明，需人工确认刷新、保存并关闭",
            }

        if initial_mtime_ns is None:
            return {
                "verified": False,
                "proof_reason": "pbix_mtime_unavailable_before_refresh",
                "message": "Power BI 已关闭，但刷新前无法读取 PBIX 保存时间",
                "note": "刷新前未读取到 PBIX mtime，无法用文件保存时间证明刷新成功",
            }

        current_mtime_ns, error = self._read_pbix_mtime_ns(pbix_path)
        if current_mtime_ns is None:
            return {
                "verified": False,
                "proof_reason": "pbix_mtime_unavailable_after_refresh",
                "message": "Power BI 已关闭，但刷新后无法读取 PBIX 保存时间",
                "note": f"刷新后未读取到 PBIX mtime，无法证明刷新成功: {error}",
            }

        if current_mtime_ns != initial_mtime_ns:
            return {
                "verified": True,
                "proof_type": "pbix_mtime_changed",
                "initial_mtime_ns": initial_mtime_ns,
                "current_mtime_ns": current_mtime_ns,
            }

        return {
            "verified": False,
            "proof_reason": "pbix_mtime_unchanged",
            "message": "Power BI 已关闭，但当前步骤缺少刷新成功证明",
            "note": "PBIX 文件保存时间未变化，无法证明刷新后已保存",
        }
    
    def find_pbidesktop(self) -> Optional[str]:
        """查找 Power BI Desktop 可执行文件"""
        for command in ("PBIDesktop.exe", "PBIDesktop"):
            executable = shutil.which(command)
            if executable:
                return executable
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
        cancel_event: threading.Event = None,
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
        mtime_proof_enabled = True
        if args:
            for arg in args:
                if arg == "--no-auto-close":
                    auto_close = False
                if arg == "--no-auto-refresh":
                    auto_refresh = False
                if arg == "--disable-mtime-proof":
                    mtime_proof_enabled = False

        # 默认超时（MA3：来自 constants.py）
        if timeout is None:
            timeout = POWERBI_REFRESH_TIMEOUT
        
        start_time = datetime.now()
        log_messages = []
        error_messages = []
        proc = None

        def _write_logs() -> None:
            with open(stdout_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(log_messages))
            with open(stderr_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(error_messages))

        def _build_manual_required_result(
            end_time: datetime,
            message: str,
            note: str,
            background_risk: bool = False,
            extra_fields: Optional[Dict[str, object]] = None,
        ) -> ExecutorResult:
            extra = build_policy_extra(
                manual_required=True,
                background_risk=background_risk if background_risk else None,
                note=note,
                extra_fields=extra_fields,
            )
            _write_logs()
            return ExecutorResult(
                success=False,
                exit_code=2,
                start_time=start_time,
                end_time=end_time,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path),
                error_message=message,
                extra=extra,
            )
        
        try:
            log_messages.append(f"[{datetime.now().isoformat()}] 开始刷新 Power BI: {pbix_path}")
            log_messages.append(f"[{datetime.now().isoformat()}] Power BI Desktop: {pbidesktop}")
            log_messages.append(f"[{datetime.now().isoformat()}] 超时设置: {timeout} 秒")
            initial_mtime_ns = None
            if mtime_proof_enabled:
                initial_mtime_ns, initial_mtime_error = self._read_pbix_mtime_ns(pbix_path)
                if initial_mtime_ns is None:
                    log_messages.append(
                        f"[{datetime.now().isoformat()}] 刷新前无法读取 PBIX mtime，后续不能用保存时间证明成功: {initial_mtime_error}"
                    )
                else:
                    log_messages.append(
                        f"[{datetime.now().isoformat()}] 已记录刷新前 PBIX mtime(ns): {initial_mtime_ns}"
                    )
            else:
                log_messages.append(f"[{datetime.now().isoformat()}] 已禁用 PBIX mtime 成功证明")
            
            # 启动 Power BI Desktop 并打开文件
            # 注意：Power BI Desktop 不支持静默刷新，需要用户交互
            log_messages.append(f"[{datetime.now().isoformat()}] 正在打开文件...")
            
            # 使用 shell 打开（调用默认程序）
            proc = start_process(
                [pbidesktop, str(pbix_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            
            # 等待一段时间让 Power BI 加载
            wait_time = min(30, timeout)
            log_messages.append(f"[{datetime.now().isoformat()}] 等待 Power BI 加载 ({wait_time}秒)...")
            if BaseExecutor.sleep_with_cancel(wait_time, cancel_event, chunk=1.0):
                log_messages.append(f"[{datetime.now().isoformat()}] 用户取消，尝试关闭 Power BI...")
                _kill_process_tree(proc)
                end_time = datetime.now()
                with open(stdout_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(log_messages))
                with open(stderr_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(error_messages))
                return ExecutorResult(
                    success=False,
                    exit_code=-1,
                    start_time=start_time,
                    end_time=end_time,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    error_message="用户取消"
                )

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
                refresh_requested = self._try_auto_refresh(pbidesktop, log_messages, error_messages, pid=proc.pid)
                if not refresh_requested:
                    log_messages.append("自动刷新未成功触发，步骤按失败处理。")
                    _kill_process_tree(proc)
                    end_time = datetime.now()
                    _write_logs()
                    return ExecutorResult(
                    success=False,
                    exit_code=1,
                    start_time=start_time,
                    end_time=end_time,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    error_message="\n".join(error_messages) or "Power BI 自动刷新未成功触发",
                    extra=build_policy_extra(
                        manual_required=False,
                        note="自动刷新未成功触发",
                    ),
                    )
            else:
                log_messages.append("已关闭自动刷新（--no-auto-refresh）")
                log_messages.append("请在 Power BI Desktop 中手动点击'刷新'按钮。")
                log_messages.append("刷新完成后请保存并关闭文件。")
                error_messages.append("Power BI 需要人工刷新确认，当前执行器无法自动判定刷新成功")
            
            if auto_close:
                log_messages.append("")
                log_messages.append(f"[{datetime.now().isoformat()}] 等待用户完成刷新并关闭 Power BI...")

                remaining = timeout - wait_time
                cancelled = False
                timed_out = False
                if remaining <= 0:
                    timed_out = True
                else:
                    # MA1: 改用 BaseExecutor.wait_with_cancel 统一等待语义
                    normal, cancelled = BaseExecutor.wait_with_cancel(
                        proc, int(remaining), cancel_event, check_interval=1.0
                    )
                    if cancelled:
                        log_messages.append(f"[{datetime.now().isoformat()}] 用户取消，尝试关闭 Power BI...")
                        _kill_process_tree(proc)
                    elif normal:
                        log_messages.append(f"[{datetime.now().isoformat()}] Power BI 已关闭")
                    else:
                        timed_out = True

                if timed_out:
                    log_messages.append(f"[{datetime.now().isoformat()}] 等待超时 ({timeout}秒)，强制关闭 Power BI...")
                    error_messages.append(f"等待超时 ({timeout}秒)，Power BI 可能未完成刷新")
                    _kill_process_tree(proc)

                if cancelled or timed_out:
                    end_time = datetime.now()
                    with open(stdout_path, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(log_messages))
                    with open(stderr_path, 'w', encoding='utf-8') as f:
                        f.write('\n'.join(error_messages))
                    return ExecutorResult(
                        success=False,
                        exit_code=-1,
                        start_time=start_time,
                        end_time=end_time,
                        stdout_path=str(stdout_path),
                        stderr_path=str(stderr_path),
                        error_message="用户取消" if cancelled else f"等待超时 ({timeout}秒)"
                    )

            end_time = datetime.now()
            completed_returncode = proc.returncode
            if completed_returncode is None and proc.poll() is not None:
                completed_returncode = proc.returncode

            if not auto_close:
                log_messages.append("已关闭自动关闭（--no-auto-close）")
                log_messages.append("Power BI Desktop 将保持打开，当前执行器无法确认刷新完成。")
                error_messages.append("Power BI 未自动关闭，存在后台进程与刷新未确认风险")
                return _build_manual_required_result(
                    end_time=end_time,
                    message="Power BI 未自动关闭，当前步骤无法确认刷新完成",
                    note="Power BI 保持打开，需人工确认刷新、保存并关闭",
                    background_risk=True,
                )

            if completed_returncode not in (None, 0):
                error_messages.append(f"Power BI 异常退出，退出码: {completed_returncode}")
                _write_logs()
                return ExecutorResult(
                    success=False,
                    exit_code=completed_returncode,
                    start_time=start_time,
                    end_time=end_time,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    error_message='\n'.join(error_messages),
                )

            proof_result = self._evaluate_success_proof(
                pbix_path=pbix_path,
                initial_mtime_ns=initial_mtime_ns,
                mtime_proof_enabled=mtime_proof_enabled,
            )
            if proof_result["verified"]:
                proof_type = str(proof_result["proof_type"])
                log_messages.append(
                    f"[{datetime.now().isoformat()}] 刷新成功证明通过: {proof_type} "
                    f"({proof_result['initial_mtime_ns']} -> {proof_result['current_mtime_ns']})"
                )
                _write_logs()
                return ExecutorResult(
                    success=True,
                    exit_code=0,
                    start_time=start_time,
                    end_time=end_time,
                    stdout_path=str(stdout_path),
                    stderr_path=str(stderr_path),
                    extra={"proof_type": proof_type},
                )

            if not auto_refresh:
                error_messages.append("Power BI 需要人工刷新确认，当前步骤未自动确认成功")
                return _build_manual_required_result(
                    end_time=end_time,
                    message="Power BI 需要人工刷新确认，当前步骤未自动确认成功",
                    note="需要人工刷新确认",
                )

            if completed_returncode is None:
                log_messages.append("Power BI 进程已结束，但未取得明确退出码。")
                log_messages.append(
                    f"[{datetime.now().isoformat()}] 刷新成功证明未通过: {proof_result['proof_reason']}"
                )
                error_messages.append(str(proof_result["message"]))
                return _build_manual_required_result(
                    end_time=end_time,
                    message=str(proof_result["message"]),
                    note=str(proof_result["note"]),
                    extra_fields={ResultPolicyKeys.PROOF_REASON: proof_result["proof_reason"]},
                )

            log_messages.append(
                f"[{datetime.now().isoformat()}] 刷新成功证明未通过: {proof_result['proof_reason']}"
            )
            error_messages.append(str(proof_result["message"]))
            return _build_manual_required_result(
                end_time=end_time,
                message=str(proof_result["message"]),
                note=str(proof_result["note"]),
                extra_fields={ResultPolicyKeys.PROOF_REASON: proof_result["proof_reason"]},
            )
            
        except Exception as e:
            if proc is not None:
                try:
                    if proc.poll() is None:
                        log_messages.append(
                            f"[{datetime.now().isoformat()}] 发生未预期异常，尝试清理 Power BI 进程树..."
                        )
                        _kill_process_tree(proc)
                    else:
                        log_messages.append(
                            f"[{datetime.now().isoformat()}] 发生未预期异常，但 Power BI 进程已退出，跳过进程树清理"
                        )
                except Exception as cleanup_exc:
                    error_messages.append(f"异常兜底清理失败: {cleanup_exc}")
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

    def _try_auto_refresh(self, pbidesktop: str, log_messages: list, error_messages: list, pid: Optional[int] = None) -> bool:
        """尝试自动刷新（需要 pywinauto）

        M4 修复：优先按 process=pid 连接，避免多个 PBIDesktop.exe 实例下抓到错的窗口。
        """
        try:
            from pywinauto import Application
            if pid:
                try:
                    app = Application(backend="uia").connect(process=pid, timeout=10)
                except Exception as exc:
                    log_messages.append(f"按进程 PID 连接 Power BI 失败，回退按路径连接: pid={pid}, error={exc}")
                    app = Application(backend="uia").connect(path=pbidesktop, timeout=10)
            else:
                app = Application(backend="uia").connect(path=pbidesktop, timeout=10)
            window = app.top_window()
            window.set_focus()
            window.type_keys("{F5}")
            log_messages.append("已发送刷新快捷键(F5)")
            return True
        except ImportError:
            error_messages.append("未安装 pywinauto，无法自动刷新")
        except Exception as e:
            error_messages.append(f"自动刷新失败: {e}")
        return False
