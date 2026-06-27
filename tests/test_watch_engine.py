# -*- coding: utf-8 -*-
"""文件监听行为测试"""

import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine import WorkflowEngine
import engine_core.watcher as watcher_mod


@dataclass
class MockWorkflow:
    id: int = 1
    name: str = "测试工作流"
    watch_enabled: bool = True
    cooldown_seconds: int = 10
    settle_seconds: int = 0
    watch_mode: str = "any_change"
    folders: list[str] | None = None

    def get_watch_folders(self) -> list[str]:
        return list(self.folders or [])


def test_validate_watch_folders_returns_unique_resolved_directories(tmp_path: Path):
    engine = WorkflowEngine()
    folder = tmp_path / "watch"
    folder.mkdir()

    result = engine.validate_watch_folders([str(folder), str(folder), str(folder / ".")])

    assert result == [str(folder.resolve())]


def test_validate_watch_folders_rejects_missing_directory(tmp_path: Path):
    engine = WorkflowEngine()
    missing = tmp_path / "missing"

    with pytest.raises(ValueError, match="不存在"):
        engine.validate_watch_folders([str(missing)])


def test_start_watch_returns_false_for_invalid_directory(tmp_path: Path):
    engine = WorkflowEngine()
    workflow = MockWorkflow(folders=[str(tmp_path / "missing")])

    started = engine.start_watch(workflow)

    assert started is False
    # M1: 监听器按 workflow_id 管理；启动失败不应留下任何 watcher
    assert engine._watchers == {}


def test_stop_watch_stops_sleeping_thread_quickly(tmp_path: Path):
    engine = WorkflowEngine()
    folder = tmp_path / "watch"
    folder.mkdir()
    workflow = MockWorkflow(folders=[str(folder)], cooldown_seconds=30)

    started = engine.start_watch(workflow)

    assert started is True
    # M1: 监听线程挂在 engine._watchers[workflow.id] 上
    watcher = engine._watchers[workflow.id]
    assert watcher._thread is not None
    assert watcher._thread.is_alive()

    started_at = time.perf_counter()
    engine.stop_watch(join_timeout=0.5)
    elapsed = time.perf_counter() - started_at

    assert elapsed < 1.0
    assert workflow.id not in engine._watchers
    assert watcher._thread is None or not watcher._thread.is_alive()


def test_engine_watches_multiple_workflows_independently(tmp_path: Path):
    """M1: 多工作流可同时监听；停掉一个不影响另一个。"""
    engine = WorkflowEngine()
    folder_a = tmp_path / "watch_a"
    folder_b = tmp_path / "watch_b"
    folder_a.mkdir()
    folder_b.mkdir()
    wf_a = MockWorkflow(id=1, name="A", folders=[str(folder_a)], cooldown_seconds=30)
    wf_b = MockWorkflow(id=2, name="B", folders=[str(folder_b)], cooldown_seconds=30)

    assert engine.start_watch(wf_a) is True
    assert engine.start_watch(wf_b) is True
    assert set(engine._watchers.keys()) == {1, 2}
    assert engine._watchers[1]._thread.is_alive()
    assert engine._watchers[2]._thread.is_alive()

    engine.stop_watch(wf_a.id, join_timeout=0.5)
    assert 1 not in engine._watchers
    assert 2 in engine._watchers
    assert engine._watchers[2]._thread.is_alive()

    engine.stop_watch(join_timeout=0.5)
    assert engine._watchers == {}


def test_engine_restore_watches_starts_enabled_workflows(tmp_path: Path, monkeypatch):
    """M1: restore_watches 启动所有 watch_enabled 工作流，跳过未启用的。"""
    import database

    engine = WorkflowEngine()
    folder = tmp_path / "watch"
    folder.mkdir()
    wf_on = MockWorkflow(id=11, name="启用监听", folders=[str(folder)], cooldown_seconds=30)
    wf_off = MockWorkflow(id=12, name="未启用", watch_enabled=False, folders=[str(folder)])
    monkeypatch.setattr(database, "list_workflows", lambda: [wf_on, wf_off])

    results = engine.restore_watches()

    assert results == [("启用监听", True)]
    assert set(engine._watchers.keys()) == {11}
    engine.stop_watch(join_timeout=0.5)


