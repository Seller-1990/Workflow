# -*- coding: utf-8 -*-
"""Pure view-model helpers for StepTablePanel."""

from __future__ import annotations


def build_stage_records(stages) -> tuple[list[dict], dict[str, int]]:
    records: list[dict] = []
    index_by_uid: dict[str, int] = {}
    for index, stage in enumerate(stages or []):
        uid = getattr(stage, "uid", "")
        records.append(
            {
                "uid": uid,
                "name": getattr(stage, "name", "阶段"),
                "order": int(getattr(stage, "order", 0) or 0),
                "color": getattr(stage, "color", None),
            }
        )
        index_by_uid[uid] = index
    return records, index_by_uid


def ensure_default_stage_records(stages: list[dict]) -> tuple[list[dict], dict[str, int]]:
    if stages:
        return stages, {stage["uid"]: index for index, stage in enumerate(stages)}
    default = [{"uid": "", "name": "默认阶段", "order": 0, "color": None}]
    return default, {"": 0}


def sort_steps_by_stage(steps, stage_order_map: dict) -> list:
    def _stage_order(step) -> int:
        return int(stage_order_map.get(getattr(step, "stage_uid", None), 0) or 0)

    return sorted(steps or [], key=lambda step: (_stage_order(step), step.order))


def build_prev_by_id(steps_sorted: list) -> dict[int, object | None]:
    return {
        step.id: steps_sorted[index - 1] if index > 0 else None
        for index, step in enumerate(steps_sorted)
    }


def build_row_meta(steps_sorted: list, stages: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for stage in stages:
        stage_uid = stage["uid"]
        rows.append({"kind": "stage_header", "stage_uid": stage_uid})
        for step in steps_sorted:
            if getattr(step, "stage_uid", None) == stage_uid:
                rows.append({"kind": "step", "step_id": step.id, "stage_uid": stage_uid})
    return rows


def build_stage_render_context(steps_sorted: list, stages: list[dict]) -> dict:
    stage_uid_to_steps: dict[object, list] = {}
    for step in steps_sorted:
        stage_uid_to_steps.setdefault(getattr(step, "stage_uid", None), []).append(step)

    stage_display_index = {stage["uid"]: index for index, stage in enumerate(stages)}
    stage_name_by_uid = {stage["uid"]: stage["name"] for stage in stages}

    within_idx_by_step: dict[tuple[object, int], int] = {}
    uid_display_map = {}
    for stage_uid, steps in stage_uid_to_steps.items():
        for index, step in enumerate(steps):
            within_idx_by_step[(stage_uid, step.id)] = index

    for stage_uid, stage_index in stage_display_index.items():
        stage_name = stage_name_by_uid.get(stage_uid, "")
        for within, step in enumerate(stage_uid_to_steps.get(stage_uid, []), start=1):
            uid_display_map[step.uid] = {
                "code": f"S{stage_index + 1}-{within}",
                "stage_name": stage_name,
                "step_name": step.name,
                "step_id": step.id,
            }

    return {
        "stage_uid_to_steps": stage_uid_to_steps,
        "stage_display_index": stage_display_index,
        "stage_name_by_uid": stage_name_by_uid,
        "within_idx_by_step": within_idx_by_step,
        "uid_display_map": uid_display_map,
    }
