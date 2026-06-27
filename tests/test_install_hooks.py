# -*- coding: utf-8 -*-
"""`.githooks/` 钩子脚本与 `tools/install_hooks.py` 安装器的回归测试。

安装器测试只在一次性临时 git 仓库中执行，绝不修改真实仓库的 git 配置。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tools.install_hooks as install_hooks

ROOT = Path(__file__).resolve().parents[1]
HOOK_NAMES = ("pre-commit", "pre-push")
GATE_SCRIPTS = ("audit_broad_except.py", "audit_risky_calls.py", "module_hotspot_report.py")


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _make_temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _run_git(repo, "init", "--quiet").returncode == 0
    hooks_dir = repo / ".githooks"
    hooks_dir.mkdir()
    for name in HOOK_NAMES:
        # 按字节复制，避免文本模式写入在 Windows 上改写行尾。
        (hooks_dir / name).write_bytes((ROOT / ".githooks" / name).read_bytes())
    return repo


def test_hook_scripts_exist_and_use_sh_shebang():
    for name in HOOK_NAMES:
        raw = (ROOT / ".githooks" / name).read_bytes()
        assert raw, f".githooks/{name} must not be empty"
        assert raw.startswith(b"#!/bin/sh"), f".githooks/{name} must start with #!/bin/sh"


def test_pre_commit_runs_fast_gates_without_pytest():
    text = (ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    for script in GATE_SCRIPTS:
        assert script in text
    assert "compileall" in text
    assert "--fail-on-regression" in text
    assert "pytest" not in text  # 快速门不运行测试套件
    assert "--no-verify" in text  # 失败提示必须说明跳过方式


def test_pre_push_runs_full_gates_including_pytest():
    text = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    for script in GATE_SCRIPTS:
        assert script in text
    assert "compileall" in text
    assert "pytest" in text
    assert "--no-verify" in text


def test_install_hooks_cli_help():
    result = subprocess.run(
        [sys.executable, "tools/install_hooks.py", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0
    assert "--uninstall" in result.stdout
    assert "--repo" in result.stdout


def test_install_is_idempotent_and_verifies_in_temp_repo(tmp_path):
    repo = _make_temp_repo(tmp_path)

    # 重复安装两次：结果一致且均成功（幂等）。
    for _ in range(2):
        assert install_hooks.main(["--repo", str(repo)]) == 0
        config = _run_git(repo, "config", "core.hooksPath")
        assert config.returncode == 0
        assert config.stdout.strip() == ".githooks"


def test_uninstall_unsets_hooks_path_in_temp_repo(tmp_path):
    repo = _make_temp_repo(tmp_path)
    assert install_hooks.main(["--repo", str(repo)]) == 0

    assert install_hooks.main(["--repo", str(repo), "--uninstall"]) == 0
    config = _run_git(repo, "config", "core.hooksPath")
    assert config.returncode != 0  # 配置已移除

    # 再次卸载仍应成功（幂等）。
    assert install_hooks.main(["--repo", str(repo), "--uninstall"]) == 0


def test_install_fails_without_hooks_dir_and_writes_no_config(tmp_path):
    repo = tmp_path / "bare"
    repo.mkdir()
    assert _run_git(repo, "init", "--quiet").returncode == 0

    assert install_hooks.main(["--repo", str(repo)]) == 1
    config = _run_git(repo, "config", "core.hooksPath")
    assert config.returncode != 0  # 安装中止时不得遗留配置


def test_install_rejects_non_git_directory(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert install_hooks.main(["--repo", str(plain)]) == 2
