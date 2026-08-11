# -*- coding: utf-8 -*-
"""R5: 子工作流线程池饥饿与取消修复测试（设计 §3 R5 重建）。

覆盖：
1. 每 run 独立步骤池：小池根层并行 2 个子工作流完成，池按 run 隔离创建/关闭
   （threading.local 绑定 run 线程；嵌套子工作流不回父 run / 全局共享池）
2. 深度预算：三层嵌套叶子只执行一次 + 全终态 + 深度沿执行链正确透传
3. 根取消穿透：无新 leaf start，运行有界返回
4. scheduler 短超时轮询：无完成事件时也能观察取消（有界返回，不挂死）
5. 并发预算：耗尽明确失败不挂死、不创建 RunHistory、non-retryable
6. 合作式取消顺序：cancel_seen → child_finished → parent_returned
7. 不合作式：保留 BACKGROUND_RISK / ORPHAN_RISK 风险结果；
   预算槽位在 child finalization 释放（而非 executor 放弃等待时）
8. 池生命周期：异常路径无泄漏、重复 run 创建全新池
"""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from constants import MAX_ACTIVE_SUBWORKFLOWS
from engine import RunMode, RunSignalPolicy, WorkflowEngine
from engine_core.run_finalization import get_run_thread_context
from engine_core.scheduler import ResourceBudgetExceededError, normalize_workflow_max_workers
from executors.base import ExecutorResult
from executors.result_policy import ResultPolicyKeys, build_cancelled_extra
from executors.sub_workflow_executor import SubWorkflowExecutor


# ───────────── 伪件基础设施 ─────────────

def _wf(wid, uid, name, max_workers=1, parallel_enabled=True):
    return SimpleNamespace(
        id=wid, uid=uid, name=name, max_workers=max_workers,
        parallel_enabled=parallel_enabled, log_retention_days=30,
        chart_theme="", single_script_enabled=False,
        get_notify_config=lambda: {},
    )


def _step(sid, uid, order, step_type, script_path, workflow_id, name=None):
    return SimpleNamespace(
        id=sid, uid=uid, order=order, name=name or f"步骤{order}",
        step_type=step_type, script_path=script_path, cwd="", chart_theme="",
        timeout_seconds=30, retry_count=0, workflow_id=workflow_id,
        get_args=lambda: [], get_depends_on=lambda: [],
        stage_uid=None, is_gate=False,
    )


class _OkExecutor:
    """普通步骤执行器：立即成功（可挂 on_execute 钩子）。"""

    def __init__(self, on_execute=None):
        self.on_execute = on_execute

    def execute(self, **kwargs):
        if self.on_execute:
            self.on_execute(kwargs)
        return ExecutorResult(success=True, exit_code=0)


class _CancelAwareExecutor:
    """合作式步骤执行器：等待 cancel_event，取消时返回 cancelled 结果。"""

    def __init__(self, on_started=None, on_cancel=None, wait_seconds=5.0):
        self.on_started = on_started
        self.on_cancel = on_cancel
        self.wait_seconds = wait_seconds

    def execute(self, **kwargs):
        if self.on_started:
            self.on_started(kwargs)
        cancel_event = kwargs.get("cancel_event")
        if cancel_event is not None:
            cancel_event.wait(self.wait_seconds)
        if cancel_event is not None and cancel_event.is_set():
            if self.on_cancel:
                self.on_cancel()
            return ExecutorResult(
                success=False, exit_code=-1,
                error_message="用户取消", extra=build_cancelled_extra(),
            )
        return ExecutorResult(success=True, exit_code=0)


class _StubbornExecutor:
    """不合作式步骤执行器：无视 cancel_event，睡满 duration 后返回成功。"""

    def __init__(self, duration=0.5):
        self.duration = duration

    def execute(self, **kwargs):
        time.sleep(self.duration)
        return ExecutorResult(success=True, exit_code=0)


