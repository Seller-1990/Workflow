# -*- coding: utf-8 -*-
"""RunWorker background execution boundary tests."""

from types import SimpleNamespace

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import ui.run_worker as run_worker_module
from ui.run_worker import RunWorker


def test_run_worker_invokes_runner_in_background_thread():
    calls = []
    engine = object()

    def runner(target_engine, *, workflow_id, mode, param):
        calls.append((target_engine, workflow_id, mode, param))

    worker = RunWorker(
        engine,
        workflow_id=7,
        mode="only_step",
        param=13,
        runner=runner,
    )

    worker.start()
    worker.join(timeout=2)

    assert worker.is_alive() is False
    assert calls == [(engine, 7, "only_step", 13)]


def test_run_worker_routes_runner_exception_to_queued_engine_log(monkeypatch):
    calls = []
    engine = object()

    def runner(_target_engine, *, workflow_id, mode, param):
        raise RuntimeError(f"boom {workflow_id} {mode} {param}")

    monkeypatch.setattr(
        run_worker_module,
        "QMetaObject",
        SimpleNamespace(
            invokeMethod=lambda target, method, connection, arg: calls.append(
                (target, method, connection, arg)
            )
        ),
    )
    monkeypatch.setattr(
        run_worker_module,
        "Q_ARG",
        lambda type_name, value: ("arg", type_name, value),
    )

    worker = RunWorker(
        engine,
        workflow_id=7,
        mode="from_step",
        param=3,
        runner=runner,
    )

    worker.start()
    worker.join(timeout=2)

    assert worker.is_alive() is False
    assert calls == [
        (
            engine,
            "_emit_log",
            run_worker_module.Qt.QueuedConnection,
            ("arg", str, "运行异常: boom 7 from_step 3"),
        )
    ]
