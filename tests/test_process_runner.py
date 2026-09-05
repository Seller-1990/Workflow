import ast
from pathlib import Path

from runtime.process_runner import ProcessRunResult, build_subprocess_kwargs, run_process, start_process


def test_build_subprocess_kwargs_stringifies_cwd(tmp_path):
    kwargs = build_subprocess_kwargs(cwd=tmp_path, env={"A": "B"}, creationflags=0, stdout=-1)
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"] == {"A": "B"}
    assert kwargs["stdout"] == -1
    assert "creationflags" not in kwargs


def test_run_process_wraps_completed_process(monkeypatch):
    calls = []

    class Completed:
        args = ["tool", "arg"]
        returncode = 7
        stdout = "out"
        stderr = "err"

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr("runtime.process_runner.subprocess.run", fake_run)
    result = run_process(("tool", "arg"), check=False)
    assert result == ProcessRunResult(args=["tool", "arg"], returncode=7, stdout="out", stderr="err")
    assert calls == [(["tool", "arg"], {"check": False})]


def test_start_process_uses_argument_list(monkeypatch):
    calls = []
    sentinel = object()

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr("runtime.process_runner.subprocess.Popen", fake_popen)
    assert start_process(("tool", "arg"), stdout=-1) is sentinel
    assert calls == [(["tool", "arg"], {"stdout": -1})]


import pytest


def test_build_subprocess_kwargs_rejects_shell_true():
    with pytest.raises(ValueError, match="shell=True"):
        build_subprocess_kwargs(shell=True)


@pytest.mark.parametrize("shell_value", [1, "true"])
def test_build_subprocess_kwargs_rejects_truthy_shell_values(shell_value):
    with pytest.raises(ValueError, match="shell=True"):
        build_subprocess_kwargs(shell=shell_value)


def test_run_process_rejects_command_string_before_subprocess(monkeypatch):
    def fail_run(*_args, **_kwargs):  # pragma: no cover - should never be called
        raise AssertionError("subprocess.run should not receive command strings")

    monkeypatch.setattr("runtime.process_runner.subprocess.run", fail_run)
    with pytest.raises(TypeError, match="explicit sequence"):
        run_process("tool arg")


def test_start_process_rejects_empty_args_before_subprocess(monkeypatch):
    def fail_popen(*_args, **_kwargs):  # pragma: no cover - should never be called
        raise AssertionError("subprocess.Popen should not receive empty argv")

    monkeypatch.setattr("runtime.process_runner.subprocess.Popen", fail_popen)
    with pytest.raises(ValueError, match="must not be empty"):
        start_process(())


def test_run_process_preserves_timeout_cwd_env_contract(monkeypatch, tmp_path):
    calls = []

    class Completed:
        args = ["tool"]
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    env = {"WORKFLOW_FLAG": "1"}
    monkeypatch.setattr("runtime.process_runner.subprocess.run", fake_run)
    result = run_process(
        ("tool",),
        **build_subprocess_kwargs(cwd=tmp_path, env=env, timeout=3, text=True),
    )

    assert result.returncode == 0
    expected_kwargs = {"timeout": 3, "text": True, "cwd": str(tmp_path), "env": env, "stdin": -3}
    # F-05: POSIX 注入 start_new_session=True（进程组终止前置）；win32 不注入
    import sys as _sys
    if _sys.platform != "win32":
        expected_kwargs["start_new_session"] = True
    assert calls == [(["tool"], expected_kwargs)]
    assert calls[0][1]["env"] is not env


def test_runtime_source_uses_reviewed_subprocess_boundary_for_process_creation_calls():
    root = Path(__file__).resolve().parent.parent
    forbidden_calls = {
        ("subprocess", "run"),
        ("subprocess", "Popen"),
        ("subprocess", "call"),
        ("subprocess", "check_call"),
        ("subprocess", "check_output"),
        ("os", "system"),
        ("os", "popen"),
    }
    offenders: list[str] = []
    for source_path in (root / "src").rglob("*.py"):
        rel = source_path.relative_to(root).as_posix()
        if rel == "src/runtime/process_runner.py":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
                continue
            call_key = (func.value.id, func.attr)
            if call_key in forbidden_calls:
                offenders.append(f"{rel}:{node.lineno}: {call_key[0]}.{call_key[1]}")

    assert offenders == []
