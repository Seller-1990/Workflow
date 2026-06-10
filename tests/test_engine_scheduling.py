# -*- coding: utf-8 -*-
"""调度引擎分批逻辑单元测试

验证 _execute_steps 中「选择本轮执行批次」的正确性。
通过 Mock Step 对象模拟各种 DAG 场景，无需数据库交互。
"""

import sys
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

import pytest

# 将 src 加入搜索路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ───────────── Mock 对象 ─────────────

@dataclass
class MockStep:
    """模拟 Step 对象，仅保留调度所需字段"""
    id: int
    uid: str
    name: str
    order: int
    stage_uid: str | None = None
    is_gate: bool = False
    is_parallel: bool = False
    _depends_on: list = field(default_factory=list)

    def get_depends_on(self) -> list:
        return list(self._depends_on)


@dataclass
class MockWorkflow:
    """模拟 Workflow 对象"""
    parallel_enabled: bool = True
    max_workers: int = 4


@dataclass
class MockResult:
    """模拟 StepResult 对象，仅保留排序与断言所需字段"""
    step_id: int
    status: str = "success"


# ───────────── 调用真实实现（compute_batches 为真相源）─────────────

def compute_batches(
    workflow: MockWorkflow,
    steps: List[MockStep],
    stage_order_by_uid: dict[str, int] | None = None,
) -> List[List[str]]:
    """调用 engine.WorkflowEngine.compute_batches，并返回每批次的 uid 列表。"""
    from engine import WorkflowEngine
    batches = WorkflowEngine.compute_batches(workflow, steps, stage_order_by_uid or {})
    return [[s.uid for s in batch] for batch in batches]


# ───────────── 测试用例 ─────────────

class TestUserScenario:
    """用户场景：A→B∥C→D→E∥F∥G"""

    def _make_steps(self):
        return [
            MockStep(id=1, uid="A", name="步骤A", order=1, is_gate=True),
            MockStep(id=2, uid="B", name="步骤B", order=2, is_parallel=True, _depends_on=["A"]),
            MockStep(id=3, uid="C", name="步骤C", order=3, is_parallel=True, _depends_on=["A"]),
            MockStep(id=4, uid="D", name="步骤D", order=4, is_gate=True, _depends_on=["B", "C"]),
            MockStep(id=5, uid="E", name="步骤E", order=5, is_parallel=True, _depends_on=["D"]),
            MockStep(id=6, uid="F", name="步骤F", order=6, is_parallel=True, _depends_on=["D"]),
            MockStep(id=7, uid="G", name="步骤G", order=7, is_parallel=True, _depends_on=["D"]),
        ]

    def test_parallel_enabled(self):
        """验证并行模式下的正确分批"""
        wf = MockWorkflow(parallel_enabled=True)
        steps = self._make_steps()
        batches = compute_batches(wf, steps)

        assert batches == [
            ["A"],           # 阶段 1：Gate 单独执行
            ["B", "C"],      # 阶段 2：并行（同依赖 A）
            ["D"],           # 阶段 3：Gate 单独执行
            ["E", "F", "G"], # 阶段 4：并行（同依赖 D）
        ]

    def test_parallel_disabled(self):
        """验证非并行模式下全部串行"""
        wf = MockWorkflow(parallel_enabled=False)
        steps = self._make_steps()
        batches = compute_batches(wf, steps)

        # 非并行模式：每批只有一个步骤
        assert all(len(b) == 1 for b in batches)
        # 顺序：A→B→C→D→E→F→G（按 order 逐个）
        assert len(batches) == 7


