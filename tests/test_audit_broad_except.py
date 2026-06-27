from __future__ import annotations

import ast
import subprocess
import sys

import tools.audit_broad_except as audit


def test_current_repository_broad_excepts_are_approved_by_policy():
    assert audit.collect_findings(audit.Path(__file__).resolve().parents[1]) == []


def test_detects_bare_and_exception_handlers():
    tree = ast.parse("try:\n    pass\nexcept Exception:\n    pass\ntry:\n    pass\nexcept:\n    pass\n")
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    assert [audit.is_broad_exception(h) for h in handlers] == [True, True]


def test_baseline_loader_requires_non_negative_integer_counts(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"src/example.py": 1}', encoding="utf-8")

    assert audit.load_baseline(audit.Path(__file__).resolve().parents[1], baseline) == {"src/example.py": 1}

    baseline.write_text('{"src/example.py": -1}', encoding="utf-8")
    try:
        audit.load_baseline(audit.Path(__file__).resolve().parents[1], baseline)
    except ValueError as exc:
        assert "Invalid broad-except baseline entry" in str(exc)
    else:
        raise AssertionError("invalid baseline entry should fail")


def test_collect_findings_scans_explicit_path(tmp_path):
    bad = tmp_path / "bad_broad.py"
    bad.write_text("try:\n    pass\nexcept Exception:\n    pass\n", encoding="utf-8")

    findings = audit.collect_findings(audit.Path(__file__).resolve().parents[1], [bad], baseline={})

    assert findings
    assert findings[0][2] == "broad-except count increased from 0 to 1"


def test_cli_scans_explicit_path(tmp_path):
    bad = tmp_path / "bad_broad.py"
    bad.write_text("try:\n    pass\nexcept:\n    pass\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "tools/audit_broad_except.py", str(bad)],
        cwd=audit.Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "broad-except count increased from 0 to 1" in result.stdout



def test_cli_rejects_invalid_audit_targets(tmp_path):
    txt = tmp_path / "not_python.txt"
    txt.write_text("try:\n    pass\nexcept:\n    pass\n", encoding="utf-8")

    for target in [tmp_path / "missing.py", txt]:
        result = subprocess.run(
            [sys.executable, "tools/audit_broad_except.py", str(target)],
            cwd=audit.Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
        )

        assert result.returncode == 2
        assert "Invalid audit target" in result.stdout
