# -*- coding: utf-8 -*-
"""运行编排子系统（batch-4 自 engine.py 纯移动提取，行为不变）

覆盖「一次工作流运行的完整编排生命周期」：``_run`` 主流程（原子启动、
运行上下文保存/恢复、RunHistory 创建、步骤执行、状态归并与收尾）、
运行级取消判定、运行历史落库、完成信号与通知派发、按模式选步
（含单脚本步骤）、dry_run 预演、批次推进与失败明细收集、过期日志清理。

设计要点（与 step_execution / ui/run_dispatch.py 同一约定）：
- 每个函数的首个参数 ``engine`` 即 WorkflowEngine 实例；跨方法调用一律走
  ``engine._xxx`` 委托方法，保持实例级 monkeypatch（测试替身，如
  ``monkeypatch.setattr(engine, "_execute_steps", ...)``）动态分发语义；
  ``engine._running`` / ``engine._cancelled`` / ``engine._active_run_ids``
  / ``engine._lock`` / ``engine._executor`` 等实例状态仍留在
  WorkflowEngine 上，本模块经 ``engine.`` 属性直接读写。
- ``RunStatus`` / ``RunSignalPolicy`` / WorkflowError 异常族定义在
  engine.py，顶层 ``import engine`` 会形成循环导入；统一经
  ``_engine_module()`` 在调用时延迟解析。
- ``get_workflow_by_id`` / ``get_steps_by_workflow`` / ``_begin_run`` /
  ``_finalize_run`` / ``_build_prev_step_status_map`` / ``_select_steps`` /
  ``_build_stage_meta`` / ``_normalize_stage_uid`` / ``_build_stage_group_map``
  / ``_describe_batch_mode`` / ``_format_dry_run_lines`` /
  ``_cleanup_old_log_dirs`` / ``LOG_DIR`` / ``send_run_notification`` /
  ``get_stage_order_map`` / ``get_latest_run_history`` /
  ``get_step_logs_by_run`` / ``list_stages``
  等依赖同样经 engine 模块全局延迟解析（late-bound），保持
  ``monkeypatch.setattr("engine.xxx", ...)`` 模块级补丁语义不变。
"""

from __future__ import annotations

import logging
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from engine import RunMode, RunSignalPolicy, StepResult, WorkflowEngine
    from models import Step, Workflow


def _engine_module():
    """延迟导入 engine 模块（避免顶层循环导入，并保留 engine.* 模块级 monkeypatch 语义）"""
    import engine

    return engine


def send_notification(
    engine: WorkflowEngine,
    workflow: Workflow,
    run_id: str,
    status: str,
    log_dir: str,
    reason: str,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
):
    """发送钉钉通知（CA2: 委托给 engine_core.notification）"""
    eng = _engine_module()
    eng.send_run_notification(
        workflow,
        run_id=run_id,
        status=status,
        log_dir=log_dir,
        reason=reason,
        start_time=start_time,
        end_time=end_time,
        log_cb=engine._emit_log,
    )


def is_run_cancelled(engine: WorkflowEngine, run_cancel_event: threading.Event = None) -> bool:
    """当前运行是否被请求取消。

    ``run_cancel_event`` 用于嵌套子工作流这类局部取消场景：
    不污染引擎级 ``engine._cancelled``，但可让当前 run 及其步骤尽快收尾。
    """
    return engine.is_cancelled or bool(run_cancel_event and run_cancel_event.is_set())


def resolve_final_status(
    engine: WorkflowEngine,
    status: str,
    run_cancel_event: threading.Event = None,
) -> str:
    eng = _engine_module()
    return eng.RunStatus.CANCELLED.value if engine._is_run_cancelled(run_cancel_event) else status


def finalize_run_history(
    engine: WorkflowEngine,
    run_history_id: int | None,
    final_status: str,
    end_time: datetime,
    signal_policy: RunSignalPolicy,
) -> None:
    eng = _engine_module()
    if not run_history_id:
        return
    try:
        if not eng._finalize_run(run_history_id, status_value=final_status, end_time=end_time):
            engine._emit_log(f"严重警告：运行历史落库失败 run_history_id={run_history_id}，UI 状态可能停留在 running")
            if signal_policy.emit_error_details:
                try:
                    engine.error_details.emit([
                        {"step": "运行收尾", "error": "运行历史更新失败（DB 锁死或磁盘满）"}
                    ])
                except Exception:
                    pass
    except Exception as e:
        logger.warning("更新运行历史失败: %s", e)
        engine._emit_log("警告：更新运行历史失败")
        engine._emit_log(traceback.format_exc())


