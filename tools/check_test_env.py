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
from dataclasses import dataclass
from pathlib import Path

MIN_PYTHON = (3, 10)


@dataclass(frozen=True)
class RequiredModule:
    import_name: str
    package_name: str
    reason: str


REQUIRED_MODULES = [
    RequiredModule("pytest", "pytest", "test runner"),
    RequiredModule("sqlalchemy", "SQLAlchemy", "models and database tests"),
    RequiredModule("PySide6", "PySide6", "engine Qt signals and UI tests"),
    RequiredModule("requests", "requests", "notifier and webhook tests"),
    RequiredModule("certifi", "certifi", "self-check and TLS diagnostics tests"),
]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    print(f"Project root: {root}")
    print(f"Python: {sys.version.split()[0]} ({platform.python_implementation()})")
    failed = False
    if sys.version_info < MIN_PYTHON:
        print(f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required")
        failed = True
    for module in REQUIRED_MODULES:
        if importlib.util.find_spec(module.import_name) is None:
            print(
                "ERROR: missing required test module: "
                f"{module.import_name} ({module.reason})"
            )
            failed = True
        else:
            print(f"OK: module available: {module.import_name}")
    if failed:
        print("\nInstall test dependencies, for example:")
        print("  python -m pip install -r requirements-ci.txt")
        print("or:")
        packages = " ".join(module.package_name for module in REQUIRED_MODULES)
        print(f"  python -m pip install {packages}")
        return 1
    print("Test environment preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