class TestEdgeCases:
    """边界场景测试"""

    def test_single_step(self):
        """单步骤工作流"""
        wf = MockWorkflow(parallel_enabled=True)
        steps = [MockStep(id=1, uid="X", name="唯一步骤", order=1)]
        batches = compute_batches(wf, steps)
        assert batches == [["X"]]

    def test_all_serial_no_parallel_flag(self):
        """所有步骤都未标记并行"""
        wf = MockWorkflow(parallel_enabled=True)
        steps = [
            MockStep(id=1, uid="A", name="A", order=1),
            MockStep(id=2, uid="B", name="B", order=2, _depends_on=["A"]),
            MockStep(id=3, uid="C", name="C", order=3, _depends_on=["B"]),
        ]
        batches = compute_batches(wf, steps)
        assert batches == [["A"], ["B"], ["C"]]

    def test_mixed_parallel_and_serial_same_deps(self):
        """同依赖层级中混合并行和非并行步骤"""
        wf = MockWorkflow(parallel_enabled=True)
        steps = [
            MockStep(id=1, uid="A", name="A", order=1, is_gate=True),
            MockStep(id=2, uid="B", name="B", order=2, is_parallel=True, _depends_on=["A"]),
            MockStep(id=3, uid="C", name="C", order=3, is_parallel=True, _depends_on=["A"]),
            MockStep(id=4, uid="D", name="D", order=4, is_parallel=False, _depends_on=["A"]),
        ]
        batches = compute_batches(wf, steps)

        # 自动并行：同依赖层默认并行（不再区分 is_parallel 标记）
        assert batches[0] == ["A"]
        assert batches[1] == ["B", "C", "D"]

    def test_no_deps_multiple_parallel(self):
        """多个无依赖的并行步骤"""
        wf = MockWorkflow(parallel_enabled=True)
        steps = [
            MockStep(id=1, uid="A", name="A", order=1, is_parallel=True),
            MockStep(id=2, uid="B", name="B", order=2, is_parallel=True),
            MockStep(id=3, uid="C", name="C", order=3, is_parallel=True),
        ]
        batches = compute_batches(wf, steps)
        # 全部无依赖 → 依赖集合相同 → 一批并行
        assert batches == [["A", "B", "C"]]

    def test_different_deps_not_batched(self):
        """不同依赖的并行步骤不会混入同一批次"""
        wf = MockWorkflow(parallel_enabled=True)
        steps = [
            MockStep(id=1, uid="A", name="A", order=1),
            MockStep(id=2, uid="B", name="B", order=2),
            MockStep(id=3, uid="C", name="C", order=3, is_parallel=True, _depends_on=["A"]),
            MockStep(id=4, uid="D", name="D", order=4, is_parallel=True, _depends_on=["B"]),
        ]
        batches = compute_batches(wf, steps)

        # 自动并行：A、B 同为无依赖 → 同批；C 依赖 A、D 依赖 B → 不同依赖集 → 不混批
        assert batches[0] == ["A", "B"]
        assert "C" in batches[1] or "D" in batches[1]
        # C 和 D 不应在同一批次
        for b in batches:
            assert not ("C" in b and "D" in b)

    def test_circular_dependency_raises(self):
        """循环依赖应抛出异常"""
        wf = MockWorkflow(parallel_enabled=True)
        steps = [
            MockStep(id=1, uid="A", name="A", order=1, _depends_on=["B"]),
            MockStep(id=2, uid="B", name="B", order=2, _depends_on=["A"]),
        ]
        from engine import DependencyError
        with pytest.raises(DependencyError, match="依赖形成循环"):
            compute_batches(wf, steps)

    def test_gate_blocks_parallel_same_level(self):
        """Gate 步骤即使与其他并行步骤同层，也单独执行"""
        wf = MockWorkflow(parallel_enabled=True)
        steps = [
            MockStep(id=1, uid="A", name="A", order=1, is_gate=True, is_parallel=True),
            MockStep(id=2, uid="B", name="B", order=2, is_parallel=True),
            MockStep(id=3, uid="C", name="C", order=3, is_parallel=True),
        ]
        batches = compute_batches(wf, steps)
        # Gate 步骤 A 强制单独
        assert batches[0] == ["A"]
        # B、C 并行
        assert batches[1] == ["B", "C"]


class TestPurposeStages:
    """用途阶段（stage barrier）语义"""

    def test_stage_barrier_orders_stages(self):
        wf = MockWorkflow(parallel_enabled=True)
        steps = [
            MockStep(id=1, uid="A", name="A", order=1, stage_uid="s1"),
            MockStep(id=2, uid="B", name="B", order=2, stage_uid="s2"),
        ]
        stage_map = {"s1": 0, "s2": 1}
        batches = compute_batches(wf, steps, stage_map)
        assert batches == [["A"], ["B"]]

    def test_stage_barrier_parallel_within_stage(self):
        wf = MockWorkflow(parallel_enabled=True)
        steps = [
            MockStep(id=1, uid="A", name="A", order=1, stage_uid="s1"),
            MockStep(id=2, uid="B", name="B", order=2, stage_uid="s1"),
            MockStep(id=3, uid="C", name="C", order=3, stage_uid="s2"),
        ]
        stage_map = {"s1": 0, "s2": 1}
        batches = compute_batches(wf, steps, stage_map)
        assert batches[0] == ["A", "B"]
        assert batches[1] == ["C"]

    def test_future_stage_dependency_forbidden(self):
        wf = MockWorkflow(parallel_enabled=True)
        steps = [
            MockStep(id=1, uid="A", name="A", order=1, stage_uid="s1", _depends_on=["B"]),
            MockStep(id=2, uid="B", name="B", order=2, stage_uid="s2"),
        ]
        stage_map = {"s1": 0, "s2": 1}
        from engine import DependencyError
        with pytest.raises(DependencyError, match="跨阶段依赖不允许"):
            compute_batches(wf, steps, stage_map)


