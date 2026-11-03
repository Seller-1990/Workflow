# -*- coding: utf-8 -*-
"""Legacy import/run flags remain compatible without path-consent side effects."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock

import pytest


IMPORT_AND_RUN_SCRIPT = Path(__file__).resolve().parents[1] / "_import_and_run.py"


@pytest.fixture
def import_and_run(monkeypatch):
    app = SimpleNamespace(processEvents=MagicMock())
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr("PySide6.QtWidgets.QApplication", SimpleNamespace(instance=lambda: app))
    spec = importlib.util.spec_from_file_location("_import_and_run_test", IMPORT_AND_RUN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("legacy_args", "legacy_kwargs"),
    [
        ((), {}),
        ((False,), {}),
        ((True,), {}),
        ((), {"auto_confirm": False}),
        ((), {"auto_confirm": True}),
    ],
    ids=["default", "positional-false", "positional-true", "keyword-false", "keyword-true"],
)
def test_cmd_run_legacy_argument_has_no_consent_side_effects(
    monkeypatch, import_and_run, legacy_args, legacy_kwargs,
):
    import database
    import risk_path_review

    module = import_and_run
    workflow = SimpleNamespace(
        id=42, name="兼容工作流", risky_paths_review_required=True,
        risky_paths_revision=7, risky_paths_confirmed_digest="scoped-v1:stale",
    )
    find = MagicMock(return_value=workflow)
    monkeypatch.setattr(module, "find_workflow", find)
    engine = MagicMock(is_running=False)
    engine.run.return_value = True
    monkeypatch.setattr(module, "WorkflowEngine", MagicMock(return_value=engine))
    consent_spies = [
        (database, "get_steps_by_workflow"),
        (database, "confirm_risky_paths"),
        (risk_path_review, "build_run_plan"),
        (risk_path_review, "evaluate_run_plan"),
    ]
    spies = []
    for owner, name in consent_spies:
        spy = MagicMock(side_effect=AssertionError(f"unexpected consent access: {name}"))
        monkeypatch.setattr(owner, name, spy)
        spies.append(spy)
    ask = MagicMock(side_effect=AssertionError("must not ask for path consent"))
    tty = MagicMock(side_effect=AssertionError("must not inspect TTY for path consent"))
    monkeypatch.setattr("builtins.input", ask)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=tty))

    with pytest.raises(SystemExit) as error:
        module.cmd_run("兼容工作流", *legacy_args, **legacy_kwargs)

    assert error.value.code == 0
    find.assert_called_once_with("兼容工作流")
    engine.run.assert_called_once_with(
        42, module.RunMode.FULL, reason="cli", signal_policy=ANY,
    )
    assert engine.run.call_args.kwargs["signal_policy"].send_notification is True
    engine.shutdown.assert_called_once_with(wait=True)
    for spy in [*spies, ask, tty]:
        spy.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        ["run", "兼容工作流"],
        ["--confirm-risky-paths", "run", "兼容工作流"],
        ["run", "兼容工作流", "--confirm-risky-paths"],
        ["--auto"],
        ["--confirm-risky-paths", "--auto"],
    ],
)
def test_legacy_flag_positions_preserve_command_dispatch(monkeypatch, import_and_run, arguments):
    module = import_and_run
    monkeypatch.setattr(module, "init_db", MagicMock())
    run = MagicMock()
    imported = MagicMock()
    monkeypatch.setattr(module, "cmd_run", run)
    monkeypatch.setattr(module, "cmd_import", imported)
    monkeypatch.setattr(sys, "argv", [str(IMPORT_AND_RUN_SCRIPT), *arguments])

    module.main()

    run.assert_called_once_with("月度数据处理" if "--auto" in arguments else "兼容工作流", auto_confirm=ANY)
    if "--auto" in arguments:
        imported.assert_called_once_with(module.DEFAULT_WORKFLOWS_JSON)
    else:
        imported.assert_not_called()


@pytest.mark.parametrize("arguments", [["--help"], ["run", "--help"]])
def test_legacy_confirmation_flag_help_describes_noop(monkeypatch, import_and_run, capsys, arguments):
    monkeypatch.setattr(import_and_run, "init_db", MagicMock())
    monkeypatch.setattr(sys, "argv", [str(IMPORT_AND_RUN_SCRIPT), *arguments])

    with pytest.raises(SystemExit) as error:
        import_and_run.main()

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "--confirm-risky-paths" in output
    assert "兼容旧脚本的无操作参数" in output
    assert "无需风险路径二次确认" in output
    assert "自动确认导入风险路径" not in output
    assert "非交互环境必须显式指定" not in output