class _PoolRecorder:
    """包装 ThreadPoolExecutor 的工厂，记录每个 run 池的创建/关闭与线程归属。"""

    def __init__(self):
        self.created = []
        self.shutdowns = []
        self._real = ThreadPoolExecutor

    def __call__(self, *args, **kwargs):
        record = {
            "max_workers": kwargs.get("max_workers"),
            "creator_thread": threading.get_ident(),
            "t": time.monotonic(),
        }
        self.created.append(record)
        pool = self._real(*args, **kwargs)
        orig_shutdown = pool.shutdown

        def _shutdown(*sa, **skw):
            self.shutdowns.append(record)
            return orig_shutdown(*sa, **skw)

        pool.shutdown = _shutdown
        return pool


def _quiet_policy():
    return RunSignalPolicy(
        emit_run_signals=False, emit_step_signals=False,
        emit_progress_signals=False, emit_error_details=False,
        send_notification=False,
    )


def _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow, lifecycle_records=None):
    """安装一套完整可跑的 engine 运行 DB/生命周期伪件（R1 的 risk 校验一并绕过）。"""
    monkeypatch.setattr("engine.LOG_DIR", tmp_path)
    monkeypatch.setattr("engine_core.lifecycle.LOG_DIR", tmp_path)
    monkeypatch.setattr("engine.get_workflow_by_id", lambda wid: workflows.get(wid))
    monkeypatch.setattr("engine.get_steps_by_workflow", lambda wid: steps_by_workflow.get(wid, []))
    monkeypatch.setattr("engine.get_stage_order_map", lambda wid: {})
    monkeypatch.setattr("engine.list_stages", lambda wid: [])
    monkeypatch.setattr("engine.create_step_log", lambda run_history_id, step_id, order: SimpleNamespace(id=step_id * 1000 + order))
    monkeypatch.setattr("engine.update_step_log", lambda *a, **k: None)
    monkeypatch.setattr("engine.cleanup_session", lambda: None)
    monkeypatch.setattr("engine.send_run_notification", lambda *a, **k: None)
    # 注：engine._cleanup_old_logs 是实例方法，不做模块级 patch；
    # LOG_DIR 已指向 tmp_path，后台日志清理对空目录是天然 no-op。
    monkeypatch.setattr("engine._build_prev_step_status_map", lambda *a, **k: None)
    monkeypatch.setattr("engine._should_skip_on_success", lambda **k: False)
    monkeypatch.setattr("engine.update_run_history", lambda *a, **k: None)
    # R1: 风险路径校验走 RunPlan——测试一律放行
    monkeypatch.setattr("risk_path_review.build_run_plan", lambda wf, steps: None)
    monkeypatch.setattr("risk_path_review.evaluate_run_plan", lambda plan: None)
    # 真实 SubWorkflowExecutor 的模块级 database 依赖 → 指向测试工作流表
    monkeypatch.setattr(
        "executors.sub_workflow_executor.get_workflow_by_uid",
        lambda uid: next((w for w in workflows.values() if w.uid == uid), None),
    )
    monkeypatch.setattr(
        "executors.sub_workflow_executor.get_workflow_by_id",
        lambda wid: workflows.get(wid),
    )
    monkeypatch.setattr(
        "executors.sub_workflow_executor.has_cross_workflow_cycle",
        lambda parent_id, target_uid: False,
    )
    # 默认执行器工厂：sub_workflow 用真实 SubWorkflowExecutor，其余立即成功。
    # 需要定制行为的测试在调用本函数后再自行覆盖 engine.get_executor。
    monkeypatch.setattr(
        "engine.get_executor",
        lambda step_type: SubWorkflowExecutor() if step_type == "sub_workflow" else _OkExecutor(),
    )

    records = lifecycle_records if lifecycle_records is not None else {}
    created = records.setdefault("created", [])
    updates = records.setdefault("updates", [])

    def fake_create_run_history(**kwargs):
        entry = {
            "workflow_id": kwargs.get("workflow_id"),
            "depth": get_run_thread_context().subworkflow_depth,
            "parent_run_id": kwargs.get("parent_run_id"),
            "t": time.monotonic(),
        }
        created.append(entry)
        return SimpleNamespace(
            id=1000 + len(created),
            run_id=f"run-{len(created)}",
            trace_id="trace-root",
            parent_run_id=kwargs.get("parent_run_id"),
        )

    def fake_update_run_history(run_history_id, **kwargs):
        updates.append({"run_history_id": run_history_id, **kwargs, "t": time.monotonic()})

    monkeypatch.setattr("engine_core.lifecycle.create_run_history", fake_create_run_history)
    monkeypatch.setattr("engine_core.lifecycle.update_run_history", fake_update_run_history)
    return records


