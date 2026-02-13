# -*- coding: utf-8 -*-
"""调度引擎分批逻辑单元测试

验证 _execute_steps 中「选择本轮执行批次」的正确性。
通过 Mock Step 对象模拟各种 DAG 场景，无需数据库交互。
"""

import sys
import json
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
