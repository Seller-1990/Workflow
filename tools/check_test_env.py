#!/usr/bin/env python
"""Preflight checks for the Workflow test environment.

This script intentionally performs only read-only checks and prints actionable
messages before pytest is invoked. It prevents CI/local runs from failing with
opaque errors such as "No module named pytest".
"""
from __future__ import annotations

import importlib.util
import platform
import sys
from pathlib import Path

REQUIRED_MODULES = ["pytest"]
MIN_PYTHON = (3, 10)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print(f"Project root: {root}")
    print(f"Python: {sys.version.split()[0]} ({platform.python_implementation()})")
    failed = False
    if sys.version_info < MIN_PYTHON:
        print(f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required")
        failed = True
    for name in REQUIRED_MODULES:
        if importlib.util.find_spec(name) is None:
            print(f"ERROR: missing required test module: {name}")
            failed = True
        else:
            print(f"OK: module available: {name}")
    if failed:
        print("\nInstall test dependencies, for example:")
        print("  python -m pip install -r requirements-ci.txt")
        print("or:")
        print("  python -m pip install -r requirements.txt pytest")
        return 1
    print("Test environment preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
