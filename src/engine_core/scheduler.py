# -*- coding: utf-8 -*-
"""调度子系统：CA2 把"批步骤并行调度"从 engine.py 抽离

设计要点：
- 不依赖 QObject / 全局 engine 状态
- 调用方传入 ``step_runner`` 回调；本模块仅负责
  并发上限、future 收集、异常封装、按 order 排序
- 并发上限由提交侧滑动窗口控制，不再用 BoundedSemaphore 占用池线程等待
  （M6：等待执行的步骤不占池线程，避免与嵌套子工作流争抢共享池导致饥饿/死锁）
- 异常路径通过 ``on_exception`` 由调用方决定如何转成 StepResult
"""

from __future__ import annotations

import logging
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


def run_steps_parallel(
    steps: List[Any],
    *,
    executor: ThreadPoolExecutor,
    max_workers: int,
    step_runner: Callable[[Any], Any],
    on_exception: Optional[Callable[[Any, Exception], Any]] = None,
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

    Returns:
        list: 按 step.order 排好序的结果列表
    """
    if not steps:
        return []
    pending = list(steps)
    window = min(max(1, int(max_workers)), len(pending))

    # 滑动窗口：先提交首个窗口；每收割一个完成的 future 再补提交一个
    futures = {executor.submit(step_runner, s): s for s in pending[:window]}
    next_idx = window
    results: List[Any] = []
    while futures:
        done, _ = wait(futures, return_when=FIRST_COMPLETED)
        for future in done:
            step = futures.pop(future)
            try:
                results.append(future.result())
            except Exception as e:
                logger.warning("并行步骤执行异常: %s", e)
                if on_exception is None:
                    raise
                results.append(on_exception(step, e))
            if next_idx < len(pending):
                nxt = pending[next_idx]
                next_idx += 1
                futures[executor.submit(step_runner, nxt)] = nxt

    # 按原始 step.order 排序，避免 future 完成顺序打乱后续序列化
    # P-13: 缺 step_id 的 result 用 +inf 排队尾，避免误顶到首位
    step_order_map = {s.id: getattr(s, "order", 0) for s in pending}
    results.sort(key=lambda r: step_order_map.get(getattr(r, "step_id", None), float("inf")))
    return results
