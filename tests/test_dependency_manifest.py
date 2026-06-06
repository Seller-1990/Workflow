# -*- coding: utf-8 -*-
"""运行依赖清单契约测试"""

from __future__ import annotations

from pathlib import Path


def _requirements_names() -> set[str]:
    req_path = Path(__file__).resolve().parent.parent / "requirements.txt"
    names = set()
    for raw_line in req_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("==", 1)[0].split(">=", 1)[0].split("<", 1)[0].strip().lower()
        names.add(name)
    return names


def test_optional_runtime_imports_are_declared():
    names = _requirements_names()

    assert "watchdog" in names
    assert "psutil" in names


def test_unused_networkx_dependency_stays_removed():
    assert "networkx" not in _requirements_names()


def test_release_requirements_pin_direct_runtime_dependencies():
    release_path = Path(__file__).resolve().parent.parent / "requirements-release.txt"
    lines = [
        line.strip()
        for line in release_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert lines
    assert all("==" in line for line in lines)
    assert {line.split("==", 1)[0].lower() for line in lines} == _requirements_names()
