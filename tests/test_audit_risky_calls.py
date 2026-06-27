from __future__ import annotations

import ast
import subprocess
import sys

import tools.audit_risky_calls as audit


def test_current_repository_risky_calls_are_approved():
    assert audit.collect_findings(audit.Path(__file__).resolve().parents[1]) == []


def test_shell_true_is_rejected():
    node = ast.parse("import subprocess\nsubprocess.run('echo hi', shell=True)\n").body[1].value
    assert isinstance(node, ast.Call)
    assert audit.has_shell_true(node)


def test_unknown_risky_call_needs_allowlist():
    assert audit.is_risky_name("subprocess.run")
    assert ("new/file.py", "subprocess.run") not in audit.ALLOWED_RISKY_CALLS


def test_collect_findings_scans_explicit_path(tmp_path):
    bad = tmp_path / "bad_risky.py"
    bad.write_text("def run(user):\n    return eval(user)\n", encoding="utf-8")

    findings = audit.collect_findings(audit.Path(__file__).resolve().parents[1], [bad])

    assert findings
    assert findings[0][2] == "eval"


def test_cli_scans_explicit_path(tmp_path):
    bad = tmp_path / "bad_risky.py"
    bad.write_text("import subprocess\nsubprocess.run('echo hi', shell=True)\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "tools/audit_risky_calls.py", str(bad)],
        cwd=audit.Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "shell=True is forbidden" in result.stdout


def test_cli_rejects_invalid_audit_targets(tmp_path):
    txt = tmp_path / "not_python.txt"
    txt.write_text("subprocess.run('echo hi', shell=True)\n", encoding="utf-8")

    for target in [tmp_path / "missing.py", txt]:
        result = subprocess.run(
            [sys.executable, "tools/audit_risky_calls.py", str(target)],
            cwd=audit.Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
        )

        assert result.returncode == 2
        assert "Invalid audit target" in result.stdout