def emit_run_completion(
    engine: WorkflowEngine,
    *,
    workflow_id: int,
    workflow: Workflow | None,
    run_id: str | None,
    started_emitted: bool,
    final_status: str,
    log_dir: Path | None,
    reason: str,
    start_time: datetime | None,
    end_time: datetime,
    signal_policy: RunSignalPolicy,
) -> None:
    eng = _engine_module()
    if not started_emitted or not run_id:
        return
    try:
        if signal_policy.emit_run_signals:
            engine.workflow_finished.emit(workflow_id, run_id, final_status)
        if final_status == eng.RunStatus.SUCCESS.value:
            engine._emit_log("工作流运行成功")
        elif final_status == eng.RunStatus.CANCELLED.value:
            engine._emit_log("工作流已取消")
        else:
            engine._emit_log("工作流运行失败")

        if workflow and log_dir and signal_policy.send_notification:
            try:
                if engine._executor is not None:
                    engine._executor.submit(
                        engine._send_notification,
                        workflow=workflow,
                        run_id=run_id,
                        status=final_status,
                        log_dir=str(log_dir),
                        reason=reason,
                        start_time=start_time,
                        end_time=end_time,
                    )
                else:
                    logger.warning("通知未发送：executor 已关闭")
            except Exception as e:
                logger.warning("提交通知任务失败: %s", e)
    except Exception as e:
        logger.warning("运行收尾处理失败: %s", e)
        engine._emit_log("警告：运行收尾处理失败")
        engine._emit_log(traceback.format_exc())


def restore_run_context(
    engine: WorkflowEngine,
    *,
    allow_nested: bool,
    run_history_id: int | None,
    prev_running: bool,
    prev_run_history_id: int | None,
    prev_run_id: str | None,
    prev_trace_id: str | None,
    prev_parent_run_id: str | None,
) -> None:
    with engine._lock:
        if not allow_nested:
            engine._running = prev_running
            engine._current_run_history_id = prev_run_history_id
            engine._current_run_id = prev_run_id
            engine._current_trace_id = prev_trace_id
            engine._current_parent_run_id = prev_parent_run_id
        if run_history_id is not None:
            engine._active_run_ids.discard(run_history_id)
        if not engine._running:
            engine._cancelled = False


