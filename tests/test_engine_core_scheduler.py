# -*- coding: utf-8 -*-
"""scheduler.run_steps_parallel 取消语义回归测试（P0-2 修复）。

并行批次中途取消时，所有步骤（含窗口内被取消、运行中被中断、尾部未提交）都必须
有对应结果条目，保证 ``len(results) == len(batch)``——否则调用方 zip(batch, results)
会错位、completed_steps 计数少计（进度"停住"）。
"""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine_core.scheduler import run_steps_parallel


class _Step:
    def __init__(self, sid: int, order: int):
        self.id = sid
        self.order = order
        self.name = f"step-{sid}"


def _ok(step):
    return SimpleNamespace(step_id=step.id, status="success", success=True)


def test_cancel_pads_results_to_batch_length():
    steps = [_Step(i, i) for i in range(10)]
    stop_event = threading.Event()

    def runner(step):
        time.sleep(0.03)  # 模拟耗时，让取消发生在部分步骤仍在途中/尚未提交时
        if step.id < 2:  # 前两个步骤完成后触发取消
            stop_event.set()
        return _ok(step)

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = run_steps_parallel(
            steps,
            executor=ex,
            max_workers=2,
            step_runner=runner,
            should_stop=stop_event.is_set,
        )

    assert len(results) == len(steps), (
        f"取消后结果条数应等于 batch 数: {len(results)} != {len(steps)}"
    )
    # 所有步骤都应有对应结果，且 id 覆盖无缺口
    assert {getattr(r, "step_id", None) for r in results} == {s.id for s in steps}
    # 应存在 cancelled 占位（尾部未提交/被取消的步骤）
    assert any(getattr(r, "status", None) == "cancelled" for r in results), (
        "取消场景应产出 cancelled 占位"
    )


def test_no_cancel_still_full_and_ordered():
    steps = [_Step(i, i) for i in range(6)]

    def runner(step):
        return _ok(step)

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = run_steps_parallel(
            steps, executor=ex, max_workers=2, step_runner=runner, should_stop=lambda: False
        )
    assert [getattr(r, "step_id", None) for r in results] == [s.id for s in steps]