# -*- coding: utf-8 -*-
"""The import/run entrypoint owns shutdown from construction to final output."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "_import_and_run.py"


@pytest.fixture
def import_run_case(monkeypatch):
    app = SimpleNamespace(processEvents=MagicMock())
    monkeypatch.setattr("PySide6.QtWidgets.QApplication", SimpleNamespace(instance=lambda: app))
    spec = importlib.util.spec_from_file_location("_import_and_run_lifetime_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    engine = MagicMock(is_running=False)
    engine.run.return_value = True
    factory = MagicMock(return_value=engine)
    monkeypatch.setattr(module, "WorkflowEngine", factory)
    monkeypatch.setattr(module, "find_workflow", MagicMock(return_value=SimpleNamespace(id=42, name="cleanup")))
    monkeypatch.setattr(module, "get_run_histories_by_workflow", MagicMock(return_value=[]))
    monkeypatch.setattr(module, "get_step_logs_by_run", MagicMock(return_value=[]))
    return SimpleNamespace(module=module, engine=engine, app=app, factory=factory)


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_normal_import_run_outcome_shuts_down_once(import_run_case, outcome):
    case = import_run_case
    reached = []
    events = []
    case.app.processEvents.side_effect = lambda: events.append("events")
    case.engine.shutdown.side_effect = lambda **_kwargs: events.append("shutdown")

    def run(*_args, **_kwargs):
        reached.append("run")
        if outcome == "cancelled":
            finished = case.engine.workflow_finished.connect.call_args.args[0]
            finished(42, "cancelled-run", "cancelled")
        return outcome == "success"

    case.engine.run.side_effect = run
    with pytest.raises(SystemExit) as error:
        case.module.cmd_run("cleanup")

    assert reached == ["run"]
    assert error.value.code == (0 if outcome == "success" else 1)
    case.factory.assert_called_once_with()
    case.engine.shutdown.assert_called_once_with(wait=True)
    assert events == ["events", "shutdown", *(["events"] * 100)]
    assert case.engine.run.call_args.kwargs["signal_policy"].send_notification is True


@pytest.mark.parametrize(
    "boundary",
    ["signal", "run", "events", "output", "history", "logs", "failure-output", "exit", "interrupt"],
)
def test_import_run_escaping_fault_shuts_down_once_and_propagates(import_run_case, monkeypatch, boundary):
    case = import_run_case
    fault = (
        SystemExit(19) if boundary == "exit" else
        KeyboardInterrupt() if boundary == "interrupt" else
        BrokenPipeError("output unavailable") if boundary in {"output", "failure-output"} else
        RuntimeError(boundary)
    )
    reached = []
    events = []
    case.engine.shutdown.side_effect = lambda **_kwargs: events.append("shutdown")

    def fail(*_args, **_kwargs):
        reached.append(boundary)
        raise fault

    if boundary == "signal":
        case.engine.log_output.connect.side_effect = fail
    elif boundary in {"run", "exit", "interrupt"}:
        case.engine.run.side_effect = fail
    elif boundary == "events":
        case.app.processEvents.side_effect = fail
    elif boundary in {"history", "logs", "failure-output"}:
        case.engine.run.return_value = False
        if boundary == "history":
            case.module.get_run_histories_by_workflow.side_effect = fail
        else:
            case.module.get_run_histories_by_workflow.return_value = [SimpleNamespace(id=5)]
            if boundary == "logs":
                case.module.get_step_logs_by_run.side_effect = fail
            else:
                case.module.get_step_logs_by_run.return_value = [SimpleNamespace(status="failure", error_message="failed")]

    if boundary in {"output", "failure-output"}:
        def print_until_fault(*values, **_kwargs):
            message = str(values[0]) if values else ""
            prefix = "\n最终结果:" if boundary == "output" else "  失败:"
            if message.startswith(prefix):
                fail()

        monkeypatch.setattr(case.module, "print", print_until_fault, raising=False)

    with pytest.raises(type(fault)) as error:
        case.module.cmd_run("cleanup")

    assert error.value is fault
    assert reached == [boundary]
    case.factory.assert_called_once_with()
    case.engine.shutdown.assert_called_once_with(wait=True)
    assert events == ["shutdown"]
    if boundary == "signal":
        case.engine.run.assert_not_called()
    else:
        case.engine.run.assert_called_once()
    if boundary in {"run", "exit", "interrupt"}:
        case.app.processEvents.assert_not_called()
    elif boundary == "events":
        assert case.app.processEvents.call_count == 1


@pytest.mark.parametrize("shutdown_error", [RuntimeError("shutdown failed"), OSError("shutdown failed")])
def test_shutdown_warning_keeps_normal_exit_and_final_event_drain(import_run_case, shutdown_error, capsys):
    case = import_run_case
    case.engine.shutdown.side_effect = shutdown_error

    with pytest.raises(SystemExit) as error:
        case.module.cmd_run("cleanup")

    assert error.value.code == 0
    case.engine.shutdown.assert_called_once_with(wait=True)
    assert case.app.processEvents.call_count == 101
    assert "警告: 引擎收尾失败: shutdown failed" in capsys.readouterr().out


def test_original_run_fault_survives_existing_caught_shutdown_error(import_run_case):
    case = import_run_case
    fault = RuntimeError("run fault")
    reached = []

    def run(*_args, **_kwargs):
        reached.append("run")
        raise fault

    case.engine.run.side_effect = run
    case.engine.shutdown.side_effect = OSError("shutdown warning")

    with pytest.raises(RuntimeError) as error:
        case.module.cmd_run("cleanup")

    assert error.value is fault
    assert reached == ["run"]
    case.engine.shutdown.assert_called_once_with(wait=True)
    case.app.processEvents.assert_not_called()


@pytest.mark.parametrize("boundary", ["run", "output"])
def test_shutdown_warning_does_not_replace_primary_fault(import_run_case, monkeypatch, boundary):
    case = import_run_case
    fault = RuntimeError("original run fault") if boundary == "run" else BrokenPipeError("original output fault")
    reached = []
    warning_output = []

    def print_until_fault(*values, **_kwargs):
        message = str(values[0]) if values else ""
        if message.startswith("警告: 引擎收尾失败:"):
            warning_output.append(message)
            raise BrokenPipeError("secondary warning output fault")
        if boundary == "output" and message.startswith("\n最终结果:"):
            reached.append("output")
            raise fault

    def run(*_args, **_kwargs):
        reached.append("run")
        if boundary == "run":
            raise fault
        return True

    monkeypatch.setattr(case.module, "print", print_until_fault, raising=False)
    case.engine.run.side_effect = run
    case.engine.shutdown.side_effect = OSError("shutdown warning")

    with pytest.raises(type(fault)) as error:
        case.module.cmd_run("cleanup")

    assert error.value is fault
    assert reached == (["run"] if boundary == "run" else ["run", "output"])
    assert warning_output == []
    case.engine.shutdown.assert_called_once_with(wait=True)


def test_import_run_constructor_failure_has_no_shutdown_target(import_run_case):
    case = import_run_case
    fault = RuntimeError("construction failed")
    case.factory.side_effect = fault

    with pytest.raises(RuntimeError) as error:
        case.module.cmd_run("cleanup")

    assert error.value is fault
    case.factory.assert_called_once_with()
    case.engine.shutdown.assert_not_called()
    case.engine.run.assert_not_called()


def test_missing_import_workflow_exits_before_engine_construction(import_run_case):
    case = import_run_case
    case.module.find_workflow.return_value = None

    with pytest.raises(SystemExit) as error:
        case.module.cmd_run("missing")

    assert error.value.code == 1
    case.factory.assert_not_called()
    case.engine.shutdown.assert_not_called()