def run_workflow(
    engine: WorkflowEngine,
    workflow_id: int,
    mode: RunMode,
    step_id: int = None,
    stage_uid: str = None,
    reason: str = "manual",
    allow_nested: bool = False,
    signal_policy: Optional[RunSignalPolicy] = None,
    parent_run_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    external_cancel_event: threading.Event = None,
    run_arg_overrides=None,
) -> bool:
    """执行工作流（原 WorkflowEngine._run 方法体）

    Args:
        workflow_id: 工作流 ID
        mode: 运行模式
        step_id: 步骤 ID（用于 FROM_STEP 和 ONLY_STEP 模式）
        stage_uid: 阶段 UID（用于 FROM_STAGE 和 ONLY_STAGE 模式）
        reason: 运行原因

    Returns:
        是否成功
    """
    eng = _engine_module()
    run_history_id = None
    run_id = None
    log_dir = None
    started_emitted = False
    start_time = None
    end_time = None
    signal_policy = signal_policy or eng.RunSignalPolicy()
    status = eng.RunStatus.FAILURE.value
    success = False
    workflow = None
    prev_running = False
    prev_run_history_id = None
    prev_run_id = None
    prev_trace_id = None
    prev_parent_run_id = None
    effective_parent_run_id = None
    effective_trace_id = None

    # 原子启动：消除 UI/监听同时触发的双启动窗口
    # #2: 仅在 outermost run（allow_nested=False）时修改实例属性。
    # nested run 用本地 run_id / trace_id 即可，避免并行 sub_workflow 出现 LIFO 栈破坏。
    from script_arg_utils import normalize_run_arg_overrides
    # 本地不可变上下文：不挂 engine 实例字段，避免并行/嵌套污染
    local_run_arg_overrides = normalize_run_arg_overrides(run_arg_overrides)
    with engine._lock:
        if engine._running and not allow_nested:
            engine._emit_log("错误：已有工作流正在运行")
            return False
        prev_running = engine._running
        prev_run_history_id = engine._current_run_history_id
        prev_run_id = engine._current_run_id
        prev_trace_id = engine._current_trace_id
        prev_parent_run_id = engine._current_parent_run_id
        if not allow_nested:
            # 只有 outermost 改 _running——nested 共享 outer 的 True，无需再写
            engine._running = True
        if not prev_running:
            engine._cancelled = False
        effective_trace_id = trace_id if trace_id is not None else engine._current_trace_id
        effective_parent_run_id = parent_run_id if parent_run_id is not None else engine._current_parent_run_id
        start_time = datetime.now()

    try:
        # 获取工作流
        workflow = eng.get_workflow_by_id(workflow_id)
        if not workflow:
            raise eng.ConfigurationError(f"工作流不存在: {workflow_id}")

        # SEC1: 首次运行含 risky import path 的工作流时检查确认标记
        from database_import_validation import workflow_has_unconfirmed_risky_paths
        if workflow_has_unconfirmed_risky_paths(workflow):
            engine._emit_log("错误：此工作流包含未经确认的导入路径（绝对路径或上级目录引用），请在工作流配置中确认路径安全后再运行")
            return False

        # 自动清理过期日志（后台线程执行，避免阻塞启动）
        engine._cleanup_old_logs_async(workflow)

        # 获取步骤
        all_steps = eng.get_steps_by_workflow(workflow_id)
        if not all_steps:
            raise eng.ConfigurationError("工作流没有步骤")

        # 根据模式筛选步骤
        steps = engine._select_steps(all_steps, mode, step_id, workflow, stage_uid=stage_uid)
        if not steps:
            engine._emit_log("没有需要执行的步骤")
            return True

        # CA2: 创建 RunHistory + log_dir + 状态切 running，整体下沉到 lifecycle 模块
        ctx = eng._begin_run(
            workflow=workflow,
            mode_value=mode.value,
            run_mode_param=str(step_id) if step_id else None,
            reason=reason,
            trace_id=effective_trace_id,
            parent_run_id=effective_parent_run_id,
            start_time=start_time,
            running_status_value=eng.RunStatus.RUNNING.value,
        )
        run_history_id = ctx.run_history_id
        run_id = ctx.run_id
        log_dir = ctx.log_dir
        # #2: 仅 outermost 把上下文写入实例属性。nested run（含并行 sub_workflow）
        # 不修改 instance attrs，靠 local run_id / trace_id 即可；UI/外部读到的始终是 outer。
        with engine._lock:
            if not allow_nested:
                engine._current_trace_id = ctx.trace_id
                engine._current_parent_run_id = ctx.parent_run_id
                engine._current_run_history_id = run_history_id
                engine._current_run_id = run_id
            # 修复 H1/H12：所有 run（包括 nested）的 history_id 都加入栈，用于 force_stop 命中
            engine._active_run_ids.add(run_history_id)

        if signal_policy.emit_run_signals:
            engine.workflow_started.emit(workflow_id, run_id)
            started_emitted = True
        engine._emit_log(f"开始运行工作流: {workflow.name}")
        engine._emit_log(f"运行模式: {mode.value}")
        engine._emit_log(f"日志目录: {log_dir}")

        # 执行步骤
        success = engine._execute_steps(
            workflow,
            steps,
            run_history_id,
            log_dir,
            signal_policy=signal_policy,
            run_cancel_event=external_cancel_event,
            run_arg_overrides=local_run_arg_overrides,
        )

        # 更新运行结果
        if engine._is_run_cancelled(external_cancel_event):
            status = eng.RunStatus.CANCELLED.value
        else:
            status = eng.RunStatus.SUCCESS.value if success else eng.RunStatus.FAILURE.value

        return success

    except eng.WorkflowError as e:
        engine._emit_log(f"错误: {e}")
        return False
    except Exception as e:
        logger.exception("未知错误: %s", e)
        engine._emit_log(f"未知错误: {e}")
        engine._emit_log(traceback.format_exc())
        return False
    finally:
        end_time = datetime.now()
        final_status = engine._resolve_final_status(status, external_cancel_event)
        engine._finalize_run_history(run_history_id, final_status, end_time, signal_policy)
        engine._emit_run_completion(
            workflow_id=workflow_id,
            workflow=workflow,
            run_id=run_id,
            started_emitted=started_emitted,
            final_status=final_status,
            log_dir=log_dir,
            reason=reason,
            start_time=start_time,
            end_time=end_time,
            signal_policy=signal_policy,
        )
        engine._restore_run_context(
            allow_nested=allow_nested,
            run_history_id=run_history_id,
            prev_running=prev_running,
            prev_run_history_id=prev_run_history_id,
            prev_run_id=prev_run_id,
            prev_trace_id=prev_trace_id,
            prev_parent_run_id=prev_parent_run_id,
        )


