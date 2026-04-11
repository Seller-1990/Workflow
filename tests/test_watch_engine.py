# -*- coding: utf-8 -*-
"""文件监听行为测试"""

import sys
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
    assert engine._watch_thread is None


def test_stop_watch_stops_sleeping_thread_quickly(tmp_path: Path):
    engine = WorkflowEngine()
    folder = tmp_path / "watch"
    folder.mkdir()
    workflow = MockWorkflow(folders=[str(folder)], cooldown_seconds=30)

    started = engine.start_watch(workflow)

    assert started is True
    assert engine._watch_thread is not None
    assert engine._watch_thread.is_alive()

    started_at = time.perf_counter()
    engine.stop_watch(join_timeout=0.5)
    elapsed = time.perf_counter() - started_at

    assert elapsed < 1.0
    assert engine._watch_thread is None or not engine._watch_thread.is_alive()
