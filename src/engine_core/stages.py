# -*- coding: utf-8 -*-
"""阶段展示元数据的纯逻辑。"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

UNASSIGNED_STAGE_UID = "__unassigned__"
UNASSIGNED_STAGE_NAME = "未归类"


def build_stage_meta(
    *,
    steps: Iterable[object],
    stage_order_by_uid: Dict[str, int],
    stage_names_by_uid: Dict[object, str],
) -> tuple[Dict[object, dict], List[object], Optional[str]]:
    """构建阶段日志展示需要的元数据。"""
    step_list = list(steps)
    order_map = dict(stage_order_by_uid)
    stage_names = dict(stage_names_by_uid)

    ordered_uids: List[object] = [
        uid for uid, _ in sorted(order_map.items(), key=lambda kv: kv[1])
    ]
    max_order = max(order_map.values(), default=-1)

    has_unassigned_step = any(
        not getattr(step, "stage_uid", None)
        or getattr(step, "stage_uid", None) not in order_map
        for step in step_list
    )
    unassigned_uid = UNASSIGNED_STAGE_UID if has_unassigned_step else None

    if unassigned_uid:
        if unassigned_uid not in ordered_uids:
            ordered_uids.append(unassigned_uid)
        stage_names.setdefault(unassigned_uid, UNASSIGNED_STAGE_NAME)
        order_map[unassigned_uid] = max_order + 1

    step_count_by_uid: Dict[object, int] = {uid: 0 for uid in ordered_uids}
    for step in step_list:
        raw_uid = getattr(step, "stage_uid", None)
        uid = raw_uid if raw_uid in step_count_by_uid else (unassigned_uid or raw_uid)
        if uid in step_count_by_uid:
            step_count_by_uid[uid] += 1

    ordered_uids = [
        uid
        for uid, _ in sorted(
            {uid: order_map.get(uid, 10**9) for uid in ordered_uids}.items(),
            key=lambda kv: kv[1],
        )
    ]

    stage_meta: Dict[object, dict] = {}
    display_index = 0
    for uid in ordered_uids:
        step_count = step_count_by_uid.get(uid, 0)
        if step_count <= 0:
            continue
        display_index += 1
        stage_meta[uid] = {
            "index": display_index,
            "name": stage_names.get(uid, "阶段"),
            "order": order_map.get(uid, display_index - 1),
            "step_count": step_count,
        }

    ordered_stage_uids = [uid for uid in ordered_uids if uid in stage_meta]
    return stage_meta, ordered_stage_uids, unassigned_uid


def normalize_stage_uid(
    stage_uid: object,
    stage_meta: Dict[object, dict],
    ordered_stage_uids: List[object],
    unassigned_uid: Optional[str],
) -> object:
    """将缺失或未知阶段归一化为可展示阶段 uid。"""
    if stage_uid in stage_meta:
        return stage_uid
    if unassigned_uid and unassigned_uid in stage_meta:
        return unassigned_uid
    if ordered_stage_uids:
        return ordered_stage_uids[-1]
    return stage_uid
