# -*- coding: utf-8 -*-
"""调度子系统：CA2 把"批步骤并行调度"从 engine.py 抽离

设计要点：
- 不依赖 QObject / 全局 engine 状态
- 调用方传入 ``step_runner`` 回调；本模块仅负责
  并发上限、future 收集、异常封装、按 order 排序
- 并发上限由提交侧滑动窗口控制，不再用 BoundedSemaphore 占用池线程等待
  （M6：等待执行的步骤不占池线程，避免与嵌套子工作流争抢共享池导致饥饿/死锁）
- 异常路径通过 ``on_exception`` 由调用方决定如何转成 StepResult
- R5：短超时轮询等待（WAIT_POLL_SECONDS），无 future 完成事件时也能周期性
  观察 ``should_stop``，及时取消未启动的 future / 停止补提交
"""

from __future__ import annotations

import logging
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from constants import (
    WAIT_POLL_SECONDS,
    WORKFLOW_MAX_WORKERS_MIN,
    WORKFLOW_MAX_WORKERS_MAX,
    WORKFLOW_MAX_WORKERS_DEFAULT,
)

logger = logging.getLogger(__name__)


class ResourceBudgetExceededError(RuntimeError):
    """R5: 子工作流资源预算耗尽（嵌套深度超限 / 并发子工作流数量超限）。

    携带明确的中文资源错误信息；由 SubWorkflowExecutor 映射为 non-retryable
    的步骤失败（不触发重试、不创建新的 RunHistory），避免父步骤无谓重试。
    """


def normalize_workflow_max_workers(value) -> int:
    """R5: 执行期把 ``workflow.max_workers`` 夹紧到 [MIN, MAX] 并返回整数。

    - 缺失/非法/<=0 → ``WORKFLOW_MAX_WORKERS_DEFAULT``
    - 越界 → 夹紧并告警

    导入/UI 层校验归其它模块（R1/主会话范围）；执行期夹紧只保证线程资源不失控。
    """
    try:
        raw = int(value)
    except (TypeError, ValueError):
        raw = 0
    if raw <= 0:
        return WORKFLOW_MAX_WORKERS_DEFAULT
    clamped = min(max(raw, WORKFLOW_MAX_WORKERS_MIN), WORKFLOW_MAX_WORKERS_MAX)
    if clamped != raw:
        logger.warning(
            "workflow.max_workers=%s 超出允许范围 [%s, %s]，已夹紧为 %s",
            raw,
            WORKFLOW_MAX_WORKERS_MIN,
            WORKFLOW_MAX_WORKERS_MAX,
            clamped,
        )
    return clamped


class _CancelledResult:
    """取消步骤的占位结果（P0-2 修复）。

    并行批次中途取消时，被取消的步骤不应从结果中丢失，否则 ``zip(batch, results)``
    会把后续结果错配到前面被取消的步骤、``completed_steps += len(results)`` 少计
    （进度"停住"）。本占位使 ``len(results) == len(batch)`` 恒成立。

    刻意不 import engine.StepResult（调度模块是纯调度、不自也不该反向依赖 engine，
    避免链式循环 import）；仅携带调用方消费所需字段，语义与 StepResult 对齐：
    - ``status == "cancelled"`` → 调用方视为取消，立即短路退出
    - ``success is False`` → 与 StepResult.success 属性（non-``{success,skipped}``）一致
    - ``step_id`` → 供按 order 排序时归位
    """

    def __init__(self) -> None:
        self.step_id = None
        self.status = "cancelled"
        self.success = False
        self.error_message = None


@dataclass
class SchedulerMetrics:
    """Lightweight counters for one parallel scheduling batch."""

    submitted: int = 0
    completed: int = 0
    cancelled: int = 0
    failed: int = 0


