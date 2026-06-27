# -*- coding: utf-8 -*-
"""阶段元数据与 dry-run 预览纯逻辑测试。"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine_core.preview import format_dry_run_lines
from engine_core.stages import (
    UNASSIGNED_STAGE_UID,
    build_stage_meta,
    normalize_stage_uid,
)


@dataclass
class StepLike:
    name: str
    stage_uid: str | None = None
    is_gate: bool = False


def test_build_stage_meta_skips_empty_stages_and_keeps_unassigned_last():
    steps = [
        StepLike("提取", "extract"),
        StepLike("清洗", "transform"),
        StepLike("手工检查"),
    ]

    stage_meta, ordered_uids, unassigned_uid = build_stage_meta(
        steps=steps,
        stage_order_by_uid={"empty": 0, "extract": 1, "transform": 2},
        stage_names_by_uid={"empty": "空阶段", "extract": "抽取", "transform": "转换"},
    )

    assert unassigned_uid == UNASSIGNED_STAGE_UID
    assert ordered_uids == ["extract", "transform", UNASSIGNED_STAGE_UID]
    assert "empty" not in stage_meta
    assert stage_meta["extract"]["index"] == 1
    assert stage_meta[UNASSIGNED_STAGE_UID]["name"] == "未归类"


def test_normalize_stage_uid_prefers_unassigned_bucket_for_unknown_stage():
    stage_meta = {UNASSIGNED_STAGE_UID: {"index": 1, "name": "未归类", "step_count": 1}}

    assert (
        normalize_stage_uid(
            "deleted-stage",
            stage_meta,
            [UNASSIGNED_STAGE_UID],
            UNASSIGNED_STAGE_UID,
        )
        == UNASSIGNED_STAGE_UID
    )


def test_format_dry_run_lines_groups_by_stage_and_batch_mode():
    steps = [
        StepLike("拉取", "extract"),
        StepLike("校验", "extract", is_gate=True),
        StepLike("汇总", "report"),
    ]
    stage_meta, ordered_uids, unassigned_uid = build_stage_meta(
        steps=steps,
        stage_order_by_uid={"extract": 0, "report": 1},
        stage_names_by_uid={"extract": "抽取", "report": "报表"},
    )

    lines = format_dry_run_lines(
        batches=[[steps[0]], [steps[1]], [steps[2]]],
        stage_meta=stage_meta,
        ordered_stage_uids=ordered_uids,
        unassigned_uid=unassigned_uid,
    )

    assert lines[0] == "═" * 40
    assert "阶段 S1 抽取 · 2步" in lines
    assert "执行组 1/2（串行）：拉取" in lines
    assert "执行组 2/2（检查点）：校验" in lines
    assert "阶段 S2 报表 · 1步" in lines
    assert "共 2 个阶段，3 个执行组，3 个步骤" in lines
