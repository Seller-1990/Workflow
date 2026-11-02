"""Skip-on-success decisions and recording; lifecycle retains public seams."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


def _lifecycle_module():
    from engine_core import lifecycle
    return lifecycle


# ============== Skip-on-success 决策 ==============

@dataclass
class SkipDecision:
    """``check_skip_on_success`` 命中时返回；调用方据此构造 StepResult / 发信号"""
    step_log_id: int
    start_time: datetime
    end_time: datetime
    note: str  # 默认 "已跳过（上次成功）"


def build_prev_step_status_map(
    workflow_id: int,
    *,
    exclude_run_history_id: Optional[int] = None,
    running_status_value: str = "running",
    pending_status_value: str = "pending",
) -> dict:
    """P-3: 一次性预取该工作流"上一次完结运行"中每个步骤的状态。

    返回 {step_id: status_str}，无最近完结运行时返回 {}。
    供 ``should_skip_on_success(..., prev_step_status_map=...)`` 跳过 N+1 查询。
    """
    latest = _lifecycle_module().get_latest_run_history(
        workflow_id,
        exclude_statuses=[running_status_value, pending_status_value],
        only_finished=True,
        exclude_run_history_id=exclude_run_history_id,
    )
    if not latest:
        return {}
    logs = _lifecycle_module().get_step_logs_by_run(latest.id) or []
    return {pl.step_id: pl.status for pl in logs}


def should_skip_on_success(
    *,
    step,
    run_history_id: int,
    running_status_value: str = "running",
    pending_status_value: str = "pending",
    prev_step_status_map: Optional[dict] = None,
) -> bool:
    """纯检查：判断本步骤是否应跳过（不写任何 DB）。

    #7: 把"检查"与"落库"拆开，让 engine 能在 emit step_started 之后再写 StepLog，
        避免任何 step_started 监听器同步查 DB 时看到 status=skipped 的语义漂移。
    P-3: 优先使用预取的 ``prev_step_status_map`` 跳过 N+1 查询。
    """
    if not getattr(step, "skip_on_success", False):
        return False

    # 预取路径：O(1) 查 map
    if prev_step_status_map is not None:
        return prev_step_status_map.get(step.id) == "success"

    # 回退路径：原 2 次 DB 查询（向后兼容）
    latest = _lifecycle_module().get_latest_run_history(
        step.workflow_id,
        exclude_statuses=[running_status_value, pending_status_value],
        only_finished=True,
        exclude_run_history_id=run_history_id,
    )
    if not latest:
        return False

    prev_logs = _lifecycle_module().get_step_logs_by_run(latest.id)
    for pl in prev_logs:
        if pl.step_id == step.id and pl.status == "success":
            return True
    return False


def record_skip_on_success(
    *,
    step,
    run_history_id: int,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    note: str = "已跳过（上次成功）",
) -> SkipDecision:
    """落库一条 skipped StepLog 并返回 SkipDecision。

    #7: caller 通常先发 step_started 信号，再调本函数写库，再发 step_finished。
    """
    now = datetime.now()
    start_time = start_time or now
    end_time = end_time or now
    step_log_id = _lifecycle_module().create_skipped_step_log(
        run_history_id=run_history_id,
        step_id=step.id,
        start_time=start_time,
        end_time=end_time,
        note=note,
        order=step.order,
    )
    return SkipDecision(
        step_log_id=step_log_id,
        start_time=start_time,
        end_time=end_time,
        note=note,
    )


def check_skip_on_success(
    *,
    step,
    run_history_id: int,
    running_status_value: str = "running",
    pending_status_value: str = "pending",
) -> Optional[SkipDecision]:
    """旧组合接口：检查 + 落库一步到位。

    保留以向后兼容；新代码建议用 should_skip_on_success + record_skip_on_success 配合
    在中间插入 step_started 信号。
    """
    if not _lifecycle_module().should_skip_on_success(
        step=step,
        run_history_id=run_history_id,
        running_status_value=running_status_value,
        pending_status_value=pending_status_value,
    ):
        return None
    return _lifecycle_module().record_skip_on_success(step=step, run_history_id=run_history_id)
