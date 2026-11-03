# -*- coding: utf-8 -*-
"""WorkflowEngine.force_stop_run 分支行为回归测试（P0-1 修复）。

覆盖：活动目标协作取消；无关目标走持久化请求/孤儿清理，不误取消本机运行。
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import engine as engine_module
from engine import WorkflowEngine


from _force_stop_fakes import _make_engine


def test_force_stop_orphan_does_not_cancel_active_run(monkeypatch):
    # 引擎正在跑工作流 A(100)；用户从历史列表强制停止一条无关孤儿记录 B(200)。
    eng, calls = _make_engine(monkeypatch, running=True, active_ids={100}, current_id=100)
    eng.force_stop_run(200)
    assert eng._cancelled is False, "不得因停止孤儿记录而误杀正在运行的 A"
    assert calls["db_cleanup"], "孤儿记录应走数据库终态清理"


def test_force_stop_current_active_run_cancels(monkeypatch):
    # 用户强制停止的是当前正在运行的 A(100) → 应取消引擎，且不碰 DB 清理。
    eng, calls = _make_engine(monkeypatch, running=True, active_ids={100}, current_id=100)
    eng.force_stop_run(100)
    assert eng._cancelled is True, "目标为当前活动运行应触发取消"
    assert calls["db_cleanup"] == [], "引擎正跑的任务应由引擎自身 finalize"


def test_force_stop_during_startup_window_only_db_cleanup(monkeypatch):
    # 启动瞬间：_running 已置位但 _active_run_ids 尚未入队（空栈），_current_run_history_id
    # 仍是上一 run 的值。此窗口内停止任何无关历史记录 → 只走 DB 孤儿清理，绝不 kill 引擎
    # （P0-1 取舍：宁可 stop 无效，也不误杀正在运行的其它任务）。
    eng, calls = _make_engine(monkeypatch, running=True, active_ids={}, current_id=50)
    eng.force_stop_run(200)
    assert eng._cancelled is False, "启动窗口内停止无关记录不得 kill 引擎"
    assert calls["db_cleanup"], "无关记录只走 DB 清理"


def test_force_stop_nested_active_run_cancels(monkeypatch):
    eng, calls = _make_engine(monkeypatch, active_ids={100, 101}, current_id=100)
    eng.force_stop_run(101)
    assert eng._cancelled is True
    assert calls["db_cleanup"] == []


def test_force_stop_idle_does_db_cleanup(monkeypatch):
    eng, calls = _make_engine(monkeypatch, running=False, active_ids=(), current_id=None)
    eng.force_stop_run(300)
    assert calls["db_cleanup"], "引擎空闲时仅做 DB 清理"
    assert eng._cancelled is False