def _run_bounded(engine, *args, timeout=20.0, **kwargs):
    """在 watchdog 线程中运行 engine._run；超时视为挂死并失败（不挂死 pytest）。"""
    outcome = {}

    def target():
        try:
            outcome["ok"] = engine._run(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            outcome["err"] = e
        finally:
            outcome["pool_after"] = get_run_thread_context().step_pool
            outcome["t"] = time.monotonic()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"运行超过 {timeout}s 未返回（疑似死锁/挂死）"
    if "err" in outcome:
        raise outcome["err"]
    return outcome


def _sub_workflow_fakes(monkeypatch, target_id=5, target_uid="wf-target", parent_id=1):
    target = SimpleNamespace(id=target_id, uid=target_uid)
    parent = SimpleNamespace(id=parent_id)
    monkeypatch.setattr(
        "executors.sub_workflow_executor.get_workflow_by_uid",
        lambda uid: target if uid == target_uid else None,
    )
    monkeypatch.setattr(
        "executors.sub_workflow_executor.get_workflow_by_id",
        lambda workflow_id: parent if workflow_id == parent_id else None,
    )
    monkeypatch.setattr(
        "executors.sub_workflow_executor.has_cross_workflow_cycle",
        lambda parent_id, target_uid: False,
    )
    return target


# ───────────── 1. 每 run 独立步骤池 ─────────────

class TestPerRunStepPools:
    def test_small_root_pool_parallel_subworkflows_complete_with_isolated_pools(
        self, monkeypatch, tmp_path,
    ):
        """根池 max_workers=1（小池）并行 2 个子工作流：完成且不共享池。

        每个 run（根 + 2 子）创建各自独立的步骤池，池按线程隔离；
        全部关闭、无泄漏；3 个 RunHistory 全终态。
        """
        workflows = {
            1: _wf(1, "wf-root", "根", max_workers=1),
            2: _wf(2, "wf-a", "子A", max_workers=1),
            3: _wf(3, "wf-b", "子B", max_workers=1),
        }
        steps_by_workflow = {
            1: [
                _step(10, "sa", 1, "sub_workflow", "wf-a", 1, name="子A"),
                _step(11, "sb", 2, "sub_workflow", "wf-b", 1, name="子B"),
            ],
            2: [
                _step(20, "pa", 1, "python", "script.py", 2, name="A1"),
                _step(21, "pa2", 2, "python", "script.py", 2, name="A2"),
            ],
            3: [
                _step(30, "pb", 1, "python", "script.py", 3, name="B1"),
                _step(31, "pb2", 2, "python", "script.py", 3, name="B2"),
            ],
        }
        records = {}
        _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow, records)
        recorder = _PoolRecorder()
        monkeypatch.setattr("engine_core.step_execution.ThreadPoolExecutor", recorder)

        engine = WorkflowEngine()
        try:
            outcome = _run_bounded(engine, 1, RunMode.FULL, signal_policy=_quiet_policy())
            assert outcome["ok"] is True
            # 根 + 2 个子工作流各 1 个独立 run 池
            assert len(recorder.created) == 3, recorder.created
            assert [c["max_workers"] for c in recorder.created] == [1, 1, 1]
            # 三个池创建于不同线程（根在 run 线程，两个子工作流各在自己的子线程）
            assert len({c["creator_thread"] for c in recorder.created}) == 3
            # 全部关闭，无泄漏
            assert len(recorder.shutdowns) == 3
            assert outcome["pool_after"] is None
            # 3 次 RunHistory（根 + 2 子），深度正确，全部终态
            assert [c["depth"] for c in records["created"]] == [0, 1, 1]
            terminal = [u for u in records["updates"] if u.get("status") != "running"]
            assert {u["run_history_id"] for u in terminal} == {1001, 1002, 1003}
            assert all(u["status"] == "success" for u in terminal)
        finally:
            engine.shutdown(wait=False)

    def test_parallel_pool_capped_by_max_workers_clamp(self, monkeypatch, tmp_path):
        """workflow.max_workers=64 越界时，执行期夹紧为 8（WORKFLOW_MAX_WORKERS_MAX）。"""
        workflows = {1: _wf(1, "wf-root", "根", max_workers=64)}
        steps_by_workflow = {
            1: [
                _step(10, "a", 1, "python", "s.py", 1),
                _step(11, "b", 2, "python", "s.py", 1),
            ],
        }
        records = {}
        _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow, records)
        recorder = _PoolRecorder()
        monkeypatch.setattr("engine_core.step_execution.ThreadPoolExecutor", recorder)

        engine = WorkflowEngine()
        try:
            outcome = _run_bounded(engine, 1, RunMode.FULL, signal_policy=_quiet_policy())
            assert outcome["ok"] is True
            assert recorder.created[0]["max_workers"] == 8
        finally:
            engine.shutdown(wait=False)


