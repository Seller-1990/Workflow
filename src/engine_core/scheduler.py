# -*- coding: utf-8 -*-
"""调度子系统：CA2 把"批步骤并行调度"从 engine.py 抽离

设计要点：
- 不依赖 QObject / 全局 engine 状态
- 调用方传入 ``step_runner`` 回调；本模块仅负责
  并发上限（BoundedSemaphore）、future 收集、异常封装、按 order 排序
- 异常路径通过 ``on_exception`` 由调用方决定如何转成 StepResult
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    """提交一批步骤到线程池并行执行，受 BoundedSemaphore 限制并发上限

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
    sem_size = max(1, min(max(1, int(max_workers)), len(steps)))
    sem = threading.BoundedSemaphore(sem_size)

    def _run_with_semaphore(step):
        with sem:
            return step_runner(step)

    futures = {executor.submit(_run_with_semaphore, s): s for s in steps}
    results: List[Any] = []
    for future in as_completed(futures):
        step = futures[future]
        try:
            results.append(future.result())
        except Exception as e:
            logger.warning("并行步骤执行异常: %s", e)
            if on_exception is None:
                raise
            results.append(on_exception(step, e))

    # 按原始 step.order 排序，避免 future 完成顺序打乱后续序列化
    # P-13: 缺 step_id 的 result 用 +inf 排队尾，避免误顶到首位
    step_order_map = {s.id: getattr(s, "order", 0) for s in steps}
    results.sort(key=lambda r: step_order_map.get(getattr(r, "step_id", None), float("inf")))
    return results
