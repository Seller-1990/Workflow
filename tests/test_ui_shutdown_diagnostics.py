# -*- coding: utf-8 -*-
"""Close-path failures remain observable without requiring a real engine."""

from types import SimpleNamespace

from ui.main_window import MainWindow

def test_close_event_logs_shutdown_failure(monkeypatch, caplog):
    class Event:
        accepted = False

        def accept(self):
            self.accepted = True

        def ignore(self):
            raise AssertionError("close should not be ignored")

    engine = SimpleNamespace(
        is_running=False,
        workflow_started=SimpleNamespace(disconnect=lambda *_args: None),
        workflow_finished=SimpleNamespace(disconnect=lambda *_args: None),
        step_started=SimpleNamespace(disconnect=lambda *_args: None),
        step_finished=SimpleNamespace(disconnect=lambda *_args: None),
        log_output=SimpleNamespace(disconnect=lambda *_args: None),
        progress_updated=SimpleNamespace(disconnect=lambda *_args: None),
        error_details=SimpleNamespace(disconnect=lambda *_args: None),
        shutdown=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("shutdown failed")),
    )
    window = SimpleNamespace(
        engine=engine,
        _confirm_discard_unsaved=lambda **_kwargs: True,
        log_panel=SimpleNamespace(append_log=lambda *_args: None),
        _on_workflow_started=lambda *_args: None,
        _on_workflow_finished=lambda *_args: None,
        _on_step_started=lambda *_args: None,
        _on_step_finished=lambda *_args: None,
        _on_progress_updated=lambda *_args: None,
        _on_error_details=lambda *_args: None,
    )
    event = Event()

    with caplog.at_level("ERROR", logger="ui.main_window"):
        MainWindow.closeEvent(window, event)

    assert event.accepted is True
    assert "关闭工作流引擎失败" in caplog.text
    assert "shutdown failed" in caplog.text