# ───────────── 2. 深度预算：三层嵌套 ─────────────

class TestDepthBudget:
    def test_three_level_nesting_leaf_once_all_terminal_depth_correct(self, monkeypatch, tmp_path):
        """根 → 子 → 孙 → 叶子：叶子只执行一次；深度 [0,1,2,3]；4 个 run 全终态。"""
        workflows = {wid: _wf(wid, f"wf-{wid}", f"W{wid}", max_workers=1) for wid in (1, 2, 3, 4)}
        leaf_executions = []
        steps_by_workflow = {
            1: [_step(10, "s1", 1, "sub_workflow", "wf-2", 1)],
            2: [_step(20, "s2", 1, "sub_workflow", "wf-3", 2)],
            3: [_step(30, "s3", 1, "sub_workflow", "wf-4", 3)],
            4: [_step(40, "leaf", 1, "python", "leaf.py", 4)],
        }
        records = {}
        _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow, records)
        monkeypatch.setattr(
            "engine.get_executor",
            lambda step_type: SubWorkflowExecutor()
            if step_type == "sub_workflow"
            else _OkExecutor(on_execute=lambda kw: leaf_executions.append(time.monotonic())),
        )

        engine = WorkflowEngine()
        try:
            outcome = _run_bounded(engine, 1, RunMode.FULL, signal_policy=_quiet_policy())
            assert outcome["ok"] is True
            assert len(leaf_executions) == 1, "叶子步骤必须只执行一次"
            assert [c["depth"] for c in records["created"]] == [0, 1, 2, 3]
            terminal = [u for u in records["updates"] if u.get("status") != "running"]
            assert {u["run_history_id"] for u in terminal} == {1001, 1002, 1003, 1004}
            assert all(u["status"] == "success" for u in terminal)
            assert outcome["pool_after"] is None
        finally:
            engine.shutdown(wait=False)

    def test_depth_exceeded_fails_fast_before_launch(self, monkeypatch):
        """深度超过 MAX_SUBWORKFLOW_DEPTH：立即返回 non-retryable 结果，不启动子线程。"""
        _sub_workflow_fakes(monkeypatch)
        calls = []

        result = SubWorkflowExecutor().execute(
            script_path="wf-target",
            workflow_id=1,
            subworkflow_depth=5,  # 超过 MAX_SUBWORKFLOW_DEPTH=4
            workflow_runner=lambda *a, **k: calls.append(a) or True,
        )

        assert result.success is False
        assert result.exit_code == 1
        assert "嵌套深度超出限制" in (result.error_message or "")
        assert result.extra[ResultPolicyKeys.NON_RETRYABLE] is True
        assert calls == [], "深度超限时不得启动子工作流线程"

    def test_depth_at_limit_allowed(self, monkeypatch):
        """深度恰好等于上限（4）时允许启动。"""
        _sub_workflow_fakes(monkeypatch)
        calls = []

        result = SubWorkflowExecutor().execute(
            script_path="wf-target",
            workflow_id=1,
            subworkflow_depth=4,
            workflow_runner=lambda *a, **k: calls.append(a) or True,
        )

        assert result.success is True
        assert calls, "深度=4 应允许启动子工作流"
        assert len(calls) == 1


