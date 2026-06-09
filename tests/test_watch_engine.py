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
    # CA2: 监听线程现在挂在 engine._watcher 上
    assert engine._watcher._thread is None


def test_stop_watch_stops_sleeping_thread_quickly(tmp_path: Path):
    engine = WorkflowEngine()
    folder = tmp_path / "watch"
    folder.mkdir()
    workflow = MockWorkflow(folders=[str(folder)], cooldown_seconds=30)

    started = engine.start_watch(workflow)

    assert started is True
    # CA2: 监听线程现在挂在 engine._watcher 上
    assert engine._watcher._thread is not None
    assert engine._watcher._thread.is_alive()

    started_at = time.perf_counter()
    engine.stop_watch(join_timeout=0.5)
    elapsed = time.perf_counter() - started_at

    assert elapsed < 1.0
    assert engine._watcher._thread is None or not engine._watcher._thread.is_alive()


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

    engine._watcher = StuckWatcher()

    engine.stop_watch(join_timeout=0.01)

    assert emitted == []


def test_watch_loop_replays_queued_change_after_current_run_finishes(monkeypatch):
    engine = WorkflowEngine()
    engine._running = True
    scan_calls = {"count": 0}
    trigger_calls = []

    def fake_scan_folder_mtimes(_folders, **_kwargs):
        scan_calls["count"] += 1
        if scan_calls["count"] == 1:
            return {"watch": 0}
        if scan_calls["count"] >= 4:
            engine._running = False
        return {"watch": 10}

    def fake_run_all(workflow_id, reason="manual"):
        trigger_calls.append((workflow_id, reason))
        engine._watcher._stop.set()
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
    # FileWatcher 内部 trigger 回调引用了 self.run_all，需要重建以拿到 patch 后的函数
    engine._watcher._trigger = lambda wf_id, reason: engine.run_all(wf_id, reason=reason)

    thread = threading.Thread(
        target=engine._watcher._loop,
        args=(7, ["watch"], 0.01, 0, "any_change"),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)
    engine._watcher._stop.set()
    thread.join(timeout=0.5)

    assert trigger_calls == [(7, "watch")]


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


def test_watch_loop_conservatively_triggers_when_scan_aborts(monkeypatch):
    logs: list[str] = []
    trigger_calls = []
    scan_calls = {"count": 0}

    def fake_scan_result(_folders, **_kwargs):
        scan_calls["count"] += 1
        if scan_calls["count"] == 1:
            return watcher_mod.MtimeScanResult({"watch": 0.0})
        if scan_calls["count"] == 2:
            return watcher_mod.MtimeScanResult({"watch": 0.0}, aborted=True, warning="scan aborted")
        return watcher_mod.MtimeScanResult({"watch": 0.0}, aborted=True, warning="scan aborted")

    watcher = watcher_mod.FileWatcher(
        logs.append,
        lambda workflow_id, reason: (trigger_calls.append((workflow_id, reason)), watcher._stop.set()),
        lambda: False,
    )
    monkeypatch.setattr(watcher_mod, "scan_folder_mtimes_result", fake_scan_result)

    thread = threading.Thread(
        target=watcher._loop,
        args=(5, ["watch"], 0.01, 0, "any_change"),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)
    watcher._stop.set()
    thread.join(timeout=0.5)

    assert trigger_calls == [(5, "watch")]
    assert any("不能确认“无变化”" in message for message in logs)
    assert any("保守触发工作流运行" in message for message in logs)


def test_watch_loop_all_folders_updated_since_success_uses_per_folder_success_baseline(monkeypatch):
    engine = WorkflowEngine()
    trigger_calls = []
    scan_calls = {"count": 0}

    def fake_scan_folder_mtimes(_folders, **_kwargs):
        scan_calls["count"] += 1
        if scan_calls["count"] == 1:
            return {"watch-a": 5, "watch-b": 10}
        if scan_calls["count"] == 2:
            return {"watch-a": 7, "watch-b": 10}
        if scan_calls["count"] == 3:
            return {"watch-a": 7, "watch-b": 11}
        engine._watcher._stop.set()
        return {"watch-a": 7, "watch-b": 11}

    def fake_run_all(workflow_id, reason="manual"):
        trigger_calls.append((workflow_id, reason))
        engine._watcher._stop.set()
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
    engine._watcher._trigger = lambda wf_id, reason: engine.run_all(wf_id, reason=reason)

    thread = threading.Thread(
        target=engine._watcher._loop,
        args=(9, ["watch-a", "watch-b"], 0.01, 0, "all_folders_updated_since_success"),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=0.5)
    engine._watcher._stop.set()
    thread.join(timeout=0.5)

    assert trigger_calls == [(9, "watch")]
