# -*- coding: utf-8 -*-
"""watchdog observer 模式端到端集成测试（I1 缺口）

与 test_watch_engine.py 的全 mock 扫描不同，本文件使用真实 watchdog Observer
和真实临时目录，验证事件驱动链路：文件写入 → dirty → 扫描 → settle → 触发，
以及触发后基线刷新不会复触发。

时序说明：CI/慢盘留余量——正向断言用轮询等待（上限 15s），
负向断言（不应触发）用固定等待窗口。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import engine_core.watcher as watcher_mod

watchdog = pytest.importorskip("watchdog", reason="watchdog 未安装时跳过 observer 集成测试")


def _wait_until(predicate, timeout: float = 15.0, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _start_observer_watcher(
    folder: Path,
    trigger_calls: list,
    triggered_event: threading.Event,
    is_running_cb,
    logs: list,
):
    watcher = watcher_mod.FileWatcher(
        log_cb=logs.append,
        trigger_cb=lambda wf_id, reason: (
            trigger_calls.append((wf_id, reason)),
            triggered_event.set(),
            True,
        )[-1],
        is_running_cb=is_running_cb,
    )
    started = watcher.start(
        workflow_id=1,
        folders=[str(folder)],
        cooldown=1,
        settle=0,
        mode="any_change",
    )
    assert started is True
    return watcher


def test_observer_mode_triggers_once_on_real_file_change(tmp_path: Path):
    """真实 Observer：写文件触发一次；触发后基线已刷新，不复触发。"""
    watched = tmp_path / "watch"
    watched.mkdir()
    trigger_calls: list = []
    triggered_event = threading.Event()
    logs: list[str] = []

    watcher = _start_observer_watcher(
        watched, trigger_calls, triggered_event, lambda: False, logs
    )
    try:
        # 必须是事件驱动模式，而不是静默回退轮询
        assert watcher._observer is not None
        assert any("事件驱动 (watchdog)" in message for message in logs)

        # 等初始基线扫描完成后再写文件，避免文件被纳入初始基线
        time.sleep(1.0)
        (watched / "data.txt").write_text("第一批数据", encoding="utf-8")

        assert triggered_event.wait(timeout=15.0), "observer 模式下文件变更未在 15s 内触发"
        assert trigger_calls == [(1, "watch")]

        # 触发后基线已刷新：无新变更时不得复触发
        time.sleep(3.0)
        assert trigger_calls == [(1, "watch")]
    finally:
        watcher.stop(join_timeout=2.0)


def test_observer_mode_swallows_change_made_while_running(tmp_path: Path):
    """真实 Observer：运行期间的文件变更被吞并刷新基线，运行结束后不补跑。"""
    watched = tmp_path / "watch"
    watched.mkdir()
    trigger_calls: list = []
    triggered_event = threading.Event()
    logs: list[str] = []
    state = {"running": True}

    watcher = _start_observer_watcher(
        watched, trigger_calls, triggered_event, lambda: state["running"], logs
    )
    try:
        assert watcher._observer is not None
        time.sleep(1.0)

        # "运行期间"写出文件（模拟工作流输出）
        (watched / "output.xlsx").write_text("运行输出", encoding="utf-8")

        # 等吞并日志出现（运行中吞并；若运行恰在窗口边缘结束则为重叠吞并——两者均为正确行为）
        swallowed = _wait_until(
            lambda: any(
                ("检测到运行期间文件变更" in message) or ("与刚结束的运行重叠" in message)
                for message in logs
            ),
            timeout=15.0,
        )
        assert swallowed, f"未观察到运行期变更吞并日志，实际日志：{logs}"

        # 运行结束后，被吞并的变更不得补跑
        state["running"] = False
        time.sleep(3.0)
        assert trigger_calls == []
    finally:
        watcher.stop(join_timeout=2.0)
