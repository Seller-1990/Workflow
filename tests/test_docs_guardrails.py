from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_development_guardrails_document_guard_commands():
    text = (ROOT / "docs/development_guardrails.md").read_text(encoding="utf-8")
    for phrase in ["audit_risky_calls.py", "audit_broad_except.py", "module_hotspot_report.py", "run_tests.py --collect-only"]:
        assert phrase in text


def test_development_guardrails_document_audit_cli_exit_contract():
    text = (ROOT / "docs/development_guardrails.md").read_text(encoding="utf-8")
    for phrase in [
        "带显式路径",
        "路径不存在",
        "目标不是 `.py` 文件",
        "`0`：扫描完成",
        "`1`：扫描完成",
        "`2`：调用方式/目标无效",
        "空扫描误通过",
    ]:
        assert phrase in text


def test_execution_security_checklist_mentions_allowlist_and_shell_true():
    text = (ROOT / "docs/execution_security_checklist.md").read_text(encoding="utf-8")
    assert "allowlist" in text.lower()
    assert "shell=True" in text
