# -*- coding: utf-8 -*-
"""打包 spec 的运行期临时目录守卫测试。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS_SPECS = ("build.spec", "build_slim.spec", "build_slim2.spec")
EXPECTED_LITERAL = r'runtime_tmpdir=r"%LOCALAPPDATA%\工作流管理\pyi-tmp"'


def test_windows_specs_keep_runtime_tmpdir_build_host_independent():
    """runtime_tmpdir 必须留到运行期展开 %LOCALAPPDATA%。

    在 spec 里用 os.environ 构建期求值，会把 CI 构建机的用户目录
    （C:\\Users\\runneradmin\\...）写死进单文件 exe；终端用户机器没有该目录，
    启动即报 "LOADER: failed to create runtime-tmpdir path ... CreateDirectory:
    系统找不到指定的路径"。
    """
    for spec_name in WINDOWS_SPECS:
        content = (ROOT / spec_name).read_text(encoding="utf-8")
        assert EXPECTED_LITERAL in content, spec_name
        assert 'os.environ.get("LOCALAPPDATA"' not in content, spec_name
        assert "str(Path.home())" not in content, spec_name
