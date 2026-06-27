#!/usr/bin/env python
"""Failing audit for broad exception handler regressions.

Existing broad exception handlers are tracked by a per-file baseline in
``quality/broad_except_baseline.json``. New files or increases in existing files
fail this gate unless the baseline is intentionally updated during debt review.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

SCAN_DIRS = ["src", "tests"]
BASELINE_PATH = Path("quality/broad_except_baseline.json")


def is_broad_exception(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name):
        return handler.type.id in {"Exception", "BaseException"}
    if isinstance(handler.type, ast.Tuple):
        return any(isinstance(elt, ast.Name) and elt.id in {"Exception", "BaseException"} for elt in handler.type.elts)
    return False


def load_baseline(root: Path, baseline_path: Path = BASELINE_PATH) -> dict[str, int]:
    path = baseline_path if baseline_path.is_absolute() else root / baseline_path
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Broad-except baseline must be a JSON object: {path}")
    baseline: dict[str, int] = {}
    for rel, count in raw.items():
        if not isinstance(rel, str) or not isinstance(count, int) or count < 0:
            raise ValueError(f"Invalid broad-except baseline entry: {rel!r}: {count!r}")
        baseline[rel] = count
    return baseline


def count_broad_exceptions(path: Path) -> tuple[int, list[int]]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and is_broad_exception(node):
            lines.append(node.lineno)
    return len(lines), lines


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


def collect_findings(
    root: Path,
    targets: list[Path] | None = None,
    baseline: dict[str, int] | None = None,
) -> list[tuple[str, int, str]]:
    expected = load_baseline(root) if baseline is None else baseline
    findings: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for path, rel in iter_python_files(root, targets):
        seen.add(rel)
        try:
            count, lines = count_broad_exceptions(path)
        except SyntaxError as exc:
            findings.append((rel, exc.lineno or 0, "SYNTAX_ERROR"))
            continue
        allowed = expected.get(rel, 0)
        if count > allowed:
            first_new_line = lines[allowed] if allowed < len(lines) else 0
            findings.append((rel, first_new_line, f"broad-except count increased from {allowed} to {count}"))
    if targets is None:
        for rel in sorted(set(expected) - seen):
            findings.append((rel, 0, "baseline entry has no matching Python file"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit broad exception handlers in Workflow Python files.")
    parser.add_argument("paths", nargs="*", type=Path, help="Optional Python files or directories to scan. Defaults to src/tests.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    if args.paths:
        target_errors = validate_targets(root, args.paths)
        if target_errors:
            for error in target_errors:
                print(f"Invalid audit target: {error}")
            return 2
    try:
        findings = collect_findings(root, args.paths or None)
    except ValueError as exc:
        print(f"Invalid broad-except baseline: {exc}")
        return 2
    print(f"Broad exception regressions: {len(findings)}")
    for rel, line, kind in findings:
        print(f"{rel}:{line}: {kind}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
