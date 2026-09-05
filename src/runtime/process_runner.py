# -*- coding: utf-8 -*-
"""Centralized subprocess boundary for Workflow runtime code.

The goal is not to hide subprocess semantics; it is to keep all direct process
creation policy in one reviewed module so executors do not grow ad-hoc risky
call sites over time.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ProcessRunResult:
    """Serializable subset of ``subprocess.CompletedProcess`` used by callers."""

    args: Sequence[str]
    returncode: int
    stdout: str | bytes | None = None
    stderr: str | bytes | None = None


def _normalize_args(args: Sequence[str]) -> list[str]:
    """Return a defensive argument-list copy for subprocess calls.

    Runtime process creation must stay on explicit argv lists.  Accepting a raw
    string command makes Windows quoting and accidental shell-style expansion too
    easy to reintroduce, even when ``shell`` is false.
    """

    if isinstance(args, (str, bytes)):
        raise TypeError("process args must be an explicit sequence, not a command string")
    normalized = [str(arg) for arg in args]
    if not normalized:
        raise ValueError("process args must not be empty")
    return normalized


def _validate_kwargs(kwargs: Mapping[str, Any]) -> None:
    """Enforce shared subprocess policy at the single reviewed boundary."""

    shell = kwargs.get("shell")
    if shell:
        raise ValueError("shell=True is forbidden for Workflow runtime processes")


def build_subprocess_kwargs(
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    creationflags: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build common subprocess kwargs while preserving explicit caller choices."""

    built: dict[str, Any] = dict(kwargs)
    _validate_kwargs(built)
    if cwd is not None:
        built["cwd"] = str(cwd)
    if env is not None:
        built["env"] = dict(env)
    if creationflags:
        built["creationflags"] = creationflags
    # F-05: POSIX 子进程放入独立会话/进程组，取消时 kill_process_tree 可对整组
    # 发信号（os.killpg）；Windows 用 taskkill /T 已覆盖，start_new_session 参数
    # 在 win32 上不可用，故按平台注入。调用方显式传值时不覆盖。
    import sys
    if sys.platform != "win32":
        built.setdefault("start_new_session", True)
    built.setdefault("stdin", subprocess.DEVNULL)
    return built


def run_process(args: Sequence[str], **kwargs: Any) -> ProcessRunResult:
    """Run a child process through the reviewed runtime boundary."""

    _validate_kwargs(kwargs)
    completed = subprocess.run(_normalize_args(args), **kwargs)
    return ProcessRunResult(
        args=list(completed.args) if isinstance(completed.args, (list, tuple)) else [str(completed.args)],
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def start_process(args: Sequence[str], **kwargs: Any) -> subprocess.Popen:
    """Start a child process through the reviewed runtime boundary."""

    _validate_kwargs(kwargs)
    return subprocess.Popen(_normalize_args(args), **kwargs)
