#!/usr/bin/env python
"""Workflow test runner wrapper.

Runs a lightweight environment preflight before delegating to pytest. Arguments
are passed through to pytest; when no arguments are supplied it defaults to the
project test suite.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[1]
    preflight = subprocess.run([sys.executable, str(root / "tools" / "check_test_env.py")], cwd=root)
    if preflight.returncode != 0:
        return preflight.returncode
    pytest_args = argv or ["tests"]
    return subprocess.run([sys.executable, "-m", "pytest", *pytest_args], cwd=root).returncode


if __name__ == "__main__":
    raise SystemExit(main())