# ───────────── 3. 根取消穿透 ─────────────

class TestRootCancelPropagation:
    def test_root_cancel_propagates_no_new_leaf_starts(self, monkeypatch, tmp_path):
        """根取消穿透到子工作流：无新 leaf start，运行有界返回，全部终态 cancelled。"""
        workflows = {
            1: _wf(1, "wf-root", "根", max_workers=2),
            2: _wf(2, "wf-a", "子A", max_workers=1),
            3: _wf(3, "wf-b", "子B", max_workers=1),
        }
        steps_by_workflow = {
            1: [
                _step(10, "sa", 1, "sub_workflow", "wf-a", 1),
                _step(11, "sb", 2, "sub_workflow", "wf-b", 1),
            ],
            2: [
                _step(20, "a1", 1, "python", "s.py", 2),
                _step(21, "a2", 2, "python", "s.py", 2),
                _step(22, "a3", 3, "python", "s.py", 2),
            ],
            3: [
                _step(30, "b1", 1, "python", "s.py", 3),
                _step(31, "b2", 2, "python", "s.py", 3),
                _step(32, "b3", 3, "python", "s.py", 3),
            ],
        }
        records = {}
        _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow, records)
        leaf_starts = []
        cancel_time = {}

        def executor_factory(step_type):
            if step_type == "sub_workflow":
                return SubWorkflowExecutor()
            return _CancelAwareExecutor(
                on_started=lambda kw: leaf_starts.append(time.monotonic()),
                wait_seconds=10,
            )

        monkeypatch.setattr("engine.get_executor", lambda step_type: executor_factory(step_type))

        engine = WorkflowEngine()
        try:
            def timer():
                time.sleep(0.4)
                cancel_time["t"] = time.monotonic()
                engine.cancel()

            threading.Thread(target=timer, daemon=True).start()
            start = time.monotonic()
            outcome = _run_bounded(engine, 1, RunMode.FULL, signal_policy=_quiet_policy(), timeout=15)
            elapsed = time.monotonic() - start

            assert elapsed < 12, f"取消后运行应快速收尾: {elapsed:.1f}s"
            assert outcome["ok"] is False
            # 取消后不得有新的 leaf 启动（留 1.5s 覆盖 watcher/轮询延迟）
            assert cancel_time
            assert all(s <= cancel_time["t"] + 1.5 for s in leaf_starts), leaf_starts
            # 每个子工作流 window=1，最多各启动 1 个 leaf
            assert len(leaf_starts) <= 2, leaf_starts
            # 全部终态且为 cancelled
            terminal = [u for u in records["updates"] if u.get("status") != "running"]
            assert terminal, "应有终态更新"
            assert all(u["status"] == "cancelled" for u in terminal), [u["status"] for u in terminal]
        finally:
            engine.shutdown(wait=False)


# ───────────── 4. scheduler 有界观察取消 ─────────────

