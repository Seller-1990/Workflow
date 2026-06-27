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
    token = "realToken" + "123456"
    export_file.write_text(
        f'{{"webhook_url": "https://oapi.dingtalk.com/robot/send?access_token={token}"}}',
        encoding="utf-8",
    )

    issues = hygiene.find_secret_matches([export_file], tmp_path)

    assert len(issues) == 1
    assert issues[0].kind == "secret-residue"
    assert issues[0].line_number == 1


def test_find_secret_matches_allows_redacted_and_test_fake_tokens(tmp_path):
    hygiene = _load_repo_hygiene()
    export_file = tmp_path / "workflows_export.json"
    export_file.write_text(
        "\n".join(
            [
                "access_token=<redacted>",
                "access_token=local-token",
                "https://oapi.dingtalk.com/robot/send?access_token=contract-token",
                "https://oapi.dingtalk.com/robot/send?access_token=integration-secret-token",
            ]
        ),
        encoding="utf-8",
    )

    assert hygiene.find_secret_matches([export_file], tmp_path) == []


def test_find_secret_matches_scans_tests_directory_for_unallowlisted_tokens(tmp_path):
    hygiene = _load_repo_hygiene()
    export_file = tmp_path / "tests" / "fixture.json"
    export_file.parent.mkdir(parents=True)
    token = "realToken" + "123456"
    export_file.write_text(f"access_token={token}", encoding="utf-8")

    issues = hygiene.find_secret_matches([export_file], tmp_path)

    assert len(issues) == 1
    assert issues[0].kind == "secret-residue"
    assert issues[0].path == export_file


def test_list_local_residue_paths_collects_ignored_runtime_outputs(tmp_path):
    hygiene = _load_repo_hygiene()
    (tmp_path / "dist").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "src" / "__pycache__").mkdir(parents=True)
    (tmp_path / ".pytest_cache").mkdir()
    for filename in ("audit_export.json", "tmp_export.json", "workflows_export.local.json"):
        (tmp_path / filename).write_text("{}", encoding="utf-8")

    residues = hygiene.list_local_residue_paths(tmp_path)
    residue_labels = [path.relative_to(tmp_path).as_posix() for path in residues]

    assert residue_labels == [
        ".pytest_cache",
        "audit_export.json",
        "data",
        "dist",
        "logs",
        "src/__pycache__",
        "tmp_export.json",
        "workflows_export.local.json",
    ]


def test_find_local_residue_reports_strict_mode_failures(tmp_path):
    hygiene = _load_repo_hygiene()
    residue_path = tmp_path / "dist"
    residue_path.mkdir()

    issues = hygiene.find_local_residue([residue_path], tmp_path)

    assert len(issues) == 1
    assert issues[0].kind == "local-residue"
    assert issues[0].message.endswith("dist")


def test_run_checks_skips_local_residue_without_strict(tmp_path):
    hygiene = _load_repo_hygiene()
    (tmp_path / "dist").mkdir()
    (tmp_path / "data").mkdir()

    issues = hygiene.run_checks(tmp_path, strict=False, tracked_paths=[])

    assert issues == []


def test_run_checks_includes_local_residue_in_strict_mode(tmp_path):
    hygiene = _load_repo_hygiene()
    (tmp_path / "build").mkdir()
    (tmp_path / "dist").mkdir()
    for filename in ("audit_export.json", "tmp_export.json", "workflows_export.json"):
        (tmp_path / filename).write_text("access_token=<redacted>", encoding="utf-8")

    issues = hygiene.run_checks(tmp_path, strict=True, tracked_paths=[])

    assert [(issue.kind, issue.path.relative_to(tmp_path).as_posix()) for issue in issues] == [
        ("local-residue", "audit_export.json"),
        ("local-residue", "build"),
        ("local-residue", "dist"),
        ("local-residue", "tmp_export.json"),
        ("local-residue", "workflows_export.json"),
    ]


def test_ci_runs_strict_hygiene_before_compileall():
    ci_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
    content = ci_path.read_text(encoding="utf-8")

    hygiene_index = content.index("python tools\\repo_hygiene.py --strict")
    compile_index = content.index("python -m compileall src tests _import_and_run.py")

    assert hygiene_index < compile_index


