# -*- coding: utf-8 -*-
"""Release metadata consistency tests."""

import ast
import re
from pathlib import Path


def _literal_assignment(path: Path, name: str) -> str:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if getattr(target, "id", None) == name:
                value = ast.literal_eval(node.value)
                assert isinstance(value, str)
                return value
    raise AssertionError(f"{name} not found in {path}")


def test_project_version_metadata_uses_config_as_single_source():
    root = Path(__file__).resolve().parent.parent
    app_version = _literal_assignment(root / "src" / "config.py", "APP_VERSION")
    package_version = _literal_assignment(root / "src" / "__init__.py", "__version__")
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert package_version == app_version
    assert f"当前发布版本：{app_version}" in readme
    assert "dist/工作流管理_<APP_VERSION>_slim2.exe" in readme

    for spec_name in ["build_slim.spec", "build_slim2.spec", "build_macos_intel.spec"]:
        spec = (root / spec_name).read_text(encoding="utf-8")
        assert "<APP_VERSION>" in spec
        assert not re.search(r"工作流管理_\d+\.\d+\.\d+", spec)


def test_gitignore_keeps_dist_artifacts_untracked():
    root = Path(__file__).resolve().parent.parent
    content = (root / ".gitignore").read_text(encoding="utf-8")

    assert "dist/" in content
    assert "!dist/*.exe" not in content
