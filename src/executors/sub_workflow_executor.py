# -*- coding: utf-8 -*-
"""子工作流执行器

R5（子工作流线程池饥饿修复）：
- 子工作流运行在独立 1 线程池上（threading.local 按线程隔离），不占父 run 步骤池；
- 深度预算：``subworkflow_depth`` 沿执行链显式透传（execute_step_attempt → 本
  execute → run_sub_workflow → _run），超过 ``MAX_SUBWORKFLOW_DEPTH`` 时 fail-fast
  返回 non-retryable 结果，不启动子线程、不创建 RunHistory；
- 并发预算：子工作流运行入口（engine._run）非阻塞获取引擎全局槽位，耗尽抛
  ``ResourceBudgetExceededError``，本执行器把它映射为 non-retryable 的中文资源
  错误结果（不触发父步骤重试）。
"""

import concurrent.futures
import inspect
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from executors.base import BaseExecutor, ExecutorResult
from executors.result_policy import ResultPolicyKeys, build_cancelled_extra, build_policy_extra
from database import (
    get_workflow_by_uid, get_workflow_by_id,
    has_cross_workflow_cycle
)
from constants import SUB_WORKFLOW_TIMEOUT, MAX_SUBWORKFLOW_DEPTH
from engine_core.scheduler import ResourceBudgetExceededError


