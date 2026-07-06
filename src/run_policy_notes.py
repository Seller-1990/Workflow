# -*- coding: utf-8 -*-
"""Shared user-facing notes for executor policy risk metadata."""

from __future__ import annotations

from typing import Mapping, Any


MANUAL_REQUIRED_NOTE = "需要人工确认"
BACKGROUND_RISK_NOTE = "可能仍有后台任务运行"
ORPHAN_RISK_NOTE = "子工作流可能仍在后台运行"
POLICY_NOTE_PREFIX = "执行诊断"


def build_policy_risk_note(extra: Mapping[str, Any] | None) -> str:
    """Build a stable Chinese diagnostic note from ExecutorResult.extra."""
    if not extra:
        return ""
    notes: list[str] = []
    if extra.get("manual_required"):
        notes.append(MANUAL_REQUIRED_NOTE)
    if extra.get("background_risk"):
        notes.append(BACKGROUND_RISK_NOTE)
    if extra.get("orphan_risk"):
        notes.append(ORPHAN_RISK_NOTE)
    return "；".join(notes)


def append_policy_risk_note(message: str | None, extra: Mapping[str, Any] | None) -> str | None:
    """Append policy diagnostics without duplicating notes on repeated handling."""
    note = build_policy_risk_note(extra)
    if not note:
        return message
    base = (message or "").strip()
    suffix = f"{POLICY_NOTE_PREFIX}: {note}"
    if suffix in base:
        return base
    return f"{base}\n{suffix}" if base else suffix


def count_policy_risk_notes(message: str | None) -> dict[str, int]:
    """Return count increments for diagnostics stored in StepLog.error_message."""
    text = message or ""
    return {
        "manual_required": int(MANUAL_REQUIRED_NOTE in text),
        "background_risk": int(BACKGROUND_RISK_NOTE in text),
        "orphan_risk": int(ORPHAN_RISK_NOTE in text),
    }
