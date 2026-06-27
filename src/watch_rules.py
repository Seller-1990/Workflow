# -*- coding: utf-8 -*-
"""文件监听规则与旧配置自修复。

输出目录判定优先级（ROI-2 / H3 根因修复，声明优先模型）：

1. 显式声明：步骤通过 ``get_output_paths()`` 声明的输出目录/文件，是首选依据；
2. ``--out`` 参数推断：从步骤参数解析 ``--out <path>`` / ``--out=<path>``（未声明步骤的安全网）；
3. 原地写回类型推断：Excel/PowerBI 刷新步骤会原地保存 ``script_path`` 指向的文件，
   其父目录视为输出目录（未声明步骤的安全网）。

历史上 ``collect_workflow_output_roots`` 还内置了「月度数据处理」工作流的业务硬编码
（按脚本名后缀推断 基础文件 目录）。该硬编码已从通用推断路径移除，仅保留在
``_legacy_monthly_output_roots`` 中作为存量数据库的兜底：

- ``detect_watch_output_conflicts`` 默认叠加该兜底（include_legacy_monthly=True），
  因为现存用户库中的月度步骤尚未显式声明输出（详见函数 docstring）；
- ``sanitize_workflow_watch_config``（启动期旧配置修复路径）必须保持该兜底开启，
  并继续通过 ``suggest_watch_folders`` 给出修复建议（这是修复提示，不是运行期推断）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


MONTHLY_WORKFLOW_NAME = "月度数据处理"
MONTHLY_REFRESH_SCRIPT_SUFFIX = "/00_月度接收__月度基础数据刷新.py"
# 这些步骤类型会原地刷新并保存 script_path 指向的文件，其所在目录视为输出目录
IN_PLACE_OUTPUT_STEP_TYPES = frozenset({"excel_powerquery", "powerbi_refresh"})


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


def _declared_output_roots(step: object) -> set[Path]:
    """读取步骤显式声明的输出路径（ROI-2 首选依据）。

    步骤模型契约：``get_output_paths()`` 返回字符串列表且不抛异常
    （JSON 解析失败时在模型层降级为空列表）。空白项跳过，避免空字符串
    被 resolve 成当前工作目录造成误判。
    """
    roots: set[Path] = set()
    output_getter = getattr(step, "get_output_paths", None)
    if not callable(output_getter):
        return roots
    for raw in output_getter() or []:
        text = str(raw).strip()
        if not text:
            continue
        declared_path = _normalize_path(text)
        if declared_path is not None:
            roots.add(declared_path)
    return roots


def collect_workflow_output_roots(steps: Iterable[object]) -> list[Path]:
    """收集当前工作流的输出根目录（显式声明优先，通用推断兜底）。

    优先级：显式声明（get_output_paths） > ``--out`` 参数推断 > 原地写回类型推断。

    注意：本函数不再包含「月度数据处理」业务硬编码；存量数据库的月度兜底
    见 ``_legacy_monthly_output_roots`` 与 ``detect_watch_output_conflicts``。
    """
    output_roots: set[Path] = set()
    for step in steps:
        # 1) 显式声明：声明过的输出目录/文件直接采信
        output_roots.update(_declared_output_roots(step))

        # 2) --out 参数推断（未声明步骤的安全网）
        args = []
        args_getter = getattr(step, "get_args", None)
        if callable(args_getter):
            try:
                args = list(args_getter() or [])
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

        # 3) 原地写回类型推断（未声明步骤的安全网）
        script_path = (getattr(step, "script_path", None) or "").replace("\\", "/")
        step_type = getattr(step, "step_type", None)
        if step_type in IN_PLACE_OUTPUT_STEP_TYPES and script_path.strip():
            # Excel/PowerBI 刷新步骤会原地保存目标文件，父目录即输出目录，
            # 监听该目录会形成 监听→运行→保存→再监听 的死循环
            script_resolved = _normalize_path(script_path)
            if script_resolved is not None:
                output_roots.add(script_resolved.parent)
    return sorted(output_roots)


def _legacy_monthly_output_roots(steps: Iterable[object]) -> set[Path]:
    """旧版「月度数据处理」基础文件目录的业务硬编码推断（仅作存量库兜底）。

    历史背景（5f90c3a 防护）：旧库中的月度刷新脚本没有显式输出声明，只能按
    脚本名后缀推断 ``<工作流根>/基础文件`` 为输出目录。声明模型落地后，新配置
    应在步骤上显式声明输出目录；本推断已从通用路径 ``collect_workflow_output_roots``
    移除，仅由 ``detect_watch_output_conflicts``（默认开启的兜底开关）与启动期
    ``sanitize_workflow_watch_config`` 修复路径使用。
    """
    roots: set[Path] = set()
    for step in steps:
        script_path = (getattr(step, "script_path", None) or "").replace("\\", "/")
        if not script_path.endswith(MONTHLY_REFRESH_SCRIPT_SUFFIX):
            continue
        script_resolved = _normalize_path(script_path)
        workflow_root = _get_monthly_workflow_root(script_resolved)
        if workflow_root is not None:
            roots.add(workflow_root / "基础文件")
    return roots


def detect_watch_output_conflicts(
    watch_folders: list[str],
    steps: Iterable[object],
    *,
    include_legacy_monthly: bool = True,
) -> list[str]:
    """检测监听目录是否与当前工作流输出目录重叠。

    输出目录来源 = ``collect_workflow_output_roots``（显式声明 > ``--out`` 推断 >
    原地写回类型推断）。

    Args:
        include_legacy_monthly: 是否叠加 ``_legacy_monthly_output_roots`` 的
            旧版月度业务兜底。默认开启：现存用户库中的月度工作流步骤尚未
            显式声明输出，运行期入口（engine.start_watch、工作流配置保存防呆）
            仍依赖该兜底拦截 监听→运行→写回 死循环；待月度步骤补齐显式声明后
            可改传 False 收紧为「声明 + 通用推断」纯净路径。
            ``sanitize_workflow_watch_config`` 的旧配置修复路径必须保持 True。
    """
    output_roots: set[Path] = set(collect_workflow_output_roots(steps))
    if include_legacy_monthly:
        output_roots.update(_legacy_monthly_output_roots(steps))
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
    """为已知工作流返回推荐监听目录（仅用于旧配置修复建议，不参与运行期推断）。"""
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
    """修正旧监听配置，返回 (是否变更, 新目录, 是否启用监听)。

    本函数是「存量库修复」路径（init_db 启动期调用）：冲突检测必须叠加旧版
    月度业务兜底（include_legacy_monthly=True），保证在步骤尚未显式声明输出
    的旧数据库上仍能识别 基础文件 重叠并改写/停用监听（保持 5f90c3a 防护）。
    ``suggest_watch_folders`` 提供的推荐目录同样只是修复建议，不是运行期推断。
    """
    current_folders = list(watch_folders or [])
    if not watch_enabled:
        return False, current_folders, False

    conflicts = detect_watch_output_conflicts(current_folders, steps, include_legacy_monthly=True)
    if not conflicts:
        return False, current_folders, True

    suggested = suggest_watch_folders(workflow_name, steps)
    if suggested:
        return True, suggested, True
    return True, [], False
