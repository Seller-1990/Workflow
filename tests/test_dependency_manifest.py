# -*- coding: utf-8 -*-
"""运行依赖清单契约测试"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path


def _requirements_names(filename: str) -> set[str]:
    req_path = Path(__file__).resolve().parent.parent / filename
    names = set()
    for raw_line in req_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("==", 1)[0].split(">=", 1)[0].split("<", 1)[0].strip().lower()
        names.add(name)
    return names


def test_runtime_requirements_cover_all_direct_dependencies():
    names = _requirements_names("requirements.txt")

    assert names == {
        "pyside6",
        "sqlalchemy",
        "pywin32",
        "pywinauto",
        "watchdog",
        "psutil",
        "requests",
        "certifi",
    }


def test_unused_networkx_dependency_stays_removed():
    assert "networkx" not in _requirements_names("requirements.txt")


def test_release_requirements_pin_runtime_dependencies_and_packaging_toolchain():
    runtime_names = _requirements_names("requirements.txt")
    release_names = _requirements_names("requirements-release.txt")

    assert runtime_names <= release_names
    assert release_names == runtime_names | {"pyinstaller"}


def test_ci_requirements_pin_runtime_dependencies_and_pytest():
    runtime_names = _requirements_names("requirements.txt")
    ci_names = _requirements_names("requirements-ci.txt")

    assert runtime_names <= ci_names
    assert ci_names == runtime_names | {"pytest"}


def test_release_requirements_are_fully_pinned():
    release_path = Path(__file__).resolve().parent.parent / "requirements-release.txt"
    lines = [
        line.strip()
        for line in release_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert lines
    assert all("==" in line for line in lines)


def test_ci_requirements_are_fully_pinned():
    ci_path = Path(__file__).resolve().parent.parent / "requirements-ci.txt"
    lines = [
        line.strip()
        for line in ci_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert lines
    assert all("==" in line for line in lines)


def test_ci_uses_locked_dependency_manifest():
    ci_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
    content = ci_path.read_text(encoding="utf-8")

    assert "pip install -r requirements-ci.txt" in content
    assert "pip install -r requirements.txt" not in content
    assert "pip install pytest" not in content


def test_ci_dependency_manifest_is_tracked_in_git():
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "requirements-ci.txt"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "requirements-ci.txt must be tracked in Git for fresh-checkout CI"


def test_runtime_dependency_import_smoke():
    modules = [
        "PySide6",
        "sqlalchemy",
        "pywinauto",
        "watchdog",
        "psutil",
        "requests",
        "certifi",
        "pythoncom",
    ]

    for module in modules:
        importlib.import_module(module)