class TestSchedulerBoundedCancel:
    def test_polling_observes_cancel_without_completion_event(self):
        """池被无限阻塞任务占满时，窗口 futures 排队未启动；取消请求在
        没有任何完成事件时也能被轮询观察（有界返回，不挂死）。

        回归保护：旧实现 wait(FIRST_COMPLETED) 无超时，会一直等一个完成事件；
        本场景下永远没有完成事件 → 取消永远不被观察 → 挂死。
        """
        from engine_core.scheduler import SchedulerMetrics, run_steps_parallel

        blockers = [threading.Event(), threading.Event()]
        steps = [SimpleNamespace(id=1, order=1), SimpleNamespace(id=2, order=2)]
        runner_calls = []
        stop_at = time.monotonic() + 0.15
        outcome = {}
        metrics = SchedulerMetrics()

        with ThreadPoolExecutor(max_workers=2) as pool:
            blocker_futures = [pool.submit(lambda ev=ev: ev.wait(30)) for ev in blockers]
            try:
                def target():
                    try:
                        outcome["results"] = run_steps_parallel(
                            steps,
                            executor=pool,
                            max_workers=2,
                            step_runner=lambda s: runner_calls.append(s.id)
                            or SimpleNamespace(step_id=s.id, status="success"),
                            should_stop=lambda: time.monotonic() >= stop_at,
                            metrics=metrics,
                        )
                        outcome["t"] = time.monotonic()
                    except Exception as e:  # noqa: BLE001
                        outcome["err"] = e

                thread = threading.Thread(target=target, daemon=True)
                thread.start()
                thread.join(5)
                assert not thread.is_alive(), "scheduler 无完成事件时未能观察取消（疑似阻塞在无超时 wait）"
            finally:
                for ev in blockers:
                    ev.set()
                for f in blocker_futures:
                    f.result(timeout=5)

            if "err" in outcome:
                raise outcome["err"]
            assert outcome["t"] - stop_at < 1.0, "取消后约一个轮询周期内有界返回"
            assert runner_calls == [], "排队未启动的 futures 不得执行"
            assert metrics.submitted == 2
            assert metrics.cancelled == 2
            assert [getattr(r, "step_id", None) for r in outcome["results"]] == [1, 2]
            assert all(getattr(r, "status", None) == "cancelled" for r in outcome["results"])

    def test_normalize_workflow_max_workers_clamps(self):
        assert normalize_workflow_max_workers(None) == 2
        assert normalize_workflow_max_workers(0) == 2
        assert normalize_workflow_max_workers(-3) == 2
        assert normalize_workflow_max_workers("abc") == 2
        assert normalize_workflow_max_workers(1) == 1
        assert normalize_workflow_max_workers(8) == 8
        assert normalize_workflow_max_workers(64) == 8  # 越界夹紧
        assert normalize_workflow_max_workers("4") == 4


# ───────────── 5. 并发预算 ─────────────

class TestSubWorkflowBudget:
    def test_budget_exhaustion_fails_fast_without_run_history(self, monkeypatch, tmp_path):
        """预算耗尽：fail-fast 抛 ResourceBudgetExceededError，不创建 RunHistory，
        释放后恢复正常运行。"""
        workflows = {5: _wf(5, "wf-child", "子", max_workers=1)}
        steps_by_workflow = {5: [_step(50, "p", 1, "python", "s.py", 5)]}
        records = {}
        _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow, records)

        engine = WorkflowEngine()
        try:
            engine._running = True
            engine._current_run_id = "parent-run"
            engine._current_trace_id = "trace-root"
            for _ in range(MAX_ACTIVE_SUBWORKFLOWS):
                assert engine._acquire_subworkflow_slot() is True
            assert engine._acquire_subworkflow_slot() is False

            started = time.monotonic()
            with pytest.raises(ResourceBudgetExceededError, match="并发子工作流数量超出限制"):
                engine.run_sub_workflow(5)
            assert time.monotonic() - started < 1.0, "预算耗尽必须 fail-fast，不挂死"
            assert records["created"] == [], "超限时不得创建 RunHistory"
            assert engine._active_subworkflow_count == MAX_ACTIVE_SUBWORKFLOWS

            # 释放后再跑正常成功
            for _ in range(MAX_ACTIVE_SUBWORKFLOWS):
                engine._release_subworkflow_slot()
            assert engine.run_sub_workflow(5) is True
            assert len(records["created"]) == 1
            assert records["created"][0]["depth"] == 1
        finally:
            engine.shutdown(wait=False)

    def test_budget_exhaustion_maps_to_non_retryable_executor_result(self, monkeypatch, tmp_path):
        """预算耗尽经 SubWorkflowExecutor 映射为 non-retryable 中文资源错误（不触发重试）。"""
        workflows = {5: _wf(5, "wf-child", "子", max_workers=1)}
        steps_by_workflow = {5: [_step(50, "p", 1, "python", "s.py", 5)]}
        _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow)
        # 后装：让 executors.sub_workflow_executor 的依赖解析到 wf-target
        _sub_workflow_fakes(monkeypatch)

        engine = WorkflowEngine()
        try:
            for _ in range(MAX_ACTIVE_SUBWORKFLOWS):
                assert engine._acquire_subworkflow_slot() is True

            started = time.monotonic()
            result = SubWorkflowExecutor().execute(
                script_path="wf-target",
                workflow_id=1,
                workflow_runner=engine.run_sub_workflow,
            )
            assert time.monotonic() - started < 1.0, "预算耗尽必须 fail-fast，不挂死"
            assert result.success is False
            assert result.exit_code == 1
            assert "并发子工作流数量超出限制" in (result.error_message or "")
            assert result.extra[ResultPolicyKeys.NON_RETRYABLE] is True
        finally:
            engine.shutdown(wait=False)


