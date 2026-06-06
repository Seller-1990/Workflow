# -*- coding: utf-8 -*-
"""Repository hygiene check tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_repo_hygiene():
    module_path = Path(__file__).resolve().parent.parent / "tools" / "repo_hygiene.py"
    spec = importlib.util.spec_from_file_location("repo_hygiene", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_find_tracked_artifacts_flags_generated_outputs(tmp_path):
    hygiene = _load_repo_hygiene()
    paths = [
        tmp_path / "dist" / "app.exe",
        tmp_path / "build" / "cache.txt",
        tmp_path / "src" / "main.py",
    ]

    issues = hygiene.find_tracked_artifacts(paths, tmp_path)

    assert [issue.kind for issue in issues] == ["tracked-artifact", "tracked-artifact"]
    assert "dist/app.exe" in issues[0].message
    assert "build/cache.txt" in issues[1].message


def test_find_secret_matches_flags_real_access_token(tmp_path):
    hygiene = _load_repo_hygiene()
    export_file = tmp_path / "workflows_export.json"
    export_file.write_text(
        '{"webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=abcDEF123456"}',
        encoding="utf-8",
    )

    issues = hygiene.find_secret_matches([export_file], tmp_path)

    assert len(issues) == 1
    assert issues[0].kind == "secret-residue"
    assert issues[0].line_number == 1


def test_find_secret_matches_allows_redacted_and_test_fake_tokens(tmp_path):
    hygiene = _load_repo_hygiene()
    export_file = tmp_path / "workflows_export.json"
    export_file.write_text("access_token=<redacted>\naccess_token=local-token", encoding="utf-8")

    assert hygiene.find_secret_matches([export_file], tmp_path) == []
