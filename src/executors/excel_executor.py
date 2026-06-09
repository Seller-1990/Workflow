# -*- coding: utf-8 -*-
"""Excel PowerQuery 刷新执行器"""

import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from executors.base import BaseExecutor, ExecutorResult
from exceptions import WorkflowTimeoutError
from runtime.process_runner import run_process
from constants import EXCEL_REFRESH_TIMEOUT


def _run_async_query_wait(wait_method, completed_event, error_holder: list[Exception | None]) -> None:
    """在后台线程中执行 Excel 的阻塞等待，避免主线程失去取消/超时可达性。"""
    pythoncom = None
    try:
        try:
            import pythoncom as _pythoncom

            pythoncom = _pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pythoncom = None
        wait_method()
    except Exception as exc:
        error_holder.append(exc)
    finally:
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
        completed_event.set()


def _wait_for_refresh_completion(excel, workbook, timeout: int, cancel_event, log_messages: list[str]) -> None:
    """等待 Excel PowerQuery 刷新完成。"""
    start_wait = time.monotonic()
    poll_interval = 0.2

    wait_method = getattr(excel, "CalculateUntilAsyncQueriesDone", None)
    if callable(wait_method):
        log_messages.append(f"[{datetime.now().isoformat()}] 等待 Excel 异步查询完成...")
        completed_event = threading.Event()
        wait_errors: list[Exception | None] = []
        wait_thread = threading.Thread(
            target=_run_async_query_wait,
            args=(wait_method, completed_event, wait_errors),
            daemon=True,
        )
        wait_thread.start()

        while not completed_event.wait(timeout=poll_interval):
            if cancel_event and cancel_event.is_set():
                log_messages.append(f"[{datetime.now().isoformat()}] 用户取消，正在关闭 Excel...")
                raise WorkflowTimeoutError("用户取消")
            if timeout is not None and time.monotonic() - start_wait > timeout:
                raise WorkflowTimeoutError(f"刷新超时 ({timeout}秒)")

        if wait_errors:
            log_messages.append(
                f"[{datetime.now().isoformat()}] 异步查询等待失败，改为轮询: {wait_errors[-1]}"
            )

    while True:
        if cancel_event and cancel_event.is_set():
            log_messages.append(f"[{datetime.now().isoformat()}] 用户取消，正在关闭 Excel...")
            raise WorkflowTimeoutError("用户取消")

        if timeout is not None and time.monotonic() - start_wait > timeout:
            raise WorkflowTimeoutError(f"刷新超时 ({timeout}秒)")

        try:
            calc_state = getattr(excel, "CalculationState", None)
            if calc_state not in (None, 0):
                time.sleep(poll_interval)
                continue
        except Exception:
            pass

        try:
            if bool(getattr(workbook, "Refreshing")):
                time.sleep(poll_interval)
                continue
        except Exception:
            pass

        return


