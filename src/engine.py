# -*- coding: utf-8 -*-
"""工作流编排引擎

基于 workflow-orchestration-patterns 和 error-handling-patterns 技能实现：
- Fan-Out/Fan-In 并行执行
- 自定义异常层次结构
- 重试与指数退避
- 优雅降级
"""

import logging
import time
import threading
import os
import traceback

logger = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional

# CA2: 监听子系统已抽到 engine_core.watcher；本模块仅做薄封装
from engine_core.watcher import (
    FileWatcher,
    validate_watch_folders as _validate_watch_folders,
)
# M1: 多 watcher 管理（start/stop/restore）已抽到 engine_core.watch_manager
from engine_core.watch_manager import WatchManager
from engine_core.notification import send_run_notification
from engine_core.lifecycle import (
    begin_run as _begin_run,
    finalize_run as _finalize_run,
    should_skip_on_success as _should_skip_on_success,
    record_skip_on_success as _record_skip_on_success,
    build_prev_step_status_map as _build_prev_step_status_map,
)
from engine_core.scheduler import SchedulerMetrics, run_steps_parallel as _run_steps_parallel
from engine_core.cancel import install_cancel_watcher as _install_cancel_watcher
from engine_core.stages import (
    build_stage_meta as _build_stage_meta,
    normalize_stage_uid as _normalize_stage_uid,
)
from engine_core.preview import (
    build_stage_group_map as _build_stage_group_map,
    describe_batch_mode as _describe_batch_mode,
    format_dry_run_lines as _format_dry_run_lines,
)
from engine_core.log_cleanup import cleanup_old_log_dirs as _cleanup_old_log_dirs
from engine_core.selection import select_steps as _select_steps
from engine_core.force_stop import (
    force_cancel_run_record as _force_cancel_run_record,
    read_run_history_status as _read_run_history_status,
)
# batch-3: 单步执行完整生命周期（skip 判定/StepLog/重试/取消/失败诊断/并行批执行/收尾）
# 下沉到 engine_core.step_execution；WorkflowEngine 保留同签名薄委托。
from engine_core import step_execution as _step_execution
# batch-4: 运行编排（_run 主流程/取消判定/收尾/选步/dry_run/批次推进/日志清理）
# 下沉到 engine_core.run_orchestration；WorkflowEngine 保留同签名薄委托。
from engine_core import run_orchestration as _run_orchestration
from watch_rules import detect_watch_output_conflicts

from PySide6.QtCore import QObject, Signal, Slot

from config import LOG_DIR
from database import (
    get_session, get_workflow_by_id, get_steps_by_workflow,
    update_run_history,
    create_step_log, update_step_log,
    get_latest_run_history, get_step_logs_by_run,
    ensure_single_script_step, get_stage_order_map, list_stages,
    cleanup_session,
)
from models import Workflow, Step, RunHistory
from executors import (
    ExecutorResult,
    get_executor,
    has_non_retryable_policy,
)
from diagnostics import ErrorDiagnostician
from duration_utils import format_duration_short
from exceptions import (
    WorkflowError, ConfigurationError, DependencyError,
)


# ============== 运行模式与状态 ==============

class RunMode(Enum):
    """运行模式"""
    FULL = "full"                    # 全流程运行
    FROM_STEP = "from_step"          # 从指定步骤开始
    ONLY_STEP = "only_step"          # 只运行指定步骤
    ONLY_STAGE = "only_stage"        # 只运行指定阶段
    FROM_STAGE = "from_stage"        # 从指定阶段开始
    RETRY_FAILED = "retry_failed"    # 重试失败步骤