def test_file_watcher_stop_timeout_keeps_thread_handle_and_blocks_parallel_restart(monkeypatch):
    logs: list[str] = []
    release_thread = threading.Event()
    started_threads: list[threading.Thread] = []

    def fake_start_watchdog(_self, _folders):
        return None

    def blocking_loop(self, *_args):
        started_threads.append(threading.current_thread())
        release_thread.wait(5.0)

    watcher = watcher_mod.FileWatcher(logs.append, lambda *_args: None, lambda: False)
    monkeypatch.setattr(watcher_mod.FileWatcher, "_start_watchdog_observer", fake_start_watchdog)
    monkeypatch.setattr(watcher_mod.FileWatcher, "_loop", blocking_loop)

    assert watcher.start(1, ["watch"], cooldown=1, settle=0, mode="any_change") is True
    old_thread = watcher._thread
    assert old_thread is not None

    watcher.stop(join_timeout=0.01)

    assert watcher._thread is old_thread
    assert old_thread.is_alive() is True

    restarted = watcher.start(2, ["watch"], cooldown=1, settle=0, mode="any_change")

    assert restarted is False
    assert watcher._thread is old_thread
    assert len(started_threads) == 1
    assert any("文件监听线程未能及时退出" in message for message in logs)
    assert any("旧的文件监听线程仍在退出中" in message for message in logs)

    release_thread.set()
    old_thread.join(timeout=0.5)
    watcher.stop(join_timeout=0.1)


def test_engine_stop_watch_does_not_emit_stopped_when_thread_survives():
    engine = WorkflowEngine()
    emitted = []
    engine.watch_stopped.connect(emitted.append)

    class AliveThread:
        def is_alive(self):
            return True

    class StuckWatcher:
        def __init__(self):
            self._thread = AliveThread()
            self._workflow_id = 7

        def stop(self, join_timeout=1.0):
            return None

    engine._watchers = {7: StuckWatcher()}

    engine.stop_watch(join_timeout=0.01)

    assert emitted == []
    # M1: 线程未退出时保留句柄，阻止并行重启
    assert 7 in engine._watchers


def test_engine_start_watch_restarts_after_watcher_thread_death(tmp_path: Path, monkeypatch):
    """H4 修复：watcher 线程死亡（_loop 致命异常退出）后，同参数 start_watch 不得被幂等守卫短路。"""
    folder = tmp_path / "watch"
    folder.mkdir()
    engine = WorkflowEngine()
    workflow = MockWorkflow(folders=[str(folder)], cooldown_seconds=30)
    # 模拟监听主循环立即退出（致命异常路径）
    monkeypatch.setattr(watcher_mod.FileWatcher, "_loop", lambda self, *args: None)

    assert engine.start_watch(workflow) is True
    dead_thread = engine._watchers[workflow.id]._thread
    assert dead_thread is not None
    dead_thread.join(timeout=1.0)
    assert not dead_thread.is_alive()

    # 旧实现：_thread 非 None 即短路返回 True，死监听永远无法恢复
    assert engine.start_watch(workflow) is True
    new_thread = engine._watchers[workflow.id]._thread
    assert new_thread is not None
    assert new_thread is not dead_thread

    engine.stop_watch()


def test_watch_loop_swallows_change_while_current_run_is_active(monkeypatch):
    engine = WorkflowEngine()
    engine._running = True
    scan_calls = {"count": 0}
    trigger_calls = []
    # M1: watcher 不再常驻 engine 属性；按引擎回调约定构造一个等价实例
    watcher = watcher_mod.FileWatcher(
        log_cb=lambda _message: None,
        trigger_cb=lambda wf_id, reason: engine.run_all(wf_id, reason=reason),
        is_running_cb=lambda: engine.is_running,
    )

    def fake_scan_folder_mtimes(_folders, **_kwargs):
        scan_calls["count"] += 1
        if scan_calls["count"] == 1:
            return {"watch": 0}
        if scan_calls["count"] >= 4:
            engine._running = False
            watcher._stop.set()
        return {"watch": 10}

    def fake_run_all(workflow_id, reason="manual"):
        trigger_calls.append((workflow_id, reason))
        watcher._stop.set()
        return True

    monkeypatch.setattr(watcher_mod, "scan_folder_mtimes", fake_scan_folder_mtimes)
    monkeypatch.setattr(
        watcher_mod,
        "scan_folder_mtimes_result",
        lambda folders, **kwargs: watcher_mod.MtimeScanResult(
            fake_scan_folder_mtimes(folders, **kwargs)
        ),
    )
    monkeypatch.setattr(engine, "run_all", fake_run_all)

    thread = threading.Thread(
        target=watcher._loop,
        args=(7, ["watch"], 0.01, 0, "any_change"),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)
    watcher._stop.set()
    thread.join(timeout=0.5)

    assert trigger_calls == []


