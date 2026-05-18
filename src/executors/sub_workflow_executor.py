# -*- coding: utf-8 -*-
"""子工作流执行器"""

import inspect
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import threading

from executors.base import BaseExecutor, ExecutorResult
from database import (
    get_workflow_by_uid, get_workflow_by_id,
    has_cross_workflow_cycle
)
from constants import SUB_WORKFLOW_TIMEOUT


class SubWorkflowExecutor(BaseExecutor):
    """子工作流执行器"""

    @staticmethod
    def _workflow_runner_accepts_cancel_event(workflow_runner) -> bool:
        """判断 workflow_runner 是否显式支持 cancel_event。"""
        try:
            signature = inspect.signature(workflow_runner)
        except (TypeError, ValueError):
            return False

        for param in signature.parameters.values():
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                return True
        return "cancel_event" in signature.parameters

    def execute(
        self,
        script_path: str,
        args: List[str] = None,
        cwd: str = None,
        env: Dict[str, str] = None,
        log_dir: Path = None,
        timeout: int = None,
        workflow_id: int = None,
        cancel_event: threading.Event = None,
        **kwargs
    ) -> ExecutorResult:
        if not script_path:
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message="未指定子工作流"
            )

        target = get_workflow_by_uid(script_path)
        if not target:
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message=f"未找到子工作流: {script_path}"
            )
        
        if workflow_id is not None:
            parent = get_workflow_by_id(workflow_id)
            if parent and parent.id == target.id:
                return ExecutorResult(
                    success=False,
                    exit_code=1,
                    error_message="禁止引用自身工作流"
                )
            if parent and has_cross_workflow_cycle(parent.id, target.uid):
                return ExecutorResult(
                    success=False,
                    exit_code=1,
                    error_message="检测到跨工作流循环依赖"
                )

        workflow_runner = kwargs.get("workflow_runner")
        if workflow_runner is None or not callable(workflow_runner):
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message="未提供子工作流运行器"
            )

        start_time = datetime.now()

        # 检查取消状态
        if cancel_event and cancel_event.is_set():
            return ExecutorResult(
                success=False,
                exit_code=-1,
                start_time=start_time,
                end_time=datetime.now(),
                error_message="用户取消"
            )

        # 使用线程执行子工作流以支持超时控制
        # H8 修复：
        # 1. 不再 future.result(timeout=...) 一把阻塞到超时，改为短轮询，及时响应外部 cancel_event。
        # 2. 给嵌套子工作流单独传 child_cancel_event，超时/取消时显式通知其尽快退出。
        import concurrent.futures
        child_cancel_event = threading.Event()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _invoke_runner():
            if self._workflow_runner_accepts_cancel_event(workflow_runner):
                return workflow_runner(
                    target.id,
                    reason="sub_workflow",
                    cancel_event=child_cancel_event,
                )
            return workflow_runner(target.id, reason="sub_workflow")

        future = executor.submit(_invoke_runner)
        # MA3：默认超时来自 constants.py
        actual_timeout = timeout if timeout else SUB_WORKFLOW_TIMEOUT
        try:
            deadline = time.monotonic() + actual_timeout
            while True:
                if cancel_event and cancel_event.is_set():
                    child_cancel_event.set()
                    return ExecutorResult(
                        success=False,
                        exit_code=-1,
                        start_time=start_time,
                        end_time=datetime.now(),
                        error_message="用户取消"
                    )

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    child_cancel_event.set()
                    return ExecutorResult(
                        success=False,
                        exit_code=-1,
                        start_time=start_time,
                        end_time=datetime.now(),
                        error_message=f"子工作流执行超时 ({actual_timeout}秒)"
                    )

                try:
                    ok = future.result(timeout=min(0.1, remaining))
                    break
                except concurrent.futures.TimeoutError:
                    continue
        finally:
            # 正常 / 取消 / 超时路径都不等待子线程这里同步回收；
            # 真正停止依赖 child_cancel_event，线程会在后台自行收尾。
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        end_time = datetime.now()

        # 再次检查取消状态（子工作流执行后）
        if cancel_event and cancel_event.is_set():
            child_cancel_event.set()
            return ExecutorResult(
                success=False,
                exit_code=-1,
                start_time=start_time,
                end_time=end_time,
                error_message="用户取消"
            )

        return ExecutorResult(
            success=ok,
            exit_code=0 if ok else 1,
            start_time=start_time,
            end_time=end_time,
            stdout_path=None,
            stderr_path=None,
            error_message=None if ok else "子工作流执行失败"
        )

    def validate(self, script_path: str) -> bool:
        if not script_path:
            return False
        return get_workflow_by_uid(script_path) is not None