def test_package_workflow_runs_strict_hygiene_before_compileall():
    package_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "package.yml"
    content = package_path.read_text(encoding="utf-8")

    hygiene_index = content.index("python tools\\repo_hygiene.py --strict")
    metadata_index = content.index("id: build_meta")
    compile_index = content.index("python -m compileall src tests _import_and_run.py")
    release_gate_index = content.index("git status --porcelain --untracked-files=all")
    build_index = content.index("pyinstaller ${{ steps.build_meta.outputs.spec_path }} --noconfirm")

    assert hygiene_index < metadata_index < compile_index < release_gate_index < build_index


def test_package_workflow_supports_manual_and_tag_releases():
    package_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "package.yml"
    content = package_path.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in content
    assert "push:" in content
    assert '      - "v*"' in content


def test_package_workflow_self_check_has_timeout_and_kill_guard():
    package_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "package.yml"
    content = package_path.read_text(encoding="utf-8")

    assert "Start-Process" in content
    assert "--self-check" in content
    assert "WORKFLOW_APP_DATA_DIR" in content
    assert "WaitForExit(60000)" in content
    assert "Stop-Process" in content


def test_package_workflow_uploads_the_same_artifact_it_self_checks():
    package_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "package.yml"
    content = package_path.read_text(encoding="utf-8")

    assert 'DEFAULT_SPEC: build_slim2.spec' in content
    assert '$specPath = "${{ github.event.inputs.spec }}"' in content
    assert '$specPath = "${{ env.DEFAULT_SPEC }}"' in content
    assert 'config_path = Path("src/config.py")' in content
    assert 'ast.parse(config_path.read_text(encoding="utf-8"), filename=str(config_path))' in content
    assert 'if getattr(target, "id", None) == "APP_VERSION":' in content
    assert "id: verify_artifact" in content
    assert '"artifact_path=$($exe.FullName)" >> $env:GITHUB_OUTPUT' in content
    assert '"artifact_name=workflow-manager-$appVersion-$specName-$shortSha" >> $env:GITHUB_OUTPUT' in content
    assert '"artifact_name=${{ steps.build_meta.outputs.artifact_name }}" >> $env:GITHUB_OUTPUT' in content
    assert '"hash_path=$hashPath" >> $env:GITHUB_OUTPUT' in content
    assert "name: ${{ steps.verify_artifact.outputs.artifact_name }}" in content
    assert "path: |\n            ${{ steps.verify_artifact.outputs.artifact_path }}" in content
    assert "${{ steps.verify_artifact.outputs.hash_path }}" in content


def test_readme_package_section_matches_self_check_workflow():
    root = Path(__file__).resolve().parent.parent
    readme = (root / "README.md").read_text(encoding="utf-8")
    package_workflow = (root / ".github" / "workflows" / "package.yml").read_text(encoding="utf-8")

    assert "--self-check" in package_workflow
    assert "--self-check" in readme
    assert "--smoke" not in readme
    assert ".sha256" in package_workflow
    assert ".sha256" in readme
    assert "WORKFLOW_APP_DATA_DIR" in readme
    assert "workflow_dispatch" in readme
    assert "v*" in readme
    assert "git status --porcelain --untracked-files=all" in readme
    assert "workflow-manager-<APP_VERSION>-<specName>-<shortSha>" in readme
    assert "src/config.py" in readme
    assert "回滚" in readme


def test_gitattributes_normalizes_text_and_protects_binary_artifacts():
    attrs_path = Path(__file__).resolve().parent.parent / ".gitattributes"
    content = attrs_path.read_text(encoding="utf-8")

    assert "* text=auto" in content
    for pattern in ["*.py text eol=lf", "*.md text eol=lf", "*.yml text eol=lf", "*.json text eol=lf"]:
        assert pattern in content
    for pattern in ["*.png binary", "*.ico binary", "*.db binary", "*.sqlite binary", "*.exe binary"]:
        assert pattern in content
