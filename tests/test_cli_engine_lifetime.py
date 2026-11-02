# -*- coding: utf-8 -*-
"""CLI command ownership closes constructed engines without changing outcomes."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import cli
import database


@pytest.fixture
def cli_case(monkeypatch):
    engine = MagicMock(is_running=False, is_cancelled=False)
    engine.run.return_value = True
    engine.dry_run.return_value = None
    modes = SimpleNamespace(
        FULL="full", FROM_STEP="from_step", ONLY_STEP="only_step",
        STEP_RANGE="step_range", ONLY_STAGE="only_stage",
        FROM_STAGE="from_stage", RETRY_FAILED="retry_failed",
    )
    case = SimpleNamespace(
        engine=engine, runners=[], on_construct=None,
        factory=MagicMock(return_value=engine),
        query=MagicMock(return_value=SimpleNamespace(id=42, name="cleanup", uid="wf")),
        cleanup=MagicMock(), notification=MagicMock(),
    )
    engine_class = cli.CLIEngine

    def construct():
        runner = engine_class()
        runner.close = MagicMock(wraps=runner.close)
        case.runners.append(runner)
        if case.on_construct is not None:
            case.on_construct(runner)
        return runner

    monkeypatch.setattr(cli, "_ensure_qapp", lambda: None)
    monkeypatch.setattr(cli, "_app", None)
    monkeypatch.setattr(cli, "init_db", MagicMock())
    monkeypatch.setattr(cli, "_import_engine", lambda: (case.factory, None, modes, SimpleNamespace))
    monkeypatch.setattr(cli, "CLIEngine", construct)
    monkeypatch.setattr(cli, "resolve_workflow_id", MagicMock(return_value=42))
    monkeypatch.setattr(cli, "resolve_step_id", lambda _wid, value: {"B": 7, "D": 9}[value])
    monkeypatch.setattr(cli, "get_workflow_by_id", case.query)
    monkeypatch.setattr(cli, "get_run_histories_by_workflow", MagicMock(return_value=[]))
    monkeypatch.setattr(cli, "send_cli_notification", case.notification)
    monkeypatch.setattr(database, "cleanup_session", case.cleanup)
    return case


def _arguments(command):
    if command == "range":
        return ["run", "wf", "--from", "B", "--to", "D"]
    return [command, "wf"]


def _assert_closed_once(case):
    case.factory.assert_called_once_with()
    assert len(case.runners) == 1
    case.runners[0].close.assert_called_once_with()
    case.engine.shutdown.assert_called_once_with(wait=True)
    case.cleanup.assert_called_once_with()


@pytest.mark.parametrize("command", ["run", "range", "retry"])
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled", "caught-error"])
def test_command_outcomes_keep_exit_codes_and_close_once(cli_case, command, outcome):
    reached = []

    def run(*_args, **_kwargs):
        reached.append("engine.run")
        if outcome == "cancelled":
            finished = cli_case.engine.workflow_finished.connect.call_args.args[0]
            finished(42, "current-run", "cancelled")
        if outcome == "caught-error":
            raise RuntimeError("handled execution failure")
        return outcome == "success"

    cli_case.engine.run.side_effect = run
    with pytest.raises(SystemExit) as error:
        cli.main(_arguments(command))

    assert reached == ["engine.run"]
    assert error.value.code == (0 if outcome == "success" else 1)
    _assert_closed_once(cli_case)
    assert cli_case.notification.call_count == 1
    assert cli_case.notification.call_args.kwargs["cancelled"] is (outcome == "cancelled")
    if command == "range":
        assert cli_case.engine.run.call_args.kwargs["end_step_id"] == 9


@pytest.mark.parametrize("result", [None, False, True])
def test_dry_run_normal_return_closes_once(cli_case, result):
    cli_case.engine.dry_run.return_value = result
    assert cli.main(["dry-run", "wf"]) is None
    cli_case.engine.dry_run.assert_called_once_with(42)
    _assert_closed_once(cli_case)
    cli_case.notification.assert_not_called()


@pytest.mark.parametrize("command", ["run", "range", "retry"])
@pytest.mark.parametrize("boundary", ["query", "run", "output", "notification", "exit"])
def test_escaping_run_fault_closes_once_and_propagates(cli_case, monkeypatch, command, boundary):
    fault = SystemExit(17) if boundary == "exit" else (
        BrokenPipeError("output unavailable") if boundary in {"output", "notification"} else RuntimeError(boundary)
    )
    reached = []

    def fail(*_args, **_kwargs):
        reached.append(boundary)
        raise fault

    if boundary == "query":
        cli_case.query.side_effect = fail
    elif boundary == "output":
        monkeypatch.setattr(cli, "print", fail, raising=False)
    elif boundary == "notification":
        cli_case.notification.side_effect = fail
        monkeypatch.setattr(cli, "print", lambda *_args, **_kwargs: None, raising=False)
    elif boundary == "exit":
        cli_case.engine.run.side_effect = fail
    else:
        cli_case.on_construct = lambda runner: monkeypatch.setattr(runner, "run", fail)

    with pytest.raises(type(fault)) as error:
        cli.main(_arguments(command))

    assert error.value is fault
    assert reached == ([boundary, boundary] if boundary == "notification" else [boundary])
    _assert_closed_once(cli_case)
    if boundary == "notification":
        assert cli_case.notification.call_count == 2  # existing normal/error notification attempts
    else:
        cli_case.notification.assert_not_called()
    if boundary == "query":
        cli_case.engine.run.assert_not_called()


@pytest.mark.parametrize("boundary", ["dry-run", "output", "exit"])
def test_escaping_preview_fault_closes_once_and_propagates(cli_case, monkeypatch, boundary):
    fault = SystemExit(23) if boundary == "exit" else (
        BrokenPipeError("preview output unavailable") if boundary == "output" else RuntimeError(boundary)
    )
    reached = []

    def fail(*_args, **_kwargs):
        reached.append(boundary)
        raise fault

    if boundary == "output":
        monkeypatch.setattr(cli, "print", fail, raising=False)
        cli_case.engine.dry_run.side_effect = lambda _wid: cli.print("preview")
    else:
        cli_case.engine.dry_run.side_effect = fail

    with pytest.raises(type(fault)) as error:
        cli.main(["dry-run", "wf"])

    assert error.value is fault
    assert reached == [boundary]
    _assert_closed_once(cli_case)
    cli_case.engine.dry_run.assert_called_once_with(42)


@pytest.mark.parametrize("command", ["run", "retry", "dry-run"])
def test_constructor_failure_has_no_close_target(cli_case, command):
    fault = RuntimeError("construction failed")
    cli_case.factory.side_effect = fault

    with pytest.raises(RuntimeError) as error:
        cli.main(_arguments(command))

    assert error.value is fault
    cli_case.factory.assert_called_once_with()
    assert cli_case.runners == []
    cli_case.engine.shutdown.assert_not_called()
    cli_case.cleanup.assert_called_once_with()


@pytest.mark.parametrize("command", ["run", "retry", "dry-run"])
def test_resolution_exit_precedes_engine_ownership(cli_case, monkeypatch, command):
    resolve = MagicMock(side_effect=SystemExit(1))
    monkeypatch.setattr(cli, "resolve_workflow_id", resolve)

    with pytest.raises(SystemExit) as error:
        cli.main(_arguments(command))

    assert error.value.code == 1
    resolve.assert_called_once_with("wf")
    cli_case.factory.assert_not_called()
    assert cli_case.runners == []
    cli_case.engine.shutdown.assert_not_called()
    cli_case.cleanup.assert_called_once_with()
