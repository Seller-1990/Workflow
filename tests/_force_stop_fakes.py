"""Explicit lightweight stop-dispatch fixture; never touches a real database."""
import threading
import engine as engine_module
from engine import WorkflowEngine


def _make_engine(monkeypatch, *, running=True, active_ids=(), current_id=None):
    """轻量构造引擎实例（绕过 __init__），只安装 force_stop_run 所需的字段。"""
    eng = WorkflowEngine.__new__(WorkflowEngine)
    eng._lock = threading.Lock()
    eng._running = running
    eng._active_run_ids = set(active_ids)
    eng._current_run_history_id = current_id
    eng._cancelled = False
    eng._emit_log = lambda *a, **k: None

    calls = {"db_cleanup": []}

    def _fake_force_cancel(*args, **kwargs):
        calls["db_cleanup"].append((args, kwargs))

    from database_run_ownership import StopState
    monkeypatch.setattr("engine_core.stop_dispatch.request_run_stop", lambda rid: StopState("ownerless"))
    monkeypatch.setattr(engine_module, "_force_cancel_run_record", _fake_force_cancel)
    return eng, calls