def test_scan_folder_mtimes_returns_root_aggregated_mtime(tmp_path: Path):
    watched = tmp_path / "watch"
    nested = watched / "nested"
    nested.mkdir(parents=True)
    root_file = watched / "root.txt"
    child_file = nested / "child.txt"
    root_file.write_text("root", encoding="utf-8")
    child_file.write_text("child", encoding="utf-8")

    root_mtime = root_file.stat().st_mtime
    child_mtime = child_file.stat().st_mtime

    folder_mtimes = watcher_mod.scan_folder_mtimes([str(watched)])

    assert folder_mtimes == {str(watched): max(root_mtime, child_mtime)}


def test_scan_folder_mtimes_scans_deeper_than_3_levels_by_default(tmp_path: Path):
    watched = tmp_path / "watch"
    deep_dir = watched / "level1" / "level2" / "level3" / "level4"
    deep_dir.mkdir(parents=True)
    deep_file = deep_dir / "deep.txt"
    deep_file.write_text("deep", encoding="utf-8")

    deep_mtime = time.time() - 60
    os.utime(deep_file, (deep_mtime, deep_mtime))

    default_scan = watcher_mod.scan_folder_mtimes([str(watched)])
    shallow_scan = watcher_mod.scan_folder_mtimes([str(watched)], max_depth=3)

    assert default_scan == {str(watched): deep_mtime}
    assert shallow_scan == {str(watched): 0.0}


def test_file_watcher_poll_mode_logs_explicit_scan_scope(tmp_path: Path, monkeypatch):
    watched = tmp_path / "watch"
    watched.mkdir()
    logs: list[str] = []

    def fake_start_watchdog(_self, _folders):
        return None

    watcher = watcher_mod.FileWatcher(logs.append, lambda *_args: None, lambda: False)
    monkeypatch.setattr(watcher_mod.FileWatcher, "_start_watchdog_observer", fake_start_watchdog)

    watcher.start(1, [str(watched)], cooldown=30, settle=0, mode="any_change")
    watcher.stop(join_timeout=0.5)

    assert any("轮询 (mtime, 深度=无限" in message for message in logs)
    assert any("目录上限=" in message and "单轮耗时上限=" in message for message in logs)


def test_scan_folder_mtimes_reports_abort_to_warning_callback(tmp_path: Path, monkeypatch):
    watched = tmp_path / "watch"
    (watched / "nested").mkdir(parents=True)
    logs: list[str] = []

    monkeypatch.setattr(watcher_mod, "MTIME_SCAN_MAX_DIRECTORIES", 1)

    folder_mtimes = watcher_mod.scan_folder_mtimes([str(watched)], warning_cb=logs.append)

    assert folder_mtimes == {str(watched): 0.0}
    assert any("警告：mtime 扫描提前终止" in message for message in logs)
    assert any("已扫描目录=1" in message for message in logs)


def test_watch_loop_does_not_trigger_when_scan_aborts(monkeypatch):
    """H2 修复：扫描不完整时不得"保守触发"——无法确认变更就不替用户启动工作流。"""
    logs: list[str] = []
    trigger_calls = []
    scan_calls = {"count": 0}

    def fake_scan_result(_folders, **_kwargs):
        scan_calls["count"] += 1
        if scan_calls["count"] == 1:
            return watcher_mod.MtimeScanResult({"watch": 5.0})
        if scan_calls["count"] >= 6:
            watcher._stop.set()
        return watcher_mod.MtimeScanResult({"watch": 5.0}, aborted=True, warning="scan aborted")

    watcher = watcher_mod.FileWatcher(
        logs.append,
        lambda workflow_id, reason: trigger_calls.append((workflow_id, reason)),
        lambda: False,
    )
    monkeypatch.setattr(watcher_mod, "scan_folder_mtimes_result", fake_scan_result)

    thread = threading.Thread(
        target=watcher._loop,
        args=(5, ["watch"], 0.01, 0, "any_change"),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=1.0)
    watcher._stop.set()
    thread.join(timeout=1.0)

    assert trigger_calls == []
    assert any("无法确认文件变更，本轮不会触发" in message for message in logs)


