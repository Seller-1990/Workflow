# -*- coding: utf-8 -*-
"""Application entrypoint self-check tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_main_self_check_subprocess_uses_isolated_app_data(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["WORKFLOW_APP_DATA_DIR"] = str(tmp_path / "app-data")

    result = subprocess.run(
        [sys.executable, str(root / "src" / "main.py"), "--self-check"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[self-check] OK app_data_writable" in output
    assert "[self-check] OK certifi_ca_bundle" in output
    assert "[self-check] OK database_init" in output
    assert "[self-check] OK main_window_construct" in output
    assert (tmp_path / "app-data").exists()



def test_main_help_returns_without_starting_gui(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["WORKFLOW_APP_DATA_DIR"] = str(tmp_path / "app-data")

    result = subprocess.run(
        [sys.executable, str(root / "src" / "main.py"), "--help"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "--self-check" in output
    assert "--smoke" in output
    assert "usage:" in output.lower()
    assert not (tmp_path / "app-data").exists()