class RunStatus(Enum):
    """运行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


@dataclass
class StepResult:
    """步骤执行结果"""
    step_id: int
    step_name: str
    status: str
    exit_code: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    log_dir: Optional[str] = None
    # 智能诊断字段
    suggested_fix: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status in {"success", "skipped"}

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


@dataclass(frozen=True)
class RunSignalPolicy:
    emit_run_signals: bool = True
    emit_step_signals: bool = True
    emit_progress_signals: bool = True
    emit_error_details: bool = True
    send_notification: bool = True  # 控制是否发送钉钉通知


# ============== 工作流引擎 ==============

class WorkflowEngine(QObject):
    """工作流编排引擎
    
    信号：
        workflow_started: 工作流开始
        workflow_finished: 工作流结束
        step_started: 步骤开始
        step_finished: 步骤结束
        log_output: 日志输出
        progress_updated: 进度更新
    """
    
    # Qt 信号
    workflow_started = Signal(int, str)  # workflow_id, run_id
    workflow_finished = Signal(int, str, str)  # workflow_id, run_id, status(success/failure/cancelled)
    step_started = Signal(int, str)  # step_id, step_name
    step_finished = Signal(int, str, str, object)  # step_id, step_name, status, duration_seconds
    log_output = Signal(str)  # message
    progress_updated = Signal(int, int)  # current, total
    error_details = Signal(list)  # [{step_name, step_id, error_message}, ...]
    # R2-#4: 监听状态信号，UI 据此显示持续指示灯
    watch_started = Signal(int, list)  # workflow_id, folders
    watch_stopped = Signal(int)        # workflow_id（最近一次开启的；可为 0 表示无）


    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._cancelled = False
        self._current_run_history_id = None
        self._last_scheduler_metrics = None
        self._current_run_id = None
        self._current_trace_id = None       # 执行追踪 ID
        self._current_parent_run_id = None   # 父运行 ID（子工作流）
        # 嵌套运行栈：所有「正在跑」的 run_history_id（用于 force_stop_run 命中任一即触发）
        self._active_run_ids: set[int] = set()
        self._lock = threading.Lock()
        # 动态计算线程池大小：基于 CPU 核心数，上限 32
        max_workers = min(32, (os.cpu_count() or 4) + 4)
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        # CA2: 监听器子系统抽到 engine_core.watcher
        # M1: 多 watcher 管理抽到 engine_core.watch_manager.WatchManager。
        # 回调用 lambda 在本模块内定义（late-bound）：
        # get_steps_by_workflow / detect_watch_output_conflicts / _validate_watch_folders
        # 在调用时才从 engine 模块全局解析，保持模块级 monkeypatch 语义；
        # watch_started / watch_stopped Qt 信号仍挂在引擎上，经 emit 回调转发。
        self._watch_manager = WatchManager(
            log_cb=self._emit_log,
            trigger_cb=lambda wf_id, reason: self.run_all(wf_id, reason=reason),
            is_running_cb=lambda: self.is_running,
            emit_started_cb=lambda wf_id, folders: self.watch_started.emit(wf_id, folders),
            emit_stopped_cb=lambda wf_id: self.watch_stopped.emit(wf_id),
            validate_folders_cb=lambda folders: _validate_watch_folders(folders),
            detect_conflicts_cb=lambda folders, steps: detect_watch_output_conflicts(folders, steps),
            get_steps_cb=lambda wf_id: get_steps_by_workflow(wf_id),
        )

    @staticmethod
    def validate_watch_folders(folders: list[str]) -> list[str]:
        """校验监听目录（委托给 engine_core.watcher.validate_watch_folders）"""
        return _validate_watch_folders(folders)
    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running
    
    def cancel(self):
        """取消当前运行"""
        with self._lock:
            self._cancelled = True

    def force_stop_run(self, run_history_id: int):
        """强制停止指定运行：先尝试取消当前引擎运行，再将数据库中该记录及未完成步骤标记为 cancelled

        适用场景：任务历史列表中出现 status=running 的"孤儿"记录（引擎已不在运行该任务），
        需要手动将其标记为已取消以释放状态。

        修复 H1/H12：使用嵌套运行栈 _active_run_ids 识别——
        命中栈内任一 run_history_id 即触发 cancel，避免父运行被误置 cancelled 但引擎仍跑子工作流。
        """
        # 1) 引擎正在运行且目标在活动运行栈中 → 正常 cancel。
        # 2) 其余一律只做 DB 孤儿记录清理，绝不设置 _cancelled。
        #
        # P0-1：旧实现只要 self._running 为真就无条件取消，导致用户从历史列表停止一条
        # 孤儿记录 B 时，把真正在跑的 A 误杀（且 B 的库记录根本没写终态）。
        # 说明：run_orchestration 在同一 lock 内原子写入 _current_run_history_id 与
        # _active_run_ids.add，真正在跑的 run 必然已在栈中；启动瞬间（_begin_run 已建
        # DB 记录、但尚未进入该 lock 段）无法用 current 区分"正在启动的 run"与"旧孤儿
        # 记录"（此刻 current 仍是上一值）——对该极窄窗口宁可只做 DB 清理（停止无效，
        # 引擎继续跑），也绝不再误伤正在运行的其它任务。
        with self._lock:
            if self._running and run_history_id in self._active_run_ids:
                self._cancelled = True
                self._emit_log(f"已发送停止信号给当前运行 (run_history_id={run_history_id})")
                return

        # 2) 否则直接在数据库中标记为 cancelled（孤儿记录）
        try:
            from database import cancel_pending_step_logs

            # R5-#3: 先批量取消 step_logs，再写 run_history 终态。
            # update_run_history 终态时会 wal_checkpoint，能一次性把 step_logs 一起落主库，
            # 避免跨进程读到 "run cancelled 但 step pending" 的窗口。
            _force_cancel_run_record(
                run_history_id,
                get_status=lambda rid: _read_run_history_status(
                    rid,
                    session_factory=get_session,
                    run_history_model=RunHistory,
                ),
                cancel_pending_step_logs=cancel_pending_step_logs,
                update_run_history=update_run_history,
                cancelled_status_value=RunStatus.CANCELLED.value,
                now=datetime.now(),
                log_cb=self._emit_log,
                warn_cb=logger.warning,
            )
        except Exception as e:
            logger.warning("强制停止运行记录失败: %s", e)
            self._emit_log(f"强制停止失败: {e}")

    def wait_for_completion(self, timeout: float = 10.0) -> bool:
        """等待当前运行完成

        Args:
            timeout: 最大等待秒数

        Returns:
            True 如果运行已完成，False 如果超时
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._running:
                    return True
            time.sleep(0.1)
        return False

    @property
    def is_cancelled(self) -> bool:
        """线程安全地检查取消标志"""
        with self._lock:
            return self._cancelled
    
    # 日志级别映射：消息前缀 -> 级别
    _LOG_LEVEL_MAP = [
        ("错误：", "ERROR"),
        ("失败：", "ERROR"),
        ("警告：", "WARNING"),
        ("已取消", "WARNING"),
        ("取消", "WARNING"),
        ("跳过", "INFO"),
        ("成功", "INFO"),
        ("完成", "INFO"),
        ("正在", "INFO"),
        ("开始", "INFO"),
    ]

    def _classify_log_level(self, message: str) -> str:
        """根据消息内容自动推断日志级别"""
        for prefix, level in self._LOG_LEVEL_MAP:
            if prefix in message:
                return level
        return "INFO"

    @Slot(str)
    def _emit_log(self, message: str):
        """发送日志信号（自动推断级别并附加级别标签）

        R3-#3: 标 @Slot(str)，可被 QMetaObject.invokeMethod 跨线程调用
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        level = self._classify_log_level(message)
        self.log_output.emit(f"[{timestamp}] [{level}] {message}")

    def _send_notification(
        self,
        workflow: Workflow,
        run_id: str,
        status: str,
        log_dir: str,
        reason: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime]
    ):
        """发送钉钉通知（CA2: 委托给 engine_core.notification）"""
        return _run_orchestration.send_notification(
            self, workflow, run_id, status, log_dir, reason, start_time, end_time,
        )

    # ============== 监听触发 ==============
    # M1: _make_watcher / start_watch / stop_watch / restore_watches（含 _safe_int）
    # 已整体移至 engine_core.watch_manager.WatchManager；此处仅保留薄委托与
    # ``_watchers`` 属性契约（测试/调用方按 dict 读取，也可整体赋值替换）。

    @property
    def _watchers(self) -> dict[int, FileWatcher]:
        """M1: 按 workflow_id 的监听器字典（实际由 WatchManager 持有）"""
        return self._watch_manager.watchers

    @_watchers.setter
    def _watchers(self, value: dict[int, FileWatcher]) -> None:
        self._watch_manager.watchers = value

    def start_watch(self, workflow: Workflow) -> bool:
        """启动该工作流的文件监听（M1: 每工作流独立 watcher；委托 WatchManager）"""
        return self._watch_manager.start_watch(workflow)

    def stop_watch(self, workflow_id: int | None = None, join_timeout: float = 1.0):
        """停止文件监听（M1: ``workflow_id=None`` 停止全部；委托 WatchManager）"""
        return self._watch_manager.stop_watch(workflow_id, join_timeout)

    def restore_watches(self) -> list[tuple[str, bool]]:
        """应用启动时恢复所有 watch_enabled 工作流的监听（M1；委托 WatchManager）"""
        return self._watch_manager.restore_watches()

    def shutdown(self, wait: bool = True):
        """关闭引擎，释放资源

        Args:
            wait: 是否等待线程池中的任务完成
        """
        self.stop_watch()
        with self._lock:
            self._cancelled = True
        if self._executor:
            self._executor.shutdown(wait=wait, cancel_futures=not wait)
            self._executor = None

    def __del__(self):
        """析构函数，确保资源释放"""
        try:
            if hasattr(self, '_executor') and self._executor:
                self._executor.shutdown(wait=False)
        except Exception:
            pass

    # ============== 四种运行模式 ==============
    
    def run_all(self, workflow_id: int, reason: str = "manual", run_arg_overrides=None) -> bool:
        """全流程运行"""
        return self._run(workflow_id, RunMode.FULL, reason=reason, run_arg_overrides=run_arg_overrides)
    
    def run_from(self, workflow_id: int, from_step_id: int, reason: str = "manual", run_arg_overrides=None) -> bool:
        """从指定步骤开始运行"""
        return self._run(
            workflow_id, RunMode.FROM_STEP, step_id=from_step_id, reason=reason,
            run_arg_overrides=run_arg_overrides,
        )
    
    def run_only(self, workflow_id: int, step_id: int, reason: str = "manual", run_arg_overrides=None) -> bool:
        """只运行指定步骤"""
        return self._run(
            workflow_id, RunMode.ONLY_STEP, step_id=step_id, reason=reason,
            run_arg_overrides=run_arg_overrides,
        )
    
    def run_stage(self, workflow_id: int, stage_uid: str, reason: str = "manual", run_arg_overrides=None) -> bool:
        """只运行指定阶段"""
        return self._run(
            workflow_id, RunMode.ONLY_STAGE, stage_uid=stage_uid, reason=reason,
            run_arg_overrides=run_arg_overrides,
        )
    
    def run_from_stage(self, workflow_id: int, stage_uid: str, reason: str = "manual", run_arg_overrides=None) -> bool:
        """从指定阶段开始运行（包含该阶段及之后所有阶段）"""
        return self._run(
            workflow_id, RunMode.FROM_STAGE, stage_uid=stage_uid, reason=reason,
            run_arg_overrides=run_arg_overrides,
        )
    
    def retry_failed(self, workflow_id: int, reason: str = "retry") -> bool:
        """重试失败步骤"""
        return self._run(workflow_id, RunMode.RETRY_FAILED, reason=reason)

    def run(
        self,
        workflow_id: int,
        mode: RunMode,
        step_id: int = None,
        stage_uid: str = None,
        reason: str = "manual",
        allow_nested: bool = False,
        signal_policy: Optional["RunSignalPolicy"] = None,
        parent_run_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        run_arg_overrides=None,
    ) -> bool:
        """MA4: 公开执行入口

        CLI 与未来 headless 调用方应使用本方法替代私有 ``_run``，
        以便参数变更时 CLI/GUI 共享同一签名。
        """
        return self._run(
            workflow_id,
            mode,
            step_id=step_id,
            stage_uid=stage_uid,
            reason=reason,
            allow_nested=allow_nested,
            signal_policy=signal_policy,
            parent_run_id=parent_run_id,
            trace_id=trace_id,
            run_arg_overrides=run_arg_overrides,
        )
    
    def run_sub_workflow(
        self,
        workflow_id: int,
        reason: str = "sub_workflow",
        cancel_event: threading.Event = None,
    ) -> bool:
        """在当前运行上下文中执行子工作流，不重复触发顶层 UI 状态。"""
        with self._lock:
            parent_run_id = self._current_run_id
            trace_id = self._current_trace_id

        return self._run(
            workflow_id,
            RunMode.FULL,
            reason=reason,
            allow_nested=True,
            signal_policy=RunSignalPolicy(
                emit_run_signals=False,
                emit_step_signals=False,
                emit_progress_signals=False,
                emit_error_details=False,
                send_notification=False,  # 子工作流不发送通知，由父工作流统一通知
            ),
            parent_run_id=parent_run_id,
            trace_id=trace_id,
            external_cancel_event=cancel_event,
        )

    # ============== 运行编排（batch-4: 下沉到 engine_core.run_orchestration） ==============
    # 纯移动提取：方法体在 engine_core/run_orchestration.py，函数首参为 engine 实例；
    # 跨方法调用经 ``engine._xxx`` 动态分发，实例级 monkeypatch（测试替身）语义不变；
    # _running / _cancelled / _active_run_ids 等实例状态仍在本类上，移动代码直接属性读写。
    # 注意：get_workflow_by_id / get_steps_by_workflow / get_stage_order_map /
    # get_latest_run_history / get_step_logs_by_run / ensure_single_script_step /
    # list_stages / send_run_notification / _begin_run / _finalize_run /
    # _build_prev_step_status_map / _select_steps / _build_stage_meta /
    # _normalize_stage_uid / _build_stage_group_map / _describe_batch_mode /
    # _format_dry_run_lines / _cleanup_old_log_dirs / LOG_DIR /
    # WorkflowError / ConfigurationError / DependencyError 等顶层导入保留在本模块
    # （late-bound 契约），run_orchestration 在调用时从 engine 模块全局解析，
    # 保持 ``monkeypatch.setattr("engine.xxx", ...)`` 模块级补丁语义。

    def _is_run_cancelled(self, run_cancel_event: threading.Event = None) -> bool:
        """当前运行是否被请求取消（含嵌套子工作流局部取消事件）。"""
        return _run_orchestration.is_run_cancelled(self, run_cancel_event)

    def _resolve_final_status(self, status: str, run_cancel_event: threading.Event = None) -> str:
        return _run_orchestration.resolve_final_status(self, status, run_cancel_event)

    def _finalize_run_history(
        self,
        run_history_id: int | None,
        final_status: str,
        end_time: datetime,
        signal_policy: RunSignalPolicy,
    ) -> None:
        return _run_orchestration.finalize_run_history(
            self, run_history_id, final_status, end_time, signal_policy,
        )

    def _emit_run_completion(
        self,
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
        return _run_orchestration.emit_run_completion(
            self,
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

    def _restore_run_context(
        self,
        *,
        allow_nested: bool,
        run_history_id: int | None,
        prev_running: bool,
        prev_run_history_id: int | None,
        prev_run_id: str | None,
        prev_trace_id: str | None,
        prev_parent_run_id: str | None,
    ) -> None:
        return _run_orchestration.restore_run_context(
            self,
            allow_nested=allow_nested,
            run_history_id=run_history_id,
            prev_running=prev_running,
            prev_run_history_id=prev_run_history_id,
            prev_run_id=prev_run_id,
            prev_trace_id=prev_trace_id,
            prev_parent_run_id=prev_parent_run_id,
        )

    # ============== 核心执行逻辑 ==============

    def _run(
        self,
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
        """执行工作流（batch-4: 方法体下沉到 run_orchestration.run_workflow）

        Args:
            workflow_id: 工作流 ID
            mode: 运行模式
            step_id: 步骤 ID（用于 FROM_STEP 和 ONLY_STEP 模式）
            stage_uid: 阶段 UID（用于 FROM_STAGE 和 ONLY_STAGE 模式）
            reason: 运行原因
            run_arg_overrides: 本次运行临时参数覆盖，key=step.uid

        Returns:
            是否成功
        """
        return _run_orchestration.run_workflow(
            self,
            workflow_id,
            mode,
            step_id=step_id,
            stage_uid=stage_uid,
            reason=reason,
            allow_nested=allow_nested,
            signal_policy=signal_policy,
            parent_run_id=parent_run_id,
            trace_id=trace_id,
            external_cancel_event=external_cancel_event,
            run_arg_overrides=run_arg_overrides,
        )

    def _select_steps(
        self,
        all_steps: List[Step],
        mode: RunMode,
        step_id: int,
        workflow: Workflow,
        stage_uid: str = None,
    ) -> List[Step]:
        """根据运行模式选择步骤"""
        return _run_orchestration.select_steps(
            self, all_steps, mode, step_id, workflow, stage_uid=stage_uid,
        )

    def _get_single_script_step(self, workflow: Workflow) -> Optional[Step]:
        """获取或创建单脚本步骤"""
        return _run_orchestration.get_single_script_step(self, workflow)

    @staticmethod
    def compute_batches(
        workflow,
        steps: List[Step],
        stage_order_by_uid: Optional[Dict[str, int]] = None,
    ) -> List[List[Step]]:
        """计算步骤的分批执行计划（纯逻辑，不实际执行）
        
        Returns:
            按阶段分组的步骤批次列表
        """
        from engine_core.batch import compute_batches as _compute
        return _compute(workflow, steps, stage_order_by_uid)

    def dry_run(self, workflow_id: int):
        """预演模式：输出分批计划但不实际执行"""
        return _run_orchestration.dry_run(self, workflow_id)

    def _execute_steps(
        self,
        workflow: Workflow,
        steps: List[Step],
        run_history_id: int,
        log_dir: Path,
        signal_policy: RunSignalPolicy,
        run_cancel_event: threading.Event = None,
        run_arg_overrides=None,
        ) -> bool:
        """执行步骤（依赖分层 + 检查点 + 自动并行；batch-4 委托 run_orchestration）"""
        return _run_orchestration.execute_steps(
            self,
            workflow,
            steps,
            run_history_id,
            log_dir,
            signal_policy=signal_policy,
            run_cancel_event=run_cancel_event,
            run_arg_overrides=run_arg_overrides,
        )

    def _build_stage_meta(
        self,
        workflow_id: int,
        steps: List[Step],
        stage_order_by_uid: Dict[str, int],
    ) -> tuple[Dict[object, dict], List[object], Optional[str]]:
        """构建用途阶段元信息（用于日志展示）"""
        return _run_orchestration.build_stage_meta(
            self,
            workflow_id=workflow_id,
            steps=steps,
            stage_order_by_uid=stage_order_by_uid,
        )

    def _normalize_stage_uid(
        self,
        stage_uid: object,
        stage_meta: Dict[object, dict],
        ordered_stage_uids: List[object],
        unassigned_uid: Optional[str],
    ) -> object:
        """将未知/缺失 stage_uid 归一化为日志可展示的阶段 uid。"""
        return _run_orchestration.normalize_stage_uid(
            self, stage_uid, stage_meta, ordered_stage_uids, unassigned_uid,
        )

    def _append_failed_detail(self, failed_details: list[dict], step: Step, result: StepResult) -> None:
        return _run_orchestration.append_failed_detail(self, failed_details, step, result)

    def _emit_failed_details(self, failed_details: list[dict], signal_policy: RunSignalPolicy) -> None:
        return _run_orchestration.emit_failed_details(self, failed_details, signal_policy)

    def _update_execution_progress(self, completed_steps: int, total_steps: int, signal_policy: RunSignalPolicy) -> None:
        return _run_orchestration.update_execution_progress(self, completed_steps, total_steps, signal_policy)

    def _handle_batch_results(
        self,
        batch: list[Step],
        results: list[StepResult],
        failed_details: list[dict],
        signal_policy: RunSignalPolicy,
    ) -> bool:
        return _run_orchestration.handle_batch_results(
            self, batch, results, failed_details, signal_policy,
        )

    def _cleanup_old_logs_async(self, workflow: Workflow):
        """在后台线程执行日志清理，避免阻塞工作流启动"""
        return _run_orchestration.cleanup_old_logs_async(self, workflow)

    def _cleanup_old_logs(self, workflow: Workflow):
        """自动清理过期日志目录（batch-4 委托 run_orchestration，M1/L6 行为不变）"""
        return _run_orchestration.cleanup_old_logs(self, workflow)

    # ============== 单步执行（batch-3: 下沉到 engine_core.step_execution） ==============
    # 纯移动提取：方法体在 engine_core/step_execution.py，函数首参为 engine 实例；
    # 跨方法调用经 ``engine._xxx`` 动态分发，实例级 monkeypatch（测试替身）语义不变。
    # 注意：create_step_log / update_step_log / get_executor / cleanup_session /
    # has_non_retryable_policy / ErrorDiagnostician / format_duration_short /
    # _install_cancel_watcher / _run_steps_parallel / _should_skip_on_success /
    # _record_skip_on_success 等顶层导入保留在本模块（late-bound 契约），
    # step_execution 在调用时从 engine 模块全局解析，保持
    # ``monkeypatch.setattr("engine.xxx", ...)`` 模块级补丁语义。

    def _execute_skip_on_success_if_needed(
        self,
        step: Step,
        run_history_id: int,
        signal_policy: RunSignalPolicy,
        prev_step_status_map: Optional[dict] = None,
    ) -> Optional[StepResult]:
        """Return a skipped result when check_skip_on_success is already satisfied."""
        return _step_execution.execute_skip_on_success_if_needed(
            self,
            step,
            run_history_id,
            signal_policy,
            prev_step_status_map=prev_step_status_map,
        )

    def _begin_step_execution(
        self,
        step: Step,
        run_history_id: int,
        log_dir: Path,
    ) -> tuple[int, Path]:
        return _step_execution.begin_step_execution(self, step, run_history_id, log_dir)

    def _mark_step_running(
        self,
        step: Step,
        step_log_id: int,
        signal_policy: RunSignalPolicy,
    ) -> None:
        return _step_execution.mark_step_running(self, step, step_log_id, signal_policy)

    def _cancelled_step_result(
        self,
        step: Step,
        exec_result: Optional[ExecutorResult] = None,
        step_log_dir: Optional[Path] = None,
    ) -> StepResult:
        return _step_execution.cancelled_step_result(self, step, exec_result, step_log_dir)

    def _finish_cancelled_step(
        self,
        step: Step,
        step_log_id: int,
        signal_policy: RunSignalPolicy,
        exec_result: Optional[ExecutorResult] = None,
        step_log_dir: Optional[Path] = None,
    ) -> StepResult:
        return _step_execution.finish_cancelled_step(
            self,
            step,
            step_log_id,
            signal_policy,
            exec_result=exec_result,
            step_log_dir=step_log_dir,
        )

    def _wait_before_retry(
        self,
        step: Step,
        attempt: int,
        cancel_event: threading.Event,
    ) -> bool:
        return _step_execution.wait_before_retry(self, step, attempt, cancel_event)

    def _execute_step_attempt(
        self,
        workflow: Workflow,
        step: Step,
        executor,
        step_log_id: int,
        step_log_dir: Path,
        cancel_event: threading.Event,
        run_cancel_event: threading.Event,
        signal_policy: RunSignalPolicy,
        run_arg_overrides=None,
        ) -> tuple[Optional[StepResult], Optional[str]]:
        return _step_execution.execute_step_attempt(
            self,
            workflow=workflow,
            step=step,
            executor=executor,
            step_log_id=step_log_id,
            step_log_dir=step_log_dir,
            cancel_event=cancel_event,
            run_cancel_event=run_cancel_event,
            signal_policy=signal_policy,
            run_arg_overrides=run_arg_overrides,
        )

    @staticmethod
    def _is_non_retryable_executor_result(exec_result: ExecutorResult) -> bool:
        return _step_execution.is_non_retryable_executor_result(exec_result)

    def _build_failed_step_result(
        self,
        workflow: Workflow,
        step: Step,
        last_error: Optional[str],
        step_log_dir: Path,
    ) -> StepResult:
        return _step_execution.build_failed_step_result(
            self,
            workflow,
            step,
            last_error,
            step_log_dir,
        )

    def _build_unexpected_step_failure(
        self,
        step: Step,
        error: Exception,
        step_log_dir: Path,
    ) -> StepResult:
        return _step_execution.build_unexpected_step_failure(self, step, error, step_log_dir)

    def _finish_failed_step_after_unexpected_error(
        self,
        step: Step,
        step_log_id: int,
        result: StepResult,
        signal_policy: RunSignalPolicy,
    ) -> None:
        return _step_execution.finish_failed_step_after_unexpected_error(
            self,
            step,
            step_log_id,
            result,
            signal_policy,
        )

    def _stop_cancel_watcher(self, cancel_watcher, step: Step) -> None:
        return _step_execution.stop_cancel_watcher(self, cancel_watcher, step)

    def _execute_step_with_retries(
        self,
        workflow: Workflow,
        step: Step,
        executor,
        step_log_id: int,
        step_log_dir: Path,
        signal_policy: RunSignalPolicy,
        run_cancel_event: threading.Event = None,
        run_arg_overrides=None,
        ) -> StepResult:
        return _step_execution.execute_step_with_retries(
            self,
            workflow=workflow,
            step=step,
            executor=executor,
            step_log_id=step_log_id,
            step_log_dir=step_log_dir,
            signal_policy=signal_policy,
            run_cancel_event=run_cancel_event,
            run_arg_overrides=run_arg_overrides,
        )

    def _execute_single_step(
        self,
        workflow: Workflow,
        step: Step,
        run_history_id: int,
        log_dir: Path,
        signal_policy: RunSignalPolicy,
        prev_step_status_map: Optional[dict] = None,
        run_cancel_event: threading.Event = None,
        run_arg_overrides=None,
        ) -> StepResult:
        """执行单个步骤（带重试）"""
        return _step_execution.execute_single_step(
            self,
            workflow,
            step,
            run_history_id,
            log_dir,
            signal_policy,
            prev_step_status_map=prev_step_status_map,
            run_cancel_event=run_cancel_event,
            run_arg_overrides=run_arg_overrides,
        )

    def _execute_parallel_steps(
        self,
        workflow: Workflow,
        steps: List[Step],
        run_history_id: int,
        log_dir: Path,
        signal_policy: RunSignalPolicy,
        prev_step_status_map: Optional[dict] = None,
        run_cancel_event: threading.Event = None,
        run_arg_overrides=None,
        ) -> List[StepResult]:
        """并行执行多个步骤（Fan-Out/Fan-In 模式；batch-3 委托 engine_core.step_execution）"""
        return _step_execution.execute_parallel_steps(
            self,
            workflow,
            steps,
            run_history_id,
            log_dir,
            signal_policy,
            prev_step_status_map=prev_step_status_map,
            run_cancel_event=run_cancel_event,
            run_arg_overrides=run_arg_overrides,
        )

    def _finish_step(
        self,
        step: Step,
        step_log_id: int,
        result: StepResult,
        exec_result: ExecutorResult = None,
        signal_policy: Optional[RunSignalPolicy] = None,
    ):
        """完成步骤处理"""
        return _step_execution.finish_step(
            self,
            step,
            step_log_id,
            result,
            exec_result,
            signal_policy,
        )