def select_steps(
    engine: WorkflowEngine,
    all_steps: List[Step],
    mode: RunMode,
    step_id: int,
    workflow: Workflow,
    stage_uid: str = None,
) -> List[Step]:
    """根据运行模式选择步骤"""
    eng = _engine_module()
    return eng._select_steps(
        all_steps=all_steps,
        mode_value=mode.value,
        step_id=step_id,
        workflow=workflow,
        stage_uid=stage_uid,
        get_single_script_step=engine._get_single_script_step,
        get_stage_order_map=eng.get_stage_order_map,
        get_latest_run_history=eng.get_latest_run_history,
        get_step_logs_by_run=eng.get_step_logs_by_run,
        running_status_value=eng.RunStatus.RUNNING.value,
        pending_status_value=eng.RunStatus.PENDING.value,
        log_cb=engine._emit_log,
    )


def get_single_script_step(engine: WorkflowEngine, workflow: Workflow) -> Optional[Step]:
    """获取已存在的单脚本步骤（退役：单脚本生产路径已移除，不再自动创建）"""
    steps = engine.get_steps_by_workflow(workflow.id)
    for step in steps:
        if step.uid == "single_script":
            return step
    return None


def dry_run(engine: WorkflowEngine, workflow_id: int):
    """预演模式：输出分批计划但不实际执行"""
    eng = _engine_module()
    workflow = eng.get_workflow_by_id(workflow_id)
    if not workflow:
        engine._emit_log("错误：工作流不存在")
        return
    all_steps = eng.get_steps_by_workflow(workflow_id)
    if not all_steps:
        engine._emit_log("工作流没有步骤")
        return
    try:
        stage_map = eng.get_stage_order_map(workflow_id)
        batches = engine.compute_batches(workflow, all_steps, stage_map)
    except eng.DependencyError as e:
        engine._emit_log(f"[预演] 依赖错误: {e}")
        return

    stage_meta, ordered_stage_uids, unassigned_uid = engine._build_stage_meta(
        workflow_id=workflow_id,
        steps=all_steps,
        stage_order_by_uid=stage_map,
    )

    for line in eng._format_dry_run_lines(
        batches=batches,
        stage_meta=stage_meta,
        ordered_stage_uids=ordered_stage_uids,
        unassigned_uid=unassigned_uid,
    ):
        engine._emit_log(line)