def run_steps_parallel(
    steps: List[Any],
    *,
    executor: ThreadPoolExecutor,
    max_workers: int,
    step_runner: Callable[[Any], Any],
    on_exception: Optional[Callable[[Any, Exception], Any]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    metrics: SchedulerMetrics | None = None,
) -> List[Any]:
    """提交一批步骤到线程池并行执行，由提交侧滑动窗口限制并发上限

    M6: 旧实现一次性提交全部步骤，超出 max_workers 的任务在
    BoundedSemaphore 上等待时仍占用池线程；共享池被等待者占满后，
    嵌套子工作流拿不到线程，可能互相等待形成死锁。现改为滑动窗口：
    先提交首个窗口，每完成一个再补提交一个，在池中的任务数始终
    不超过窗口大小，任何任务都不会在池内阻塞等槽位。

    Args:
        steps: 步骤序列（任意带 ``id`` / ``order`` 属性的对象）
        executor: 共享的 ThreadPoolExecutor（通常来自 engine._executor）
        max_workers: 并发上限（来自 workflow.max_workers）
        step_runner: 单步执行回调，返回 StepResult-like 对象
        on_exception: 单步 raise 时的兜底处理；不传则原样向上抛
        should_stop: 返回 True 时停止提交后续步骤，并尝试取消尚未开始的 future

    Returns:
        list: 按 step.order 排好序的结果列表
    """
    if not steps:
        return []
    pending = list(steps)
    window = min(max(1, int(max_workers)), len(pending))

    def _stop_requested() -> bool:
        return bool(should_stop and should_stop())

    metrics = metrics or SchedulerMetrics()

    def _submit(step: Any) -> Future:
        metrics.submitted += 1
        return executor.submit(step_runner, step)

    def _cancel_not_started(futures_by_future: dict[Future, Any]) -> None:
        for pending_future in list(futures_by_future):
            if pending_future.cancel():
                metrics.cancelled += 1
                step = futures_by_future.pop(pending_future, None)
                if step is not None:
                    # P0-2: 被取消的步骤补 cancelled 占位，保证结果条数与 batch 一致。
                    cancelled = _CancelledResult()
                    cancelled.step_id = getattr(step, "id", None)
                    results.append(cancelled)

    if _stop_requested():
        return []

    # 滑动窗口：先提交首个窗口；每收割一个完成的 future 再补提交一个
    futures = {_submit(s): s for s in pending[:window]}
    next_idx = window
    results: List[Any] = []
    stop_submitting = False

    def _stop_submitting_and_pad_tail() -> None:
        """停止补提交 + 取消未启动 futures + 尾部补 cancelled 占位（幂等）。

        - 未启动 futures 用 future.cancel() 取消，计入 metrics.cancelled
        - 被取消 / 未提交的尾部步骤补 _CancelledResult 占位，
          保证 len(results) == len(pending)（调用方按 batch 配对不错位）
        """
        nonlocal next_idx
        _cancel_not_started(futures)
        for unsubmitted in pending[next_idx:]:
            cancelled = _CancelledResult()
            cancelled.step_id = getattr(unsubmitted, "id", None)
            results.append(cancelled)
        next_idx = len(pending)

    while futures:
        # R5: 短超时轮询等待——没有任何 future 完成时，wait 也会在
        # WAIT_POLL_SECONDS 后返回，让 should_stop 能及时被观察（取消未启动
        # futures / 停止补提交），而不是阻塞在无超时 wait 上等一个完成事件。
        done, _ = wait(futures, timeout=WAIT_POLL_SECONDS, return_when=FIRST_COMPLETED)
        if not stop_submitting and _stop_requested():
            stop_submitting = True
            _stop_submitting_and_pad_tail()
        for future in done:
            step = futures.pop(future)
            if future.cancelled():
                metrics.cancelled += 1
                # P0-2: 与 _cancel_not_started 同理，取消的 future 也要补占位，避免结果错位。
                cancelled = _CancelledResult()
                cancelled.step_id = getattr(step, "id", None)
                results.append(cancelled)
                continue
            try:
                results.append(future.result())
                metrics.completed += 1
            except Exception as e:
                logger.warning("并行步骤执行异常: %s", e)
                metrics.failed += 1
                metrics.completed += 1
                if on_exception is None:
                    raise
                results.append(on_exception(step, e))
            if _stop_requested():
                stop_submitting = True
                _stop_submitting_and_pad_tail()
            if not stop_submitting and next_idx < len(pending):
                nxt = pending[next_idx]
                next_idx += 1
                futures[_submit(nxt)] = nxt

    # 按原始 step.order 排序，避免 future 完成顺序打乱后续序列化
    # P-13: 缺 step_id 的 result 用 +inf 排队尾，避免误顶到首位
    step_order_map = {s.id: getattr(s, "order", 0) for s in pending}
    results.sort(key=lambda r: step_order_map.get(getattr(r, "step_id", None), float("inf")))
    return results
