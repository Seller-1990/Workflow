# -*- coding: utf-8 -*-
"""dry-run 预览文本生成。"""

from __future__ import annotations

from typing import Dict, List, Optional

from engine_core.stages import normalize_stage_uid

SEPARATOR_LINE = "═" * 40


def describe_batch_mode(group: list[object]) -> str:
    if len(group) > 1:
        return "并行"
    if group and getattr(group[0], "is_gate", False):
        return "检查点"
    return "串行"


def build_stage_group_map(
    *,
    batches: list[list[object]],
    stage_meta: Dict[object, dict],
    ordered_stage_uids: List[object],
    unassigned_uid: Optional[str],
) -> Dict[object, list[list[object]]]:
    groups_by_stage: Dict[object, list[list[object]]] = {
        uid: [] for uid in ordered_stage_uids
    }
    for group in batches:
        raw_uid = getattr(group[0], "stage_uid", None) if group else None
        uid = normalize_stage_uid(raw_uid, stage_meta, ordered_stage_uids, unassigned_uid)
        groups_by_stage.setdefault(uid, []).append(group)
    return groups_by_stage


def format_dry_run_lines(
    *,
    batches: list[list[object]],
    stage_meta: Dict[object, dict],
    ordered_stage_uids: List[object],
    unassigned_uid: Optional[str],
) -> list[str]:
    stage_uid_to_groups = build_stage_group_map(
        batches=batches,
        stage_meta=stage_meta,
        ordered_stage_uids=ordered_stage_uids,
        unassigned_uid=unassigned_uid,
    )

    lines = [SEPARATOR_LINE, "[预演] 按阶段执行预览："]
    shown_stages = 0

    for uid in ordered_stage_uids:
        meta = stage_meta.get(uid)
        if not meta or meta["step_count"] <= 0:
            continue
        groups = stage_uid_to_groups.get(uid, [])
        if not groups:
            continue

        shown_stages += 1
        lines.append(f"阶段 S{meta['index']} {meta['name']} · {meta['step_count']}步")

        if len(groups) == 1:
            group = groups[0]
            names = ", ".join(step.name for step in group)
            lines.append(f"  {describe_batch_mode(group)}：{names}")
        else:
            total = len(groups)
            for index, group in enumerate(groups, 1):
                names = ", ".join(step.name for step in group)
                lines.append(f"执行组 {index}/{total}（{describe_batch_mode(group)}）：{names}")

    lines.append(
        f"共 {shown_stages} 个阶段，{len(batches)} 个执行组，{sum(len(b) for b in batches)} 个步骤"
    )
    lines.append(SEPARATOR_LINE)
    return lines