# ───────────── 6. 合作式取消顺序 ─────────────

class TestCooperativeCancelOrdering:
    def test_cancel_seen_then_child_finished_then_parent_returned(self, monkeypatch, tmp_path):
        """合作式取消链路：cancel_seen → child_finished → parent_returned，有界返回。"""
        workflows = {
            1: _wf(1, "wf-root", "根", max_workers=1),
            2: _wf(2, "wf-child", "子", max_workers=1),
        }
        steps_by_workflow = {
            1: [_step(10, "s", 1, "sub_workflow", "wf-child", 1)],
            2: [_step(20, "p", 1, "python", "s.py", 2)],
        }
        records = {}
        _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow, records)

        def executor_factory(step_type):
            if step_type == "sub_workflow":
                return SubWorkflowExecutor()
            return _CancelAwareExecutor(
                on_cancel=lambda: events.setdefault("cancel_seen", time.monotonic()),
                wait_seconds=10,
            )

        monkeypatch.setattr("engine.get_executor", lambda step_type: executor_factory(step_type))

        engine = WorkflowEngine()
        try:
            events = {}

            def timer():
                time.sleep(0.4)
                events["cancel_requested"] = time.monotonic()
                engine.cancel()

            threading.Thread(target=timer, daemon=True).start()
            start = time.monotonic()
            outcome = _run_bounded(engine, 1, RunMode.FULL, signal_policy=_quiet_policy(), timeout=15)
            elapsed = time.monotonic() - start

            assert elapsed < 12, f"合作式取消应快速收尾: {elapsed:.1f}s"
            assert outcome["ok"] is False
            assert "cancel_seen" in events, "子工作流步骤应观察到取消"
            child_terminal = [
                u for u in records["updates"]
                if u["run_history_id"] == 1002 and u.get("status") != "running"
            ]
            assert child_terminal, "子工作流应有终态"
            assert all(u["status"] == "cancelled" for u in child_terminal)
            events["child_finished"] = child_terminal[0]["t"]
            events["parent_returned"] = outcome["t"]
            # 顺序：cancel_requested ≤ cancel_seen ≤ child_finished ≤ parent_returned
            assert events["cancel_requested"] <= events["cancel_seen"] <= events["child_finished"] <= events["parent_returned"]
        finally:
            engine.shutdown(wait=False)


# ───────────── 7. 不合作式：风险结果保留 + 槽位释放时机 ─────────────

