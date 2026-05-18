# -*- coding: utf-8 -*-
"""文件监听行为测试"""

import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine import WorkflowEngine


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


def test_watch_loop_replays_queued_change_after_current_run_finishes(monkeypatch):
    engine = WorkflowEngine()
    engine._running = True
    scan_calls = {"count": 0}
    trigger_calls = []

    # CA2: scan_mtime / scan_folder_mtimes 现在在 engine_core.watcher
    import engine_core.watcher as watcher_mod

    monkeypatch.setattr(watcher_mod, "scan_mtime", lambda folders: 0)

    def fake_scan_folder_mtimes(_folders):
        scan_calls["count"] += 1
        if scan_calls["count"] >= 3:
            engine._running = False
        return {"watch": 10}

    def fake_run_all(workflow_id, reason="manual"):
        trigger_calls.append((workflow_id, reason))
        engine._watcher._stop.set()
        return True

    monkeypatch.setattr(watcher_mod, "scan_folder_mtimes", fake_scan_folder_mtimes)
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