class ExcelExecutor(BaseExecutor):
    """Excel PowerQuery 刷新执行器
    
    使用 win32com 打开 Excel 文件并刷新所有数据连接。
    """
    
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
        """刷新 Excel 文件中的 PowerQuery
        
        Args:
            script_path: Excel 文件路径 (.xlsx, .xlsm)
            args: 未使用
            cwd: 未使用
            env: 未使用
            log_dir: 日志目录
            timeout: 超时时间（秒），默认 300 秒
            cancel_event: 取消事件
            
        Returns:
            ExecutorResult: 执行结果
        """
        # 解析路径
        excel_path = self.get_absolute_path(script_path)
        if not excel_path.exists():
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"Excel 文件不存在: {excel_path}"
            )
        
        # 检查文件扩展名
        if excel_path.suffix.lower() not in ('.xlsx', '.xlsm', '.xlsb', '.xls'):
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"不支持的文件格式: {excel_path.suffix}"
            )
        
        # 准备日志目录
        if log_dir is None:
            from config import LOG_DIR
            log_dir = LOG_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        stdout_path = log_dir / "stdout.txt"
        stderr_path = log_dir / "stderr.txt"
        
        # 默认超时（MA3：来自 constants.py）
        if timeout is None:
            timeout = EXCEL_REFRESH_TIMEOUT
        
        start_time = datetime.now()
        log_messages = []
        error_messages = []
        
        excel = None
        workbook = None
        pythoncom = None
        excel_pid: Optional[int] = None
        forced_kill = False

        try:
            import pythoncom
            import win32com.client

            # 初始化 COM
            pythoncom.CoInitialize()

            log_messages.append(f"[{datetime.now().isoformat()}] 开始刷新 Excel: {excel_path}")
            log_messages.append(f"[{datetime.now().isoformat()}] 超时设置: {timeout} 秒")

            # 启动 Excel
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False

            # 记录 Excel 进程 PID（H9 修复：用于取消/超时时 taskkill 兜底，避免 Excel 进程残留持文件锁）
            try:
                import win32process
                hwnd = excel.Hwnd
                _, excel_pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                excel_pid = None

            # 打开工作簿
            log_messages.append(f"[{datetime.now().isoformat()}] 正在打开工作簿...")
            workbook = excel.Workbooks.Open(str(excel_path))
            
            # 设置连接刷新属性
            for conn in workbook.Connections:
                try:
                    conn.OLEDBConnection.BackgroundQuery = False
                except Exception:
                    pass
            
            # 刷新所有数据
            log_messages.append(f"[{datetime.now().isoformat()}] 正在刷新数据连接...")
            workbook.RefreshAll()
            
            # 等待刷新完成（支持取消中断）
            _wait_for_refresh_completion(excel, workbook, timeout, cancel_event, log_messages)
            
            # 保存并关闭
            log_messages.append(f"[{datetime.now().isoformat()}] 正在保存工作簿...")
            workbook.Save()
            workbook.Close(SaveChanges=True)
            workbook = None  # 标记为已关闭
            
            log_messages.append(f"[{datetime.now().isoformat()}] 刷新完成")
            
            end_time = datetime.now()
            
            # 写入日志
            with open(stdout_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(log_messages))
            
            return ExecutorResult(
                success=True,
                exit_code=0,
                start_time=start_time,
                end_time=end_time,
                stdout_path=str(stdout_path),
                stderr_path=str(stderr_path)
            )
            
        except ImportError as e:
            error_messages.append(f"缺少依赖: {e}")
            error_messages.append("请安装 pywin32: pip install pywin32")
            
        except WorkflowTimeoutError as e:
            error_messages.append(str(e))
            
        except Exception as e:
            error_messages.append(f"刷新失败: {e}")
        
        finally:
            # 先尝试正常关闭工作簿（每个操作独立异常处理）
            if workbook:
                try:
                    workbook.Close(SaveChanges=False)
                except Exception:
                    pass
                finally:
                    workbook = None

            # 退出 Excel 应用（独立异常处理）
            if excel:
                try:
                    excel.Quit()
                except Exception:
                    pass
                finally:
                    excel = None

            # H9 修复：若取消或异常路径下 Excel.Quit() 失败导致进程残留，taskkill /F /PID 兜底
            # 仅当出现错误（取消/超时/RefreshAll 异常）时介入，正常路径下 Quit() 已经把进程清掉
            if excel_pid and error_messages:
                try:
                    run_process(
                        ["taskkill", "/F", "/T", "/PID", str(excel_pid)],
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )
                    forced_kill = True
                except Exception:
                    pass

            # 强制垃圾回收
            try:
                import gc
                gc.collect()
            except Exception:
                pass

            # 释放 COM（独立异常处理）
            if pythoncom:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

            # 再次垃圾回收确保 COM 对象完全释放
            try:
                import gc
                gc.collect()
            except Exception:
                pass

        if forced_kill:
            error_messages.append(f"已通过 taskkill 强制终止 Excel 进程 (PID={excel_pid})")
        
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
        """验证 Excel 文件路径"""
        if not script_path:
            return False
        path = Path(script_path)
        if not path.exists():
            return False
        return path.suffix.lower() in ('.xlsx', '.xlsm', '.xlsb', '.xls')