class SubWorkflowExecutor(BaseExecutor):
    """子工作流执行器"""

    POLL_INTERVAL_SECONDS = 0.1
    CHILD_EXIT_GRACE_SECONDS = 0.2

    @staticmethod
    def _workflow_runner_accepts_cancel_event(workflow_runner) -> bool:
        """判断 workflow_runner 是否显式支持 cancel_event。"""
        return SubWorkflowExecutor._runner_accepts_param(workflow_runner, "cancel_event")

    @staticmethod
    def _runner_accepts_param(workflow_runner, param_name: str) -> bool:
        """判断 workflow_runner 是否显式支持指定参数（含 **kwargs）。"""
        try:
            signature = inspect.signature(workflow_runner)
        except (TypeError, ValueError):
            return False

        for param in signature.parameters.values():
            if param.kind == inspect.Parameter.VAR_KEYWORD:
                return True
        return param_name in signature.parameters

    def _wait_for_child_exit(
        self,
        future: concurrent.futures.Future,
        grace_seconds: float,
    ) -> bool:
        """在有限宽限期内确认子工作流线程已结束。"""
        try:
            future.result(timeout=max(0.0, float(grace_seconds)))
        except concurrent.futures.TimeoutError:
            return False
        except Exception:
            return True
        return True

    def _build_interrupted_result(
        self,
        *,
        start_time: datetime,
        child_cancel_event: threading.Event,
        future: concurrent.futures.Future,
        error_message: str,
        exit_code: int,
    ) -> ExecutorResult:
        """取消/超时后通知子工作流并验证其是否在宽限期内退出。"""
        child_cancel_event.set()
        child_exited = self._wait_for_child_exit(future, self.CHILD_EXIT_GRACE_SECONDS)
        end_time = datetime.now()
        if child_exited:
            return ExecutorResult(
                success=False,
                exit_code=exit_code,
                start_time=start_time,
                end_time=end_time,
                error_message=error_message,
                extra=build_cancelled_extra() if error_message == "用户取消" else {},
            )

        grace_text = f"{self.CHILD_EXIT_GRACE_SECONDS:g}"
        return ExecutorResult(
            success=False,
            exit_code=exit_code,
            start_time=start_time,
            end_time=end_time,
            error_message=f"{error_message}；子工作流未在 {grace_text} 秒宽限期内退出，存在后台运行风险",
            extra=build_policy_extra(
                cancelled=error_message == "用户取消",
                non_retryable=error_message == "用户取消",
                orphan_risk=True,
                background_risk=True,
                extra_fields={
                    ResultPolicyKeys.CHILD_EXIT_GRACE_SECONDS: self.CHILD_EXIT_GRACE_SECONDS,
                },
            ),
        )

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
        subworkflow_depth: int = 1,
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
        if not self._workflow_runner_accepts_cancel_event(workflow_runner):
            return ExecutorResult(
                success=False,
                exit_code=1,
                error_message="子工作流运行器必须显式支持 cancel_event 参数"
            )

        start_time = datetime.now()

        # R5: 深度预算——子工作流嵌套超过 MAX_SUBWORKFLOW_DEPTH 时 fail-fast，
        # 不启动子线程、不创建 RunHistory；non-retryable，避免父步骤无谓重试。
        if subworkflow_depth > MAX_SUBWORKFLOW_DEPTH:
            return ExecutorResult(
                success=False,
                exit_code=1,
                start_time=start_time,
                end_time=datetime.now(),
                error_message=(
                    f"子工作流嵌套深度超出限制（最大 {MAX_SUBWORKFLOW_DEPTH} 层），"
                    "请检查工作流是否构成过深嵌套"
                ),
                extra=build_policy_extra(non_retryable=True),
            )

        # 检查取消状态
        if cancel_event and cancel_event.is_set():
            return ExecutorResult(
                success=False,
                exit_code=-1,
                start_time=start_time,
                end_time=datetime.now(),
                error_message="用户取消",
                extra=build_cancelled_extra(),
            )

        # 使用线程执行子工作流以支持超时控制
        # H8 修复：
        # 1. 不再 future.result(timeout=...) 一把阻塞到超时，改为短轮询，及时响应外部 cancel_event。
        # 2. 给嵌套子工作流单独传 child_cancel_event，超时/取消时显式通知其尽快退出。
        child_cancel_event = threading.Event()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def _invoke_runner():
            # R5: 深度沿执行链显式透传——runner 支持时带上 subworkflow_depth
            # （engine.run_sub_workflow 支持；测试注入的 lambda 可能不支持则不传）。
            kwargs = {"reason": "sub_workflow", "cancel_event": child_cancel_event}
            if self._runner_accepts_param(workflow_runner, "subworkflow_depth"):
                kwargs["subworkflow_depth"] = subworkflow_depth
            return workflow_runner(target.id, **kwargs)

        future = executor.submit(_invoke_runner)
        # MA3：默认超时来自 constants.py
        actual_timeout = timeout if timeout else SUB_WORKFLOW_TIMEOUT
        try:
            deadline = time.monotonic() + actual_timeout
            while True:
                if cancel_event and cancel_event.is_set():
                    return self._build_interrupted_result(
                        start_time=start_time,
                        child_cancel_event=child_cancel_event,
                        future=future,
                        error_message="用户取消",
                        exit_code=-1,
                    )

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._build_interrupted_result(
                        start_time=start_time,
                        child_cancel_event=child_cancel_event,
                        future=future,
                        error_message=f"子工作流执行超时 ({actual_timeout}秒)",
                        exit_code=-1,
                    )

                try:
                    ok = future.result(timeout=min(self.POLL_INTERVAL_SECONDS, remaining))
                    break
                except concurrent.futures.TimeoutError:
                    continue
                except ResourceBudgetExceededError as e:
                    # R5: 子工作流资源预算耗尽（深度/并发超限）——明确中文资源错误，
                    # non-retryable，避免父步骤无谓重试；不当作普通执行异常。
                    child_cancel_event.set()
                    return ExecutorResult(
                        success=False,
                        exit_code=1,
                        start_time=start_time,
                        end_time=datetime.now(),
                        error_message=str(e),
                        extra=build_policy_extra(non_retryable=True),
                    )
                except Exception as e:
                    child_cancel_event.set()
                    return ExecutorResult(
                        success=False,
                        exit_code=1,
                        start_time=start_time,
                        end_time=datetime.now(),
                        error_message=f"子工作流执行异常: {e}",
                    )
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
            return self._build_interrupted_result(
                start_time=start_time,
                child_cancel_event=child_cancel_event,
                future=future,
                error_message="用户取消",
                exit_code=-1,
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
