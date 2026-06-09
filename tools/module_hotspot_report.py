#!/usr/bin/env python
"""Report large/high-complexity Python modules as refactoring hotspots."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

SCAN_DIRS = ["src", "tests"]


def build_rows(root: Path) -> list[tuple[int, int, int, str]]:
    rows: list[tuple[int, int, int, str]] = []
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            try:
                tree = ast.parse(text)
                funcs = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))
                classes = sum(isinstance(n, ast.ClassDef) for n in ast.walk(tree))
            except SyntaxError:
                funcs = classes = -1
            rows.append((len(text.splitlines()), funcs, classes, path.relative_to(root).as_posix()))
    rows.sort(reverse=True)
    return rows


def load_baseline(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    modules = data.get("modules", data)
    return {str(key): int(value) for key, value in modules.items()}


def write_baseline(path: Path, rows: list[tuple[int, int, int, str]]) -> None:
    payload = {
        "description": "Module line-count baseline. --fail-on-regression fails when a tracked module grows beyond this value.",
        "modules": {rel: line_count for line_count, _funcs, _classes, rel in rows},
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_regressions(rows: list[tuple[int, int, int, str]], baseline: dict[str, int]) -> list[tuple[str, int, int]]:
    current = {rel: line_count for line_count, _funcs, _classes, rel in rows}
    return [(rel, current[rel], allowed) for rel, allowed in baseline.items() if rel in current and current[rel] > allowed]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=20, help="Number of hotspot rows to print.")
    parser.add_argument("--max-lines", type=int, default=None, help="Optional line threshold for hotspot warnings.")
    parser.add_argument("--fail-on-threshold", action="store_true", help="Return non-zero when --max-lines is exceeded.")
    parser.add_argument("--baseline", type=Path, default=None, help="JSON file containing allowed per-module line counts.")
    parser.add_argument("--write-baseline", type=Path, default=None, help="Write the current line-count baseline and exit.")
    parser.add_argument("--fail-on-regression", action="store_true", help="Return non-zero when a module grows beyond --baseline.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    rows = build_rows(root)
    if args.write_baseline is not None:
        baseline_path = args.write_baseline if args.write_baseline.is_absolute() else root / args.write_baseline
        write_baseline(baseline_path, rows)
        print(f"Wrote hotspot baseline: {baseline_path}")
        return 0

    print("Top Hotspots")
    print("lines\tfunctions\tclasses\tpath")
    for line_count, funcs, classes, rel in rows[: args.top]:
        marker = " HOT" if args.max_lines is not None and line_count > args.max_lines else ""
        print(f"{line_count}\t{funcs}\t{classes}\t{rel}{marker}")
    exceeded = [row for row in rows if args.max_lines is not None and row[0] > args.max_lines]
    if exceeded:
        print(f"Hotspot threshold exceeded: {len(exceeded)} files over {args.max_lines} lines")

    regressions: list[tuple[str, int, int]] = []
    if args.baseline is not None:
        baseline_path = args.baseline if args.baseline.is_absolute() else root / args.baseline
        baseline = load_baseline(baseline_path)
        regressions = find_regressions(rows, baseline)
        if regressions:
            print(f"Hotspot baseline regressions: {len(regressions)}")
            for rel, current, allowed in regressions:
                print(f"{rel}: {current} lines > baseline {allowed}")
        else:
            print("Hotspot baseline regressions: 0")

    if args.fail_on_threshold and exceeded:
        return 1
    if args.fail_on_regression and regressions:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