def execute_steps(
    engine: WorkflowEngine,
    workflow: Workflow,
    steps: List[Step],
    run_history_id: int,
    log_dir: Path,
    signal_policy: RunSignalPolicy,
    run_cancel_event: threading.Event = None,
    run_arg_overrides=None,
) -> bool:
    """执行步骤

    依赖与并行规则：
    - 依赖（depends_on）必须先完成
    - 检查点步骤（is_gate=True）优先单独执行
    - 自动并行：仅需 workflow.parallel_enabled=True，同依赖层步骤默认并行
    """
    eng = _engine_module()
    total_steps = len(steps)
    completed_steps = 0
    failed_details = []  # 收集失败步骤摘要

    # R2-#1: 预取改为 local 变量，避免父子 sub_workflow 共享 self 属性互相覆盖
    # 沿调用链把 prev_step_status_map 传给 _execute_single_step / _execute_parallel_steps
    try:
        prev_step_status_map = eng._build_prev_step_status_map(
            workflow.id,
            exclude_run_history_id=run_history_id,
            running_status_value=eng.RunStatus.RUNNING.value,
            pending_status_value=eng.RunStatus.PENDING.value,
        )
    except Exception as e:
        logger.warning("预取上次步骤状态失败，回退按步查询: %s", e)
        prev_step_status_map = None

    stage_map = eng.get_stage_order_map(workflow.id)
    batches = engine.compute_batches(workflow, steps, stage_map)

    stage_meta, ordered_stage_uids, unassigned_uid = engine._build_stage_meta(
        workflow_id=workflow.id,
        steps=steps,
        stage_order_by_uid=stage_map,
    )

    stage_uid_to_groups = eng._build_stage_group_map(
        batches=batches,
        stage_meta=stage_meta,
        ordered_stage_uids=ordered_stage_uids,
        unassigned_uid=unassigned_uid,
    )
    stage_uid_to_group_total = {
        uid: len(groups) for uid, groups in stage_uid_to_groups.items() if groups
    }

    stage_uid_to_group_index: Dict[object, int] = {uid: 0 for uid in stage_uid_to_group_total.keys()}
    current_stage_uid = None

    for batch in batches:
        if engine._is_run_cancelled(run_cancel_event):
            engine._emit_log(f"运行已取消（已完成 {completed_steps}/{total_steps}）")
            engine._emit_failed_details(failed_details, signal_policy)
            return False

        # 阶段标题（阶段变化时打印一次）
        if batch:
            raw_uid = getattr(batch[0], "stage_uid", None)
        else:
            raw_uid = None
        stage_uid = engine._normalize_stage_uid(raw_uid, stage_meta, ordered_stage_uids, unassigned_uid)
        if stage_uid != current_stage_uid and stage_uid in stage_meta:
            meta = stage_meta[stage_uid]
            engine._emit_log(f"══ 阶段 S{meta['index']} {meta['name']}（{meta['step_count']}步）══")
            current_stage_uid = stage_uid

        # 执行组提示（仅当该阶段存在多个执行组时显示）
        if batch and stage_uid in stage_uid_to_group_total:
            group_total = stage_uid_to_group_total.get(stage_uid, 1)
            names = ", ".join(s.name for s in batch)
            mode = eng._describe_batch_mode(batch)
            if group_total > 1:
                stage_uid_to_group_index[stage_uid] = stage_uid_to_group_index.get(stage_uid, 0) + 1
                idx = stage_uid_to_group_index[stage_uid]
                engine._emit_log(f"执行组 {idx}/{group_total}（{mode}）：{names}")
            else:
                engine._emit_log(f"  {mode}：{names}")

        # 执行步骤
        if len(batch) == 1:
            step = batch[0]
            try:
                result = engine._execute_single_step(
                    workflow, step, run_history_id, log_dir, signal_policy,
                    prev_step_status_map=prev_step_status_map,
                    run_cancel_event=run_cancel_event,
                    run_arg_overrides=run_arg_overrides,
                )
            except Exception as e:
                logger.warning("单步执行异常: step=%s, error=%s", step.name, e)
                result = eng.StepResult(
                    step_id=step.id,
                    step_name=step.name,
                    status="failure",
                    exit_code=-1,
                    error_message=str(e),
                )
            completed_steps += 1
            engine._update_execution_progress(completed_steps, total_steps, signal_policy)

            # 取消状态：直接退出，不当作失败
            if result.status == "cancelled":
                return False

            if not result.success:
                engine._append_failed_detail(failed_details, step, result)
                engine._emit_failed_details(failed_details, signal_policy)
                return False
        else:
            results = engine._execute_parallel_steps(
                workflow, batch, run_history_id, log_dir, signal_policy,
                prev_step_status_map=prev_step_status_map,
                run_cancel_event=run_cancel_event,
                run_arg_overrides=run_arg_overrides,
            )
            completed_steps += len(results)
            engine._update_execution_progress(completed_steps, total_steps, signal_policy)
            if engine._is_run_cancelled(run_cancel_event):
                engine._emit_failed_details(failed_details, signal_policy)
                return False
            if not engine._handle_batch_results(batch, results, failed_details, signal_policy):
                return False

    return True


def build_stage_meta(
    engine: WorkflowEngine,
    workflow_id: int,
    steps: List[Step],
    stage_order_by_uid: Dict[str, int],
) -> tuple[Dict[object, dict], List[object], Optional[str]]:
    """构建用途阶段元信息（用于日志展示）

    Returns:
        stage_meta: stage_uid -> {index,name,order,step_count}
        ordered_stage_uids: 按用途阶段顺序排列的 stage_uid 列表（包含必要的未归类 stage）
        unassigned_uid: 未归类阶段 uid（若无需则为 None）
    """
    eng = _engine_module()
    stage_names: Dict[object, str] = {}
    try:
        stages = eng.list_stages(workflow_id)
        stage_names.update({s.uid: s.name for s in stages})
    except Exception as e:
        logger.warning("获取阶段列表失败: %s", e)
    return eng._build_stage_meta(
        steps=steps,
        stage_order_by_uid=stage_order_by_uid,
        stage_names_by_uid=stage_names,
    )


