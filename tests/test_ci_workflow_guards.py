from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUALITY_GUARDS = [
    "python tools/check_test_env.py",
    "python tools/check_requirements_consistency.py",
    "python tools/audit_risky_calls.py",
    "python tools/audit_broad_except.py",
    "python tools/module_hotspot_report.py --top 30 --baseline quality/module_hotspot_baseline.json --fail-on-regression",
    "python tools/run_tests.py --collect-only",
]
DOC_GUARD_TEST = "python -m pytest tests/test_docs_guardrails.py tests/test_ci_workflow_guards.py -q"


def _read_workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_quality_baselines_exist_for_ci_fresh_checkout():
    hotspot = ROOT / "quality" / "module_hotspot_baseline.json"
    broad_except = ROOT / "quality" / "broad_except_baseline.json"
    assert hotspot.is_file()
    assert broad_except.is_file()
    assert '"src/ui/main_window.py"' in hotspot.read_text(encoding="utf-8")
    assert '"src/ui/main_window.py"' in broad_except.read_text(encoding="utf-8")


def test_ci_workflow_runs_quality_guards_before_tests():
    text = _read_workflow("ci.yml")
    for first, second in zip(QUALITY_GUARDS, QUALITY_GUARDS[1:]):
        assert first in text
        assert second in text
        assert text.index(first) < text.index(second)
    assert text.index(QUALITY_GUARDS[-1]) < text.index("pytest -q")
    assert "QT_QPA_PLATFORM: offscreen" in text


def test_package_workflow_runs_quality_guards_before_build_and_upload():
    text = _read_workflow("package.yml")
    for first, second in zip(QUALITY_GUARDS, QUALITY_GUARDS[1:]):
        assert first in text
        assert second in text
        assert text.index(first) < text.index(second)
    assert "pip install -r requirements-ci.txt" in text
    assert DOC_GUARD_TEST in text
    assert text.index(DOC_GUARD_TEST) < text.index("pyinstaller")
    assert text.index(QUALITY_GUARDS[-1]) < text.index("pyinstaller")
    assert text.index("Verify artifact") < text.index("Upload artifact")
    assert "if-no-files-found: error" in text
    assert "${{ steps.verify_artifact.outputs.artifact_path }}" in text
    assert "${{ steps.verify_artifact.outputs.hash_path }}" in text


def test_macos_package_job_runs_full_pytest_before_build():
    text = _read_workflow("package.yml")
    macos_job = text[text.index("package-macos-intel:"):]

    assert "pip install -r requirements-ci.txt" in macos_job
    assert "python -m pytest -q" in macos_job
    assert macos_job.index("python -m pytest -q") < macos_job.index("pyinstaller build_macos_intel.spec")