class TestUncooperativeChild:
    def test_timeout_keeps_risk_result_and_slot_released_at_child_finalization(
        self, monkeypatch, tmp_path,
    ):
        """不合作子工作流：执行器有界返回并保留 BACKGROUND_RISK / ORPHAN_RISK；
        预算槽位在 child finalization 释放（而非 executor 放弃等待时）。"""
        workflows = {2: _wf(2, "wf-child", "子", max_workers=1)}
        steps_by_workflow = {2: [_step(20, "p", 1, "python", "s.py", 2)]}
        _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow)
        monkeypatch.setattr("engine.get_executor", lambda step_type: _StubbornExecutor(duration=0.5))
        monkeypatch.setattr(SubWorkflowExecutor, "CHILD_EXIT_GRACE_SECONDS", 0.05)
        _sub_workflow_fakes(monkeypatch, target_id=2, target_uid="wf-child")

        engine = WorkflowEngine()
        try:
            for _ in range(MAX_ACTIVE_SUBWORKFLOWS - 1):
                assert engine._acquire_subworkflow_slot() is True

            started = time.monotonic()
            result = SubWorkflowExecutor().execute(
                script_path="wf-child",
                workflow_id=1,
                timeout=0.05,
                workflow_runner=engine.run_sub_workflow,
            )
            elapsed = time.monotonic() - started
            assert elapsed < 0.4, f"不合作子工作流应有界返回: {elapsed:.2f}s"
            assert result.success is False
            assert result.exit_code == -1
            assert "子工作流执行超时" in (result.error_message or "")
            assert "后台运行风险" in (result.error_message or "")
            assert result.extra[ResultPolicyKeys.BACKGROUND_RISK] is True
            assert result.extra[ResultPolicyKeys.ORPHAN_RISK] is True
            # 此刻子工作流仍在后台运行：槽位未释放（计数 = 15 + 1）
            assert engine._active_subworkflow_count == MAX_ACTIVE_SUBWORKFLOWS
            # 子工作流最终收尾后释放槽位
            deadline = time.monotonic() + 5
            while (
                engine._active_subworkflow_count != MAX_ACTIVE_SUBWORKFLOWS - 1
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            assert engine._active_subworkflow_count == MAX_ACTIVE_SUBWORKFLOWS - 1, \
                "child finalization 应释放预算槽位"
        finally:
            engine.shutdown(wait=False)


# ───────────── 8. 池生命周期 ─────────────

class TestPoolLifecycle:
    def test_exception_path_shuts_down_pool_no_leak(self, monkeypatch, tmp_path):
        """执行中途抛异常：run 收尾仍关闭步骤池（异常路径无泄漏）。"""
        workflows = {1: _wf(1, "wf-root", "根", max_workers=2)}
        steps_by_workflow = {1: [_step(10, "a", 1, "python", "s.py", 1)]}
        records = {}
        _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow, records)

        engine = WorkflowEngine()

        def fake_execute_steps(*a, **k):
            # 模拟"已创建并行步骤池后，执行中途抛异常"
            get_run_thread_context().step_pool = ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="run-steps",
            )
            raise RuntimeError("mid-run boom")

        monkeypatch.setattr(engine, "_execute_steps", fake_execute_steps)
        try:
            outcome = _run_bounded(engine, 1, RunMode.FULL, signal_policy=_quiet_policy())
            assert outcome["ok"] is False
            assert outcome["pool_after"] is None, "异常路径必须关闭步骤池"
        finally:
            engine.shutdown(wait=False)

    def test_repeated_runs_create_fresh_pools(self, monkeypatch, tmp_path):
        """每次 run 都创建全新的独立步骤池；run 结束后 ctx 无残留池。"""
        workflows = {1: _wf(1, "wf-root", "根", max_workers=2)}
        steps_by_workflow = {
            1: [
                _step(10, "a", 1, "python", "s.py", 1),
                _step(11, "b", 2, "python", "s.py", 1),
            ],
        }
        records = {}
        _install_run_fakes(monkeypatch, tmp_path, workflows, steps_by_workflow, records)
        recorder = _PoolRecorder()
        monkeypatch.setattr("engine_core.step_execution.ThreadPoolExecutor", recorder)

        engine = WorkflowEngine()
        try:
            for _ in range(2):
                outcome = _run_bounded(engine, 1, RunMode.FULL, signal_policy=_quiet_policy())
                assert outcome["ok"] is True
                assert outcome["pool_after"] is None
            assert len(recorder.created) == 2, "每次 run 都应创建全新的独立步骤池"
            assert len(recorder.shutdowns) == 2
        finally:
            engine.shutdown(wait=False)


# ───────────── 辅助池 ─────────────

class TestAuxiliaryPool:
    def test_submit_auxiliary_falls_back_to_daemon_thread_when_pool_closed(self):
        """辅助池不可用时降级 daemon 线程执行，不丢通知任务。"""
        engine = WorkflowEngine()
        engine.shutdown(wait=False)
        assert engine._executor is None
        done = threading.Event()

        def task():
            done.set()

        engine._submit_auxiliary(task)
        assert done.wait(2), "辅助池不可用时必须降级 daemon 线程执行，不丢任务"
        assert engine._active_subworkflow_count == 0

    def test_auxiliary_pool_has_bounded_workers(self):
        engine = WorkflowEngine()
        try:
            assert engine._executor._max_workers == 4
        finally:
            engine.shutdown(wait=False)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
