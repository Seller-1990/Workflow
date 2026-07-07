# -*- coding: utf-8 -*-
"""Watch manager lifecycle contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine_core.watch_manager import WatchManager
from engine_core.watcher import FileWatcher


@dataclass
class _Workflow:
    id: int
    folders: list[str]
    watch_enabled: bool = True
    cooldown_seconds: int = 1
    settle_seconds: int = 0
    watch_mode: str = "any_change"

    def get_watch_folders(self):
        return list(self.folders)


class _AliveThread:
    def is_alive(self):
        return True


class _StuckWatcher:
    def __init__(self):
        self._thread = _AliveThread()
        self._folders = ["old"]
        self._cooldown = 1
        self._settle = 0
        self._mode = "any_change"

    def stop(self, join_timeout=1.0):
        return None


def _make_manager(logs: list[str]) -> WatchManager:
    return WatchManager(
        log_cb=logs.append,
        trigger_cb=lambda *_args: True,
        is_running_cb=lambda: False,
        emit_started_cb=lambda *_args: None,
        emit_stopped_cb=lambda *_args: None,
        validate_folders_cb=lambda folders: list(folders),
        detect_conflicts_cb=lambda folders, steps: [],
        get_steps_cb=lambda workflow_id: [],
    )


def test_start_watch_does_not_overwrite_stuck_existing_watcher(tmp_path: Path, monkeypatch):
    logs: list[str] = []
    manager = _make_manager(logs)
    old_watcher = _StuckWatcher()
    manager.watchers[7] = old_watcher
    created = []

    def make_watcher():
        created.append(True)
        raise AssertionError("should not create a replacement while old watcher is alive")

    monkeypatch.setattr(manager, "_make_watcher", make_watcher)

    started = manager.start_watch(_Workflow(id=7, folders=[str(tmp_path)]))

    assert started is False
    assert manager.watchers[7] is old_watcher
    assert created == []
    assert any("旧的文件监听线程仍在退出中" in message for message in logs)


def test_watchdog_partial_schedule_failure_falls_back_to_polling(tmp_path: Path, monkeypatch):
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    logs: list[str] = []

    class FakeObserver:
        def __init__(self):
            self.started = False
            self.scheduled = []

        def schedule(self, _handler, folder, recursive=True):
            if folder == str(bad):
                raise RuntimeError("schedule boom")
            self.scheduled.append(folder)

        def start(self):
            self.started = True

    class FakeHandler:
        pass

    monkeypatch.setitem(sys.modules, "watchdog", types.ModuleType("watchdog"))
    observers_mod = types.ModuleType("watchdog.observers")
    observers_mod.Observer = FakeObserver
    events_mod = types.ModuleType("watchdog.events")
    events_mod.FileSystemEventHandler = FakeHandler
    monkeypatch.setitem(sys.modules, "watchdog.observers", observers_mod)
    monkeypatch.setitem(sys.modules, "watchdog.events", events_mod)

    watcher = FileWatcher(logs.append, lambda *_args: True, lambda: False)

    watcher._start_watchdog_observer([str(good), str(bad)])

    assert watcher._observer is None
    assert any("部分监听目录未能启用事件驱动" in message for message in logs)
