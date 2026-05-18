from collections import defaultdict
from typing import List, Dict, Optional

from models import Step
from exceptions import DependencyError


def compute_batches(
    workflow,
    steps: List[Step],
    stage_order_by_uid: Optional[Dict[str, int]] = None,
) -> List[List[Step]]:
    """计算步骤的分批执行计划（纯逻辑，不实际执行）

    Returns:
        按阶段分组的步骤批次列表

    设计说明：
    - retry_failed / from_step / from_stage 模式下 steps 是子集，子集外的依赖视为已完成（H3）。
    - HA1 优化：按 stage 预分桶（dict[int, list]）；pending 用 set 维护；deps 转 frozenset 缓存。
      复杂度由 O(n²) 降到 O(n+edges)。
    """
    if stage_order_by_uid is None:
        stage_order_by_uid = {}

    step_uids = {s.uid for s in steps}
    parallel_enabled = bool(getattr(workflow, "parallel_enabled", False))

    def _stage_of(s: Step) -> int:
        return int(stage_order_by_uid.get(getattr(s, "stage_uid", None), 0) or 0)

    # 预分桶 & 缓存
    uid_to_stage: Dict[str, int] = {s.uid: _stage_of(s) for s in steps}
    deps_by_uid: Dict[str, frozenset] = {
        s.uid: frozenset(d for d in s.get_depends_on() if d in step_uids)
        for s in steps
    }

    # 跨阶段依赖校验（仅子集内）
    for s in steps:
        s_stage = uid_to_stage[s.uid]
        for d in deps_by_uid[s.uid]:
            d_stage = uid_to_stage.get(d, 0)
            if d_stage > s_stage:
                raise DependencyError(
                    f"跨阶段依赖不允许：步骤「{s.name}」依赖未来阶段的步骤 uid={d}"
                )

    # 按阶段分桶，桶内按 order 排序
    stage_buckets: Dict[int, list[Step]] = defaultdict(list)
    for s in steps:
        stage_buckets[uid_to_stage[s.uid]].append(s)
    for stage in stage_buckets:
        stage_buckets[stage].sort(key=lambda s: s.order)

    stage_order_sorted = sorted(stage_buckets.keys())

    completed_success: set[str] = set()
    batches: List[List[Step]] = []

    for stage in stage_order_sorted:
        # 当前阶段 pending set
        pending_uids: set[str] = {s.uid for s in stage_buckets[stage]}
        pending_uid_to_step: Dict[str, Step] = {s.uid: s for s in stage_buckets[stage]}

        while pending_uids:
            # 当前批次：从 pending 中筛出 deps 全部满足的
            runnable: list[Step] = []
            for uid in list(pending_uids):
                if deps_by_uid[uid] <= completed_success:
                    runnable.append(pending_uid_to_step[uid])

            if not runnable:
                stuck_names = [pending_uid_to_step[u].name for u in pending_uids]
                stuck_uids = list(pending_uids)
                raise DependencyError(
                    f"依赖形成循环或无法满足：{len(stuck_names)} 个步骤被阻塞 "
                    f"({', '.join(stuck_names[:5])}{'...' if len(stuck_names) > 5 else ''})。"
                    f"请检查以下步骤的依赖关系是否形成环：{', '.join(stuck_uids)}"
                )

            # 保持 order 顺序
            runnable.sort(key=lambda s: s.order)

            if not parallel_enabled:
                batch = [runnable[0]]
            else:
                gate_steps = [s for s in runnable if s.is_gate]
                if gate_steps:
                    batch = [gate_steps[0]]
                else:
                    # 同依赖层并行
                    first_deps = deps_by_uid[runnable[0].uid]
                    batch = [s for s in runnable if deps_by_uid[s.uid] == first_deps]

            batches.append(batch)
            for s in batch:
                completed_success.add(s.uid)
                pending_uids.discard(s.uid)

    return batches