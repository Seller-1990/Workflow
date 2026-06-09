# -*- coding: utf-8 -*-
"""Dependency consistency checker tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import check_requirements_consistency as check_req


def test_parse_req_line_normalizes_names_and_specs():
    assert check_req.parse_req_line("PySide6==6.6.0  # GUI") == ("pyside6", "==6.6.0")
    assert check_req.parse_req_line("my_pkg>=1") == ("my-pkg", ">=1")
    assert check_req.parse_req_line("# comment") is None
    assert check_req.parse_req_line("-r other.txt") is None


def test_requirement_checker_reports_pinned_drift(tmp_path, monkeypatch, capsys):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    fake_script = tools_dir / "check_requirements_consistency.py"
    fake_script.write_text("", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("demo>=1\n", encoding="utf-8")
    (tmp_path / "requirements-ci.txt").write_text("demo==1.0\n", encoding="utf-8")
    (tmp_path / "requirements-release.txt").write_text("demo==2.0\n", encoding="utf-8")

    monkeypatch.setattr(check_req, "__file__", str(fake_script))

    assert check_req.main() == 1
    assert "demo" in capsys.readouterr().out