def test_watch_loop_rebaselines_after_initial_abort_without_trigger(monkeypatch):
    """H2 修复：初始扫描中止后，首个完整扫描只重建基线；其后真实变更仍可触发。"""
    logs: list[str] = []
    trigger_calls = []
    scan_calls = {"count": 0}

    def fake_scan_result(_folders, **_kwargs):
        scan_calls["count"] += 1
        n = scan_calls["count"]
        if n == 1:
            return watcher_mod.MtimeScanResult({"watch": 0.0}, aborted=True, warning="scan aborted")
        if n in (2, 3):
            return watcher_mod.MtimeScanResult({"watch": 10.0})
        if n >= 7:
            watcher._stop.set()
        return watcher_mod.MtimeScanResult({"watch": 20.0})

    watcher = watcher_mod.FileWatcher(
        logs.append,
        lambda workflow_id, reason: trigger_calls.append((workflow_id, reason)),
        lambda: False,
    )
    monkeypatch.setattr(watcher_mod, "scan_folder_mtimes_result", fake_scan_result)

    thread = threading.Thread(
        target=watcher._loop,
        args=(7, ["watch"], 0.01, 0, "any_change"),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=1.0)
    watcher._stop.set()
    thread.join(timeout=1.0)

    # 完整扫描（mtime=10）只重建基线不触发；随后 mtime=20 的真实变更触发一次
    assert trigger_calls == [(7, "watch")]
    assert any("监听基线已重新建立（此前扫描不完整），本轮不触发" in message for message in logs)


def test_watch_loop_swallows_pending_change_when_run_finished_before_settle(monkeypatch):
    """H1 修复：pending 窗口内曾有运行、settle 到期时运行已结束 → 吞并刷新基线，不得重跑。

    旧实现只在 settle 到期"当时"正在运行才吞并；运行尾部写出的文件在运行结束后到期，
    会被立刻当作新变更触发 watch 重跑（用户报告的"跑完又自动跑一遍"）。
    """
    logs: list[str] = []
    trigger_calls = []
    scan_calls = {"count": 0}
    running_calls = {"count": 0}

    def fake_scan_result(_folders, **_kwargs):
        scan_calls["count"] += 1
        n = scan_calls["count"]
        if n == 1:
            return watcher_mod.MtimeScanResult({"watch": 0.0})
        if n >= 6:
            watcher._stop.set()
        return watcher_mod.MtimeScanResult({"watch": 10.0})

    def fake_is_running():
        # 仅 pending 建立那一刻运行中（运行随后立刻结束）
        running_calls["count"] += 1
        return running_calls["count"] == 1

    watcher = watcher_mod.FileWatcher(
        logs.append,
        lambda workflow_id, reason: trigger_calls.append((workflow_id, reason)),
        fake_is_running,
    )
    monkeypatch.setattr(watcher_mod, "scan_folder_mtimes_result", fake_scan_result)

    thread = threading.Thread(
        target=watcher._loop,
        args=(11, ["watch"], 0.01, 0, "any_change"),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=1.0)
    watcher._stop.set()
    thread.join(timeout=1.0)

    assert trigger_calls == []
    assert any("与刚结束的运行重叠" in message for message in logs)


def test_watch_loop_all_folders_updated_since_success_uses_per_folder_success_baseline(monkeypatch):
    engine = WorkflowEngine()
    trigger_calls = []
    scan_calls = {"count": 0}
    # M1: watcher 不再常驻 engine 属性；按引擎回调约定构造一个等价实例
    watcher = watcher_mod.FileWatcher(
        log_cb=lambda _message: None,
        trigger_cb=lambda wf_id, reason: engine.run_all(wf_id, reason=reason),
        is_running_cb=lambda: engine.is_running,
    )

    def fake_scan_folder_mtimes(_folders, **_kwargs):
        scan_calls["count"] += 1
        if scan_calls["count"] == 1:
            return {"watch-a": 5, "watch-b": 10}
        if scan_calls["count"] == 2:
            return {"watch-a": 7, "watch-b": 10}
        if scan_calls["count"] == 3:
            return {"watch-a": 7, "watch-b": 11}
        watcher._stop.set()
        return {"watch-a": 7, "watch-b": 11}

    def fake_run_all(workflow_id, reason="manual"):
        trigger_calls.append((workflow_id, reason))
        watcher._stop.set()
        return True

    monkeypatch.setattr(watcher_mod, "scan_folder_mtimes", fake_scan_folder_mtimes)
    monkeypatch.setattr(
        watcher_mod,
        "scan_folder_mtimes_result",
        lambda folders, **kwargs: watcher_mod.MtimeScanResult(
            fake_scan_folder_mtimes(folders, **kwargs)
        ),
    )
    monkeypatch.setattr(engine, "run_all", fake_run_all)

    thread = threading.Thread(
        target=watcher._loop,
        args=(9, ["watch-a", "watch-b"], 0.01, 0, "all_folders_updated_since_success"),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)
    watcher._stop.set()
    thread.join(timeout=0.5)

    assert trigger_calls == [(9, "watch")]


