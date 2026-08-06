# -*- coding: utf-8 -*-
"""批处理执行器测试"""

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from executors.bat_executor import BatExecutor


@pytest.fixture
def executor():
    return BatExecutor()


def test_bat_executor_rejects_nonexistent_script(executor, tmp_path):
    result = executor.execute(str(tmp_path / "no_such.bat"))
    assert not result.success
    assert "不存在" in result.error_message


def test_bat_executor_rejects_non_bat_extension(executor, tmp_path):
    txt_file = tmp_path / "script.txt"
    txt_file.write_text("echo hi")
    result = executor.execute(str(txt_file))
    assert not result.success
    assert "不支持" in result.error_message


def test_bat_executor_rejects_null_byte_args(executor, tmp_path):
    bat = tmp_path / "test.bat"
    bat.write_text("@echo off\necho hello")
    result = executor.execute(str(bat), args=["good", "bad\x00arg"])
    assert not result.success
    assert "空字符" in result.error_message


def test_bat_executor_rejects_missing_cwd(executor, tmp_path):
    bat = tmp_path / "test.bat"
    bat.write_text("@echo off\necho hi")
    result = executor.execute(str(bat), cwd=str(tmp_path / "nope"))
    assert not result.success
    assert "工作目录不存在" in result.error_message


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_bat_executor_runs_simple_script(executor, tmp_path):
    bat = tmp_path / "hello.bat"
    bat.write_text("@echo off\necho HELLO_BAT")
    result = executor.execute(str(bat), log_dir=tmp_path / "logs")
    assert result.success
    assert result.exit_code == 0
    assert result.stdout_path is not None
    content = Path(result.stdout_path).read_text(encoding="utf-8-sig", errors="replace")
    assert "HELLO_BAT" in content


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_bat_executor_captures_args(executor, tmp_path):
    bat = tmp_path / "args.bat"
    bat.write_text("@echo off\necho %1 %2")
    result = executor.execute(str(bat), args=["foo", "bar"], log_dir=tmp_path / "logs")
    assert result.success
    content = Path(result.stdout_path).read_text(encoding="utf-8-sig", errors="replace")
    assert "foo" in content and "bar" in content


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_bat_executor_nonzero_exit_code(executor, tmp_path):
    bat = tmp_path / "fail.bat"
    bat.write_text("@echo off\nexit /b 42")
    result = executor.execute(str(bat), log_dir=tmp_path / "logs")
    assert not result.success
    assert result.exit_code == 42


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_bat_executor_cancel(executor, tmp_path):
    bat = tmp_path / "slow.bat"
    bat.write_text("@echo off\nping -n 30 127.0.0.1 >nul")
    cancel = threading.Event()
    cancel.set()
    result = executor.execute(str(bat), cancel_event=cancel, log_dir=tmp_path / "logs")
    assert not result.success
    assert "取消" in (result.error_message or "")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_bat_executor_timeout(executor, tmp_path):
    bat = tmp_path / "slow.bat"
    bat.write_text("@echo off\nping -n 30 127.0.0.1 >nul")
    result = executor.execute(str(bat), timeout=1, log_dir=tmp_path / "logs")
    assert not result.success
    assert "超时" in (result.error_message or "")
