# -*- coding: utf-8 -*-
"""文件监听规则与旧配置自修复。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


MONTHLY_WORKFLOW_NAME = "月度数据处理"
MONTHLY_REFRESH_SCRIPT_SUFFIX = "/00_月度接收__月度基础数据刷新.py"


def _normalize_path(raw_path: str) -> Path | None:
    try:
        return Path(raw_path).expanduser().resolve()
    except Exception:
        return None


def _extract_output_path(arg: str) -> Path | None:
    normalized = (arg or "").strip()
    if not normalized:
        return None
    prefix = "--out="
    if normalized.lower().startswith(prefix):
        return _normalize_path(normalized[len(prefix):])
    return None


def _get_monthly_workflow_root(script_resolved: Path | None) -> Path | None:
    if script_resolved is None:
        return None
    parents = script_resolved.parents
    if len(parents) <= 3:
        return None
    return parents[3]


def collect_workflow_output_roots(steps: Iterable[object]) -> list[Path]:
    """根据步骤脚本与参数推断当前工作流的输出根目录。"""
    output_roots: set[Path] = set()
    for step in steps:
        args = []
        getter = getattr(step, "get_args", None)
        if callable(getter):
            try:
                args = list(getter() or [])
            except Exception:
                args = []
        for index, arg in enumerate(args):
            if arg == "--out" and index + 1 < len(args):
                output_path = _normalize_path(args[index + 1])
                if output_path is not None:
                    output_roots.add(output_path)
                continue
            inline_output_path = _extract_output_path(arg)
            if inline_output_path is not None:
                output_roots.add(inline_output_path)

        script_path = (getattr(step, "script_path", None) or "").replace("\\", "/")
        if script_path.endswith(MONTHLY_REFRESH_SCRIPT_SUFFIX):
            script_resolved = _normalize_path(script_path)
            workflow_root = _get_monthly_workflow_root(script_resolved)
            if workflow_root is not None:
                output_roots.add(workflow_root / "基础文件")
    return sorted(output_roots)


def detect_watch_output_conflicts(watch_folders: list[str], steps: Iterable[object]) -> list[str]:
    """检测监听目录是否与当前工作流推断输出目录重叠。"""
    output_roots = collect_workflow_output_roots(steps)
    conflicts: list[str] = []
    for folder in watch_folders or []:
        watch_path = _normalize_path(folder)
        if watch_path is None:
            continue
        for output_root in output_roots:
            if (
                watch_path == output_root
                or output_root in watch_path.parents
                or watch_path in output_root.parents
            ):
                conflicts.append(str(watch_path))
                break
    return conflicts


def suggest_watch_folders(workflow_name: str, steps: Iterable[object]) -> list[str]:
    """为已知工作流返回推荐监听目录。"""
    if workflow_name != MONTHLY_WORKFLOW_NAME:
        return []

    for step in steps:
        script_path = (getattr(step, "script_path", None) or "").replace("\\", "/")
        if script_path.endswith(MONTHLY_REFRESH_SCRIPT_SUFFIX):
            script_resolved = _normalize_path(script_path)
            workflow_root = _get_monthly_workflow_root(script_resolved)
            if workflow_root is None:
                continue
            source_root = workflow_root / "月度接收" / "1账务信息"
            return [str(source_root)]
    return []


def sanitize_workflow_watch_config(
    workflow_name: str,
    watch_enabled: bool,
    watch_folders: list[str],
    steps: Iterable[object],
) -> tuple[bool, list[str], bool]:
    """修正旧监听配置，返回 (是否变更, 新目录, 是否启用监听)。"""
    current_folders = list(watch_folders or [])
    if not watch_enabled:
        return False, current_folders, False

    conflicts = detect_watch_output_conflicts(current_folders, steps)
    if not conflicts:
        return False, current_folders, True

    suggested = suggest_watch_folders(workflow_name, steps)
    if suggested:
        return True, suggested, True
    return True, [], False