# ───────────── run_steps_parallel 滑动窗口调度（M6）─────────────

class TestRunStepsParallel:
    """run_steps_parallel 提交侧滑动窗口语义

    M6 修复：并发上限改由提交侧滑动窗口控制，等待执行的步骤
    不再占用共享池线程，嵌套子工作流可正常拿到线程。
    """

    @staticmethod
    def _make_steps(n: int) -> List[MockStep]:
        return [
            MockStep(id=i, uid=f"S{i}", name=f"步骤{i}", order=i)
            for i in range(1, n + 1)
        ]

    def test_window_caps_in_flight_concurrency(self):
        """max_workers=2 跑 6 个步骤：同时在跑的步骤数 <= 2，结果按 order 返回"""
        from engine_core.scheduler import run_steps_parallel

        steps = self._make_steps(6)
        lock = threading.Lock()
        in_flight = 0
        max_in_flight = 0

        def step_runner(step):
            nonlocal in_flight, max_in_flight
            with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            time.sleep(0.05)
            with lock:
                in_flight -= 1
            return MockResult(step_id=step.id)

        # 池容量（8）远大于窗口（2），若窗口失效会观察到 >2 的并发
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = run_steps_parallel(
                list(reversed(steps)),  # 故意乱序传入，验证按 order 排序而非完成/提交顺序
                executor=pool,
                max_workers=2,
                step_runner=step_runner,
            )

        assert max_in_flight <= 2
        assert [r.step_id for r in results] == [1, 2, 3, 4, 5, 6]

    def test_nested_submission_to_shared_pool_no_starvation(self):
        """步骤内部向同一共享池提交子任务并等待时不得死锁（池饥饿回归）

        旧实现一次性提交 3 个步骤到 2 线程池（信号量上限 1）：
        一个线程跑步骤并等子任务、另一个线程在信号量上阻塞等待，
        子任务永远拿不到线程 → 死锁。滑动窗口实现同一时刻只占 1 个
        池线程，剩余线程可服务嵌套子任务。子任务带 5 秒超时，
        回归时测试快速失败而不是挂死 pytest。
        """
        from engine_core.scheduler import run_steps_parallel

        steps = self._make_steps(3)

        with ThreadPoolExecutor(max_workers=2) as pool:
            def step_runner(step):
                # 模拟嵌套子工作流：占用同一共享池的一个槽位并等待结果
                inner = pool.submit(lambda: step.id * 10)
                assert inner.result(timeout=5) == step.id * 10
                return MockResult(step_id=step.id)

            results = run_steps_parallel(
                steps,
                executor=pool,
                max_workers=1,
                step_runner=step_runner,
            )

        assert [r.step_id for r in results] == [1, 2, 3]
        assert all(r.status == "success" for r in results)

    def test_on_exception_converts_step_failure(self):
        """步骤抛异常时走 on_exception 兜底，其余步骤结果不受影响"""
        from engine_core.scheduler import run_steps_parallel

        steps = self._make_steps(4)

        def step_runner(step):
            if step.id == 2:
                raise RuntimeError(f"步骤{step.id}失败")
            return MockResult(step_id=step.id)

        def on_exception(step, exc):
            return MockResult(step_id=step.id, status=f"failure:{exc}")

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = run_steps_parallel(
                steps,
                executor=pool,
                max_workers=2,
                step_runner=step_runner,
                on_exception=on_exception,
            )

        assert [r.step_id for r in results] == [1, 2, 3, 4]
        assert results[1].status == "failure:步骤2失败"
        assert all(r.status == "success" for r in results if r.step_id != 2)

    def test_exception_reraised_without_on_exception(self):
        """未提供 on_exception 时步骤异常原样向上抛"""
        from engine_core.scheduler import run_steps_parallel

        steps = self._make_steps(2)

        def step_runner(step):
            raise ValueError(f"boom-{step.id}")

        with ThreadPoolExecutor(max_workers=2) as pool:
            with pytest.raises(ValueError, match="boom-"):
                run_steps_parallel(
                    steps,
                    executor=pool,
                    max_workers=2,
                    step_runner=step_runner,
                )

    def test_empty_steps_returns_empty_list(self):
        """空步骤列表直接返回 []，不触碰线程池"""
        from engine_core.scheduler import run_steps_parallel

        results = run_steps_parallel(
            [],
            executor=None,  # 空列表分支不应使用 executor
            max_workers=4,
            step_runner=lambda s: s,
        )
        assert results == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