def normalize_stage_uid(
    engine: WorkflowEngine,
    stage_uid: object,
    stage_meta: Dict[object, dict],
    ordered_stage_uids: List[object],
    unassigned_uid: Optional[str],
) -> object:
    """将未知/缺失 stage_uid 归一化为日志可展示的阶段 uid。"""
    eng = _engine_module()
    return eng._normalize_stage_uid(
        stage_uid,
        stage_meta,
        ordered_stage_uids,
        unassigned_uid,
    )


def append_failed_detail(
    engine: WorkflowEngine,
    failed_details: list[dict],
    step: Step,
    result: StepResult,
) -> None:
    failed_details.append({
        "step_id": step.id,
        "step_name": step.name,
        "error_message": result.error_message or "未知错误",
        "suggested_fix": result.suggested_fix or "",
    })


def emit_failed_details(
    engine: WorkflowEngine,
    failed_details: list[dict],
    signal_policy: RunSignalPolicy,
) -> None:
    if failed_details and signal_policy.emit_error_details:
        engine.error_details.emit(failed_details)


def update_execution_progress(
    engine: WorkflowEngine,
    completed_steps: int,
    total_steps: int,
    signal_policy: RunSignalPolicy,
) -> None:
    if signal_policy.emit_progress_signals:
        engine.progress_updated.emit(completed_steps, total_steps)


def handle_batch_results(
    engine: WorkflowEngine,
    batch: list[Step],
    results: list[StepResult],
    failed_details: list[dict],
    signal_policy: RunSignalPolicy,
) -> bool:
    has_failure = False
    for step, result in zip(batch, results):
        if result.status == "cancelled":
            engine._emit_failed_details(failed_details, signal_policy)
            return False
        if not result.success:
            has_failure = True
            engine._append_failed_detail(failed_details, step, result)

    if has_failure:
        engine._emit_failed_details(failed_details, signal_policy)
        return False
    return True


def cleanup_old_logs_async(engine: WorkflowEngine, workflow: Workflow):
    """在后台执行日志清理，避免阻塞工作流启动"""
    def cleanup():
        try:
            engine._cleanup_old_logs(workflow)
        except Exception as e:
            logger.warning("日志清理失败: %s", e)
        finally:
            # R3-#4: 释放线程局部 scoped_session，避免每次运行残留 identity map
            try:
                from database import cleanup_session
                cleanup_session()
            except Exception:
                pass
            pass  # 清理失败不应影响主流程

    if engine._executor is not None:
        try:
            engine._executor.submit(cleanup)
        except (RuntimeError, AttributeError):
            thread = threading.Thread(target=cleanup, daemon=True)
            thread.start()
    else:
        thread = threading.Thread(target=cleanup, daemon=True)
        thread.start()


def cleanup_old_logs(engine: WorkflowEngine, workflow: Workflow):
    """自动清理过期日志目录

    M1 修复：使用严格正则匹配日志目录名（YYYYMMDD_HHMMSS 或带 _xxxx 后缀），
    避免共享前缀但非日志目录被误删。
    L6 修复：跳过仍处于 running 状态的 RunHistory 引用的目录，
    防止用户回拨系统时间后误删当前正在写入的日志目录。
    """
    eng = _engine_module()
    try:
        retention_days = getattr(workflow, 'log_retention_days', 30) or 30
        # L6: 收集仍在 running 的 RunHistory 引用的目录名
        active_dir_names: set[str] = set()
        try:
            from database import get_session
            from models import RunHistory
            with get_session() as session:
                rows = (
                    session.query(RunHistory.log_dir)
                    .filter(
                        RunHistory.workflow_id == workflow.id,
                        RunHistory.status == "running",
                    )
                    .all()
                )
                for (log_dir,) in rows:
                    if log_dir:
                        active_dir_names.add(Path(log_dir).name)
        except Exception as e:
            logger.warning("收集活跃运行日志目录失败: %s", e)
        removed = eng._cleanup_old_log_dirs(
            workflow,
            base_log_dir=eng.LOG_DIR,
            active_dir_names=active_dir_names,
        )
        if removed:
            engine._emit_log(f"已清理 {removed} 个过期日志目录（保留 {retention_days} 天）")
    except Exception as e:
        logger.exception("日志清理出错: %s", e)
        engine._emit_log(f"日志清理出错: {e}")
