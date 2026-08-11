#!/usr/bin/env python
"""Failing audit for risky dynamic execution and subprocess call sites.

The gate intentionally permits the current reviewed call sites, but any new
``eval``/``exec``/``compile``/``os.system``/``subprocess`` call must be added to
``ALLOWED_RISKY_CALLS`` with a human-readable reason.  ``shell=True`` is never
accepted by this guard.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

SCAN_DIRS = ["src", "tests", "tools"]
RISKY_NAMES = {"eval", "exec", "compile"}
RISKY_ATTRS = {
    ("os", "system"),
    ("os", "popen"),
    ("subprocess", "run"),
    ("subprocess", "Popen"),
    ("subprocess", "call"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
}

ALLOWED_RISKY_CALLS: dict[tuple[str, str], str] = {
    ("src/executors/base.py", "subprocess.run"): "Executor base checks external process availability with argument-list subprocess execution.",
    ("src/runtime/process_runner.py", "subprocess.Popen"): "Central reviewed process-start boundary used by runtime executors. Callers must pass argument lists, never shell=True.",
    ("src/runtime/process_runner.py", "subprocess.run"): "Central reviewed process-run boundary used by runtime executors. Callers must pass argument lists, never shell=True.",
    ("tests/test_audit_broad_except.py", "subprocess.run"): "Audit CLI regression test executes the broad-except audit script with explicit args and no shell.",
    ("tests/test_audit_risky_calls.py", "subprocess.run"): "Audit CLI regression test executes the risky-call audit script with explicit args and no shell.",
    ("tests/test_cli_contracts.py", "subprocess.run"): "CLI contract test executes the repository CLI in a child interpreter.",
    ("tests/test_cli_subprocess.py", "subprocess.run"): "CLI subprocess regression test validates command behavior.",
    ("tests/test_dependency_manifest.py", "subprocess.run"): "Dependency manifest test invokes the checker script.",
    ("tests/test_import_and_run_warnings.py", "subprocess.run"): "Import-and-run warning tests run _import_and_run.py in a child interpreter for WORKFLOW_APP_DATA_DIR isolation (same pattern as test_import_warnings).",
    ("tests/test_risk_path_review.py", "subprocess.run"): "R1 risk-path review tests run cli.py / _import_and_run.py in child interpreters for WORKFLOW_APP_DATA_DIR isolation (same pattern as test_cli_contracts).",
    ("tests/test_import_warnings.py", "subprocess.run"): "Import-warning tests run CLI import in a child interpreter for WORKFLOW_APP_DATA_DIR isolation (same pattern as test_cli_contracts).",
    ("tests/test_install_hooks.py", "subprocess.run"): "Hook installer tests run git and the installer CLI against a throwaway temp repository using explicit args.",
    ("tests/test_main_self_check.py", "subprocess.run"): "Self-check test runs the packaged entrypoint contract.",
    ("tools/install_hooks.py", "subprocess.run"): "Hook installer sets/unsets git core.hooksPath via argument-list git invocations, never shell=True.",
    ("tools/repo_hygiene.py", "subprocess.run"): "Repository hygiene tool shells out to git using explicit args.",
    ("tools/run_tests.py", "subprocess.run"): "Test runner wrapper delegates to pytest/collect commands using explicit args.",
}


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: list[str] = []
        cur: ast.AST | None = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
            return ".".join(reversed(parts))
    return None


def is_risky_name(name: str | None) -> bool:
    return bool(name) and (name in RISKY_NAMES or tuple(name.split(".")[-2:]) in RISKY_ATTRS)


def has_shell_true(node: ast.Call) -> bool:
    return any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)


def iter_python_files(root: Path, targets: list[Path] | None = None) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    if targets:
        for target in targets:
            path = target if target.is_absolute() else root / target
            if path.is_file() and path.suffix == ".py":
                try:
                    rel = path.relative_to(root).as_posix()
                except ValueError:
                    rel = path.as_posix()
                files.append((path, rel))
            elif path.is_dir():
                for py_file in path.rglob("*.py"):
                    try:
                        rel = py_file.relative_to(root).as_posix()
                    except ValueError:
                        rel = py_file.as_posix()
                    files.append((py_file, rel))
        return files

    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            files.append((path, path.relative_to(root).as_posix()))
    return files


def validate_targets(root: Path, targets: list[Path]) -> list[str]:
    errors: list[str] = []
    for target in targets:
        path = target if target.is_absolute() else root / target
        if not path.exists():
            errors.append(f"{target}: path does not exist")
        elif path.is_file() and path.suffix != ".py":
            errors.append(f"{target}: expected a .py file or directory")
    return errors


def collect_findings(root: Path, targets: list[Path] | None = None) -> list[tuple[str, int, str, str]]:
    findings: list[tuple[str, int, str, str]] = []
    for path, rel in iter_python_files(root, targets):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = call_name(node.func)
                if not is_risky_name(name):
                    continue
                key = (rel, name or "")
                if has_shell_true(node):
                    findings.append((rel, node.lineno, name or "<unknown>", "shell=True is forbidden"))
                elif key not in ALLOWED_RISKY_CALLS:
                    findings.append((rel, node.lineno, name or "<unknown>", "missing allowlist entry"))
                elif not ALLOWED_RISKY_CALLS[key].strip():
                    findings.append((rel, node.lineno, name or "<unknown>", "allowlist reason is empty"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit risky dynamic execution and subprocess call sites.")
    parser.add_argument("paths", nargs="*", type=Path, help="Optional Python files or directories to scan. Defaults to src/tests/tools.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    if args.paths:
        target_errors = validate_targets(root, args.paths)
        if target_errors:
            for error in target_errors:
                print(f"Invalid audit target: {error}")
            return 2
    findings = collect_findings(root, args.paths or None)
    print(f"Unapproved risky call sites: {len(findings)}")
    for rel, line, name, reason in findings:
        print(f"{rel}:{line}: {name}: {reason}")
    if not findings:
        print(f"Approved risky call allowlist entries: {len(ALLOWED_RISKY_CALLS)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