def test_watch_loop_swallows_changes_while_workflow_is_running(monkeypatch):
    """运行期间写入监听目录应只刷新基线，不应在运行结束后自动补跑一次。"""
    logs: list[str] = []
    trigger_calls = []
    state = {"scans": 0, "running": False}

    def fake_scan_result(_folders, **_kwargs):
        state["scans"] += 1
        n = state["scans"]
        if n == 1:
            return watcher_mod.MtimeScanResult({"watch": 0.0})
        if n <= 4:
            # 阶段一：外部变更（无运行）→ 应正常触发一次
            return watcher_mod.MtimeScanResult({"watch": 10.0})
        if n == 5:
            # 阶段二：手动运行开始，运行期间写出新文件
            state["running"] = True
        if n >= 8:
            state["running"] = False
        if n > 12:
            watcher._stop.set()
        return watcher_mod.MtimeScanResult({"watch": 20.0})

    def fake_trigger(workflow_id, reason):
        trigger_calls.append((workflow_id, reason))
        return True

    watcher = watcher_mod.FileWatcher(logs.append, fake_trigger, lambda: state["running"])
    monkeypatch.setattr(watcher_mod, "scan_folder_mtimes_result", fake_scan_result)

    thread = threading.Thread(
        target=watcher._loop,
        args=(11, ["watch"], 0.01, 0, "any_change"),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=1.5)
    watcher._stop.set()
    watcher._dirty.set()
    thread.join(timeout=1.0)

    # 外部变更只触发一次；运行期间的变更被吞并，不补跑第二次
    assert trigger_calls == [(11, "watch")]
    assert any("检测到运行期间文件变更，已刷新监听基线" in message for message in logs)


def test_watch_loop_refreshes_all_folders_baseline_after_run(monkeypatch):
    logs: list[str] = []
    trigger_calls = []
    scan_calls = {"count": 0}
    run_finished = {"value": False}

    def fake_scan_result(_folders, **_kwargs):
        scan_calls["count"] += 1
        if scan_calls["count"] == 1:
            return watcher_mod.MtimeScanResult({"a": 0.0, "b": 0.0})
        if not run_finished["value"]:
            return watcher_mod.MtimeScanResult({"a": 5.0, "b": 5.0})
        return watcher_mod.MtimeScanResult({"a": 9.0, "b": 9.0})

    def fake_trigger(workflow_id, reason):
        trigger_calls.append((workflow_id, reason))
        run_finished["value"] = True
        return True

    watcher = watcher_mod.FileWatcher(logs.append, fake_trigger, lambda: False)
    monkeypatch.setattr(watcher_mod, "scan_folder_mtimes_result", fake_scan_result)

    thread = threading.Thread(
        target=watcher._loop,
        args=(12, ["a", "b"], 0.01, 0, "all_folders_updated_since_success"),
        daemon=True,
    )
    thread.start()
    time.sleep(0.12)
    watcher._stop.set()
    watcher._dirty.set()
    thread.join(timeout=0.5)

    assert trigger_calls == [(12, "watch")]
    assert any("监听触发后已刷新文件变更基线" in message for message in logs)


def test_watch_refreshes_file_baseline_after_failed_trigger(monkeypatch):
    """监听触发的工作流失败后，也应刷新基线，避免同一批文件变更无限重跑。"""
    logs = []
    trigger_calls = []
    watcher = watcher_mod.FileWatcher(
        trigger_cb=lambda workflow_id, reason: trigger_calls.append((workflow_id, reason)) or False,
        is_running_cb=lambda: False,
        log_cb=logs.append,
    )

    scan_calls = {"count": 0}

    def fake_scan(folders, max_depth=8, warning_cb=None):
        scan_calls["count"] += 1
        if scan_calls["count"] == 1:
            return watcher_mod.MtimeScanResult({"watch": 1}, False)
        if scan_calls["count"] == 2:
            return watcher_mod.MtimeScanResult({"watch": 5}, False)
        if scan_calls["count"] == 3:
            return watcher_mod.MtimeScanResult({"watch": 8}, False)
        watcher._stop.set()
        return watcher_mod.MtimeScanResult({"watch": 8}, False)

    monkeypatch.setattr(watcher_mod, "scan_folder_mtimes_result", fake_scan)

    thread = threading.Thread(
        target=watcher._loop,
        args=(13, ["watch"], 0.01, 0, "any_change"),
        daemon=True,
    )
    thread.start()
    time.sleep(0.12)
    watcher._stop.set()
    watcher._dirty.set()
    thread.join(timeout=0.5)

    assert trigger_calls == [(13, "watch")]
    assert any("监听触发失败后已刷新文件变更基线" in message for message in logs)
