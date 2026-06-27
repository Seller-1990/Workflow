#!/usr/bin/env python
"""启用/停用仓库本地 git 质量门钩子。

通过 ``git config core.hooksPath .githooks`` 将钩子目录指向受版本控制的
``.githooks/``，使 ``pre-commit``（快速门）与 ``pre-push``（完整门）对本地
提交/推送强制生效。脚本幂等，可重复执行；只修改目标仓库的本地配置，
不触碰全局 git 配置。``--uninstall`` 恢复默认钩子目录。
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

HOOKS_PATH = ".githooks"
HOOK_FILES = ("pre-commit", "pre-push")


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # 仅以参数列表方式调用 git，禁止 shell=True（见 tools/audit_risky_calls.py）。
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def read_hooks_path(repo: Path) -> str | None:
    # 未设置时 git config 返回非零退出码。
    result = run_git(repo, "config", "core.hooksPath")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def install(repo: Path) -> int:
    hooks_dir = repo / HOOKS_PATH
    if not hooks_dir.is_dir():
        print(f"Hook directory missing: {hooks_dir}")
        return 1
    missing = [name for name in HOOK_FILES if not (hooks_dir / name).is_file()]
    if missing:
        print(f"Hook files missing in {hooks_dir}: {', '.join(missing)}")
        return 1

    previous = read_hooks_path(repo)
    result = run_git(repo, "config", "core.hooksPath", HOOKS_PATH)
    if result.returncode != 0:
        print(f"git config failed: {result.stderr.strip()}")
        return 1
    current = read_hooks_path(repo)
    if current != HOOKS_PATH:
        print(f"Verification failed: core.hooksPath={current!r}, expected {HOOKS_PATH!r}")
        return 1

    if previous == HOOKS_PATH:
        print(f"Already installed: core.hooksPath={HOOKS_PATH} (repo: {repo})")
    elif previous:
        print(f"Installed: core.hooksPath changed from {previous!r} to {HOOKS_PATH!r} (repo: {repo})")
    else:
        print(f"Installed: core.hooksPath={HOOKS_PATH} (repo: {repo})")
    print("pre-commit: audit_broad_except + audit_risky_calls + module_hotspot_report --fail-on-regression + compileall")
    print("pre-push:   all pre-commit gates + pytest -q")
    return 0


def uninstall(repo: Path) -> int:
    previous = read_hooks_path(repo)
    if previous is None:
        print(f"Already uninstalled: core.hooksPath not set (repo: {repo})")
        return 0
    result = run_git(repo, "config", "--unset", "core.hooksPath")
    if result.returncode != 0:
        print(f"git config --unset failed: {result.stderr.strip()}")
        return 1
    if read_hooks_path(repo) is not None:
        print("Verification failed: core.hooksPath is still set")
        return 1
    print(f"Uninstalled: core.hooksPath {previous!r} removed (repo: {repo})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enable or disable the repository-local git quality-gate hooks (core.hooksPath=.githooks)."
    )
    parser.add_argument("--repo", type=Path, default=Path("."), help="Target git repository root (default: current directory).")
    parser.add_argument("--uninstall", action="store_true", help="Unset core.hooksPath instead of installing.")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    # 必须是仓库根目录（普通仓库为 .git 目录，worktree 为 .git 文件），
    # 防止误把配置写到上层仓库。
    if not (repo / ".git").exists():
        print(f"Not a git repository root: {repo}")
        return 2
    return uninstall(repo) if args.uninstall else install(repo)


if __name__ == "__main__":
    raise SystemExit(main())
