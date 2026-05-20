# -*- coding: utf-8 -*-
"""工作流编排引擎

基于 workflow-orchestration-patterns 和 error-handling-patterns 技能实现：
- Fan-Out/Fan-In 并行执行
- 自定义异常层次结构
- 重试与指数退避
- 优雅降级
"""

import logging
import shutil
import time
import threading
import os
import traceback

logger = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any

# CA2: 监听子系统已抽到 engine_core.watcher；本模块仅做薄封装
from engine_core.watcher import (
    FileWatcher,
    validate_watch_folders as _validate_watch_folders,
)
from engine_core.notification import send_run_notification
from engine_core.lifecycle import (
    begin_run as _begin_run,
    finalize_run as _finalize_run,
    create_running_step_log as _create_running_step_log,
    check_skip_on_success as _check_skip_on_success,
    should_skip_on_success as _should_skip_on_success,
    record_skip_on_success as _record_skip_on_success,
    build_prev_step_status_map as _build_prev_step_status_map,
)
from engine_core.scheduler import run_steps_parallel as _run_steps_parallel
from engine_core.cancel import install_cancel_watcher as _install_cancel_watcher
from watch_rules import detect_watch_output_conflicts

from PySide6.QtCore import QObject, Signal, Slot

from config import LOG_DIR
from database import (
    get_session, get_workflow_by_id, get_steps_by_workflow,
    create_run_history, update_run_history,
    create_step_log, update_step_log,
    get_latest_run_history, get_step_logs_by_run,
    ensure_single_script_step, get_stage_order_map, list_stages,
    cleanup_session,
)
from models import Workflow, Step, RunHistory, StepLog
from executors import get_executor, ExecutorResult
from notifier import send_workflow_notification
from database import get_webhook_by_id
from diagnostics import ErrorDiagnostician
from duration_utils import format_duration_short
from exceptions import (
    WorkflowError, ConfigurationError, ExecutionError,
    DependencyError, WorkflowTimeoutError,
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
        self._watcher = FileWatcher(
            log_cb=self._emit_log,
            trigger_cb=lambda wf_id, reason: self.run_all(wf_id, reason=reason),
            is_running_cb=lambda: self.is_running,
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
        # 1) 如果引擎正在运行且该 run_history_id 在嵌套栈中，走正常 cancel
        with self._lock:
            if self._running and run_history_id in self._active_run_ids:
                self._cancelled = True
                self._emit_log(f"已发送停止信号给当前运行 (run_history_id={run_history_id})")
                return
            # R4-#6: 闭合竞态窗口——_running 已置位但 _active_run_ids.add 尚未完成的时刻，
            # 若直接走路径 2 写 DB 会被后续 finalize 覆盖，且引擎不会真正停止。
            # 仍是引擎正在运行（不论是不是这个 run_history_id），先把 _cancelled 置位，
            # 让引擎自身去 finalize 该运行；UI 上用户感知到的就是"已请求停止"。
            if self._running:
                self._cancelled = True
                self._emit_log(
                    f"引擎正在启动/运行中，已发送停止信号 (run_history_id={run_history_id})"
                )
                return

        # 2) 否则直接在数据库中标记为 cancelled（孤儿记录）
        now = datetime.now()
        try:
            # R3-#2: 写 cancelled 前先检查当前状态——若已是 success/failure/cancelled 终态，
            # 说明正常 finalize 已完成，不再覆盖；只清理可能残留的孤儿 step_logs。
            from database import get_session
            from models import RunHistory as _RH
            existing_status = None
            try:
                with get_session() as s:
                    row = s.query(_RH.status).filter(_RH.id == run_history_id).first()
                    if row:
                        existing_status = row[0]
            except Exception as e:
                logger.warning("读取 run_history 状态失败: %s", e)
            if existing_status in ("success", "failure", "cancelled"):
                self._emit_log(
                    f"运行 {run_history_id} 已是终态 {existing_status}，跳过强制取消"
                )
                # R4-#9: 批量取消残留 pending/running 的 step_logs（一次 UPDATE）
                # R5-#7: 受影响行数为 0 时不输出"已清理"误导日志
                try:
                    from database import cancel_pending_step_logs
                    affected = cancel_pending_step_logs(
                        run_history_id, "父运行已终态，孤儿步骤被清理"
                    )
                    if affected:
                        self._emit_log(
                            f"清理 {affected} 个孤儿步骤（run_history_id={run_history_id}）"
                        )
                except Exception as e:
                    logger.warning("批量清理孤儿步骤失败: %s", e)
                return
            # R5-#3: 先批量取消 step_logs，再写 run_history 终态。
            # update_run_history 终态时会 wal_checkpoint，能一次性把 step_logs 一起落主库，
            # 避免跨进程读到 "run cancelled 但 step pending" 的窗口。
            try:
                from database import cancel_pending_step_logs
                cancel_pending_step_logs(run_history_id, "用户强制停止")
            except Exception as e:
                logger.warning("批量取消 step_logs 失败: %s", e)
            update_run_history(
                run_history_id,
                status=RunStatus.CANCELLED.value,
                end_time=now,
            )
            self._emit_log(f"已强制停止运行记录 (run_history_id={run_history_id})")
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
        send_run_notification(
            workflow,
            run_id=run_id,
            status=status,
            log_dir=log_dir,
            reason=reason,
            start_time=start_time,
            end_time=end_time,
            log_cb=self._emit_log,
        )

    # ============== 监听触发 ==============

    def start_watch(self, workflow: Workflow) -> bool:
        """启动文件监听（委托给 FileWatcher）

        R2-#4: 启停信号在状态切换时发出，UI 据此更新持续指示灯。
        幂等：若当前已对同 workflow + 同 folders 启动监听，则跳过 stop+restart 抖动。
        """
        # R2-#4 / R4-#1 / R4-#10 / R5-#2 幂等：避免点同一 workflow 多次造成监听抖动
        # 目录顺序变化不视为目标变化；但 cooldown/settle/mode 任一改变都视为需重启
        prev_workflow_id = getattr(self._watcher, "_workflow_id", None)
        prev_folders = list(getattr(self._watcher, "_folders", []) or [])
        prev_cooldown = int(getattr(self._watcher, "_cooldown", 0) or 0)
        prev_settle = int(getattr(self._watcher, "_settle", 0) or 0)
        prev_mode = str(getattr(self._watcher, "_mode", "") or "")
        new_folders = list(workflow.get_watch_folders() or [])
        # R6-#5: DB 中若存在脏数据（字符串/None/异常类型）也兜底为默认值
        def _safe_int(value, default: int, minimum: int = 0) -> int:
            try:
                v = int(value) if value is not None else default
            except (TypeError, ValueError):
                v = default
            return max(minimum, v)
        new_cooldown = _safe_int(workflow.cooldown_seconds, default=8, minimum=1)
        new_settle = _safe_int(workflow.settle_seconds, default=15, minimum=0)
        new_mode = workflow.watch_mode or "any_change"
        if (
            workflow.watch_enabled
            and prev_workflow_id == workflow.id
            and sorted(prev_folders) == sorted(new_folders)
            and prev_cooldown == new_cooldown
            and prev_settle == new_settle
            and prev_mode == new_mode
            and getattr(self._watcher, "_thread", None) is not None
        ):
            return True  # 已在监听同样目标 + 同样参数，无需重启

        # R4-#1: stop_watch 内部已发 watch_stopped；不再重复 emit，避免指示器抖动
        self.stop_watch()

        if not workflow.watch_enabled:
            return False
        if not new_folders:
            return False
        try:
            folders = _validate_watch_folders(new_folders)
        except ValueError as e:
            self._emit_log(f"监听未启动: {e}")
            return False
        conflicts = detect_watch_output_conflicts(
            folders,
            get_steps_by_workflow(workflow.id),
        )
        if conflicts:
            joined = "；".join(conflicts)
            self._emit_log(f"监听未启动: 监听目录与工作流输出目录重叠：{joined}")
            return False
        ok = self._watcher.start(
            workflow_id=workflow.id,
            folders=folders,
            cooldown=new_cooldown,
            settle=new_settle,
            mode=new_mode,
        )
        if ok:
            try:
                self.watch_started.emit(workflow.id, folders)
            except Exception:
                pass
        return ok

    def stop_watch(self, join_timeout: float = 1.0):
        """停止文件监听（委托给 FileWatcher）"""
        was_watching = getattr(self._watcher, "_thread", None) is not None
        prev_workflow_id = getattr(self._watcher, "_workflow_id", None)
        self._watcher.stop(join_timeout)
        if was_watching:
            try:
                self.watch_stopped.emit(prev_workflow_id or 0)
            except Exception:
                pass

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
    
    def run_all(self, workflow_id: int, reason: str = "manual") -> bool:
        """全流程运行"""
        return self._run(workflow_id, RunMode.FULL, reason=reason)
    
    def run_from(self, workflow_id: int, from_step_id: int, reason: str = "manual") -> bool:
        """从指定步骤开始运行"""
        return self._run(workflow_id, RunMode.FROM_STEP, step_id=from_step_id, reason=reason)
    
    def run_only(self, workflow_id: int, step_id: int, reason: str = "manual") -> bool:
        """只运行指定步骤"""
        return self._run(workflow_id, RunMode.ONLY_STEP, step_id=step_id, reason=reason)
    
    def run_stage(self, workflow_id: int, stage_uid: str, reason: str = "manual") -> bool:
        """只运行指定阶段"""
        return self._run(workflow_id, RunMode.ONLY_STAGE, stage_uid=stage_uid, reason=reason)
    
    def run_from_stage(self, workflow_id: int, stage_uid: str, reason: str = "manual") -> bool:
        """从指定阶段开始运行（包含该阶段及之后所有阶段）"""
        return self._run(workflow_id, RunMode.FROM_STAGE, stage_uid=stage_uid, reason=reason)
    
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

    def _is_run_cancelled(self, run_cancel_event: threading.Event = None) -> bool:
        """当前运行是否被请求取消。

        ``run_cancel_event`` 用于嵌套子工作流这类局部取消场景：
        不污染引擎级 ``self._cancelled``，但可让当前 run 及其步骤尽快收尾。
        """
        return self.is_cancelled or bool(run_cancel_event and run_cancel_event.is_set())

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
    ) -> bool:
        """执行工作流
        
        Args:
            workflow_id: 工作流 ID
            mode: 运行模式
            step_id: 步骤 ID（用于 FROM_STEP 和 ONLY_STEP 模式）
            stage_uid: 阶段 UID（用于 FROM_STAGE 和 ONLY_STAGE 模式）
            reason: 运行原因
            
        Returns:
            是否成功
        """
        run_history_id = None
        run_id = None
        log_dir = None
        started_emitted = False
        start_time = None
        end_time = None
        signal_policy = signal_policy or RunSignalPolicy()
        status = RunStatus.FAILURE.value
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
        with self._lock:
            if self._running and not allow_nested:
                self._emit_log("错误：已有工作流正在运行")
                return False
            prev_running = self._running
            prev_run_history_id = self._current_run_history_id
            prev_run_id = self._current_run_id
            prev_trace_id = self._current_trace_id
            prev_parent_run_id = self._current_parent_run_id
            if not allow_nested:
                # 只有 outermost 改 _running——nested 共享 outer 的 True，无需再写
                self._running = True
            if not prev_running:
                self._cancelled = False
            effective_trace_id = trace_id if trace_id is not None else self._current_trace_id
            effective_parent_run_id = parent_run_id if parent_run_id is not None else self._current_parent_run_id
            start_time = datetime.now()

        try:
            # 获取工作流
            workflow = get_workflow_by_id(workflow_id)
            if not workflow:
                raise ConfigurationError(f"工作流不存在: {workflow_id}")
            
            # 自动清理过期日志（后台线程执行，避免阻塞启动）
            self._cleanup_old_logs_async(workflow)
            
            # 获取步骤
            all_steps = get_steps_by_workflow(workflow_id)
            if not all_steps:
                raise ConfigurationError("工作流没有步骤")
            
            # 根据模式筛选步骤
            steps = self._select_steps(all_steps, mode, step_id, workflow, stage_uid=stage_uid)
            if not steps:
                self._emit_log("没有需要执行的步骤")
                return True
            
            # CA2: 创建 RunHistory + log_dir + 状态切 running，整体下沉到 lifecycle 模块
            ctx = _begin_run(
                workflow=workflow,
                mode_value=mode.value,
                run_mode_param=str(step_id) if step_id else None,
                reason=reason,
                trace_id=effective_trace_id,
                parent_run_id=effective_parent_run_id,
                start_time=start_time,
                running_status_value=RunStatus.RUNNING.value,
            )
            run_history_id = ctx.run_history_id
            run_id = ctx.run_id
            log_dir = ctx.log_dir
            # #2: 仅 outermost 把上下文写入实例属性。nested run（含并行 sub_workflow）
            # 不修改 instance attrs，靠 local run_id / trace_id 即可；UI/外部读到的始终是 outer。
            with self._lock:
                if not allow_nested:
                    self._current_trace_id = ctx.trace_id
                    self._current_parent_run_id = ctx.parent_run_id
                    self._current_run_history_id = run_history_id
                    self._current_run_id = run_id
                # 修复 H1/H12：所有 run（包括 nested）的 history_id 都加入栈，用于 force_stop 命中
                self._active_run_ids.add(run_history_id)

            if signal_policy.emit_run_signals:
                self.workflow_started.emit(workflow_id, run_id)
                started_emitted = True
            self._emit_log(f"开始运行工作流: {workflow.name}")
            self._emit_log(f"运行模式: {mode.value}")
            self._emit_log(f"日志目录: {log_dir}")
            
            # 执行步骤
            success = self._execute_steps(
                workflow,
                steps,
                run_history_id,
                log_dir,
                signal_policy=signal_policy,
                run_cancel_event=external_cancel_event,
            )
            
            # 更新运行结果
            if self._is_run_cancelled(external_cancel_event):
                status = RunStatus.CANCELLED.value
            else:
                status = RunStatus.SUCCESS.value if success else RunStatus.FAILURE.value
            
            return success
            
        except WorkflowError as e:
            self._emit_log(f"错误: {e}")
            return False
        except Exception as e:
            logger.exception("未知错误: %s", e)
            self._emit_log(f"未知错误: {e}")
            self._emit_log(traceback.format_exc())
            return False
        finally:
            end_time = datetime.now()

            # 运行结果落库 + 通知 + UI 解锁，必须在任何分支都「收尾」
            try:
                if run_history_id:
                    # cancelled 优先，否则按 success/failure
                    final_status = (
                        RunStatus.CANCELLED.value
                        if self._is_run_cancelled(external_cancel_event)
                        else status
                    )
                    # CA2: 委托给 lifecycle.finalize_run（已内置 try/except + str/truncate）
                    if not _finalize_run(
                        run_history_id,
                        status_value=final_status,
                        end_time=end_time,
                    ):
                        # #8: finalize 失败意味着 DB 锁死 / 磁盘满；显眼上抛 + 通过 error_details 通道告知 UI
                        self._emit_log(f"严重警告：运行历史落库失败 run_history_id={run_history_id}，UI 状态可能停留在 running")
                        if signal_policy.emit_error_details:
                            try:
                                self.error_details.emit([
                                    {"step": "运行收尾", "error": "运行历史更新失败（DB 锁死或磁盘满）"}
                                ])
                            except Exception:
                                pass
            except Exception as e:
                # 落库失败不应阻断 UI 收尾
                logger.warning("更新运行历史失败: %s", e)
                self._emit_log("警告：更新运行历史失败")
                self._emit_log(traceback.format_exc())

            try:
                if started_emitted and run_id:
                    final_status = (
                        RunStatus.CANCELLED.value
                        if self._is_run_cancelled(external_cancel_event)
                        else status
                    )
                    if signal_policy.emit_run_signals:
                        self.workflow_finished.emit(workflow_id, run_id, final_status)
                    if final_status == RunStatus.SUCCESS.value:
                        self._emit_log("工作流运行成功")
                    elif final_status == RunStatus.CANCELLED.value:
                        self._emit_log("工作流已取消")
                    else:
                        self._emit_log("工作流运行失败")

                    # 修复 H7：钉钉通知改为异步发送，避免阻塞主运行线程 10 秒
                    if workflow and log_dir and signal_policy.send_notification:
                        try:
                            self._executor.submit(
                                self._send_notification,
                                workflow=workflow,
                                run_id=run_id,
                                status=final_status,
                                log_dir=str(log_dir),
                                reason=reason,
                                start_time=start_time,
                                end_time=end_time,
                            )
                        except Exception as e:
                            logger.warning("提交通知任务失败: %s", e)
            except Exception as e:
                logger.warning("运行收尾处理失败: %s", e)
                self._emit_log("警告：运行收尾处理失败")
                self._emit_log(traceback.format_exc())

            with self._lock:
                # #2: 仅 outermost 还原实例属性。nested 没改过，无需还原（也避免覆盖兄弟 nested run 的状态）
                if not allow_nested:
                    self._running = prev_running
                    self._current_run_history_id = prev_run_history_id
                    self._current_run_id = prev_run_id
                    self._current_trace_id = prev_trace_id
                    self._current_parent_run_id = prev_parent_run_id
                # 修复 H1/H12：本次 run_history_id 出栈
                if run_history_id is not None:
                    self._active_run_ids.discard(run_history_id)
                # 仅最外层出栈时复位取消标志
                if not self._running:
                    self._cancelled = False
    
    def _select_steps(
        self,
        all_steps: List[Step],
        mode: RunMode,
        step_id: int,
        workflow: Workflow,
        stage_uid: str = None,
    ) -> List[Step]:
        """根据运行模式选择步骤"""
        if workflow.single_script_enabled:
            step = self._get_single_script_step(workflow)
            if not step:
                raise ConfigurationError("单脚本模式未配置脚本路径")
            if mode in (RunMode.FULL, RunMode.RETRY_FAILED, RunMode.ONLY_STAGE, RunMode.FROM_STAGE):
                return [step]
            if mode in (RunMode.FROM_STEP, RunMode.ONLY_STEP):
                if step.id == step_id:
                    return [step]
                raise ConfigurationError("单脚本模式仅支持运行单脚本步骤")
        
        if mode == RunMode.FULL:
            return all_steps
        
        elif mode == RunMode.FROM_STEP:
            # 从指定步骤开始
            found = False
            result = []
            for step in all_steps:
                if step.id == step_id:
                    found = True
                if found:
                    result.append(step)
            if not result:
                raise ConfigurationError(f"未找到步骤: {step_id}")
            return result
        
        elif mode == RunMode.ONLY_STEP:
            # 只运行指定步骤
            for step in all_steps:
                if step.id == step_id:
                    return [step]
            raise ConfigurationError(f"未找到步骤: {step_id}")
        
        elif mode == RunMode.ONLY_STAGE:
            # 只运行指定阶段内的步骤
            if not stage_uid:
                raise ConfigurationError("ONLY_STAGE 模式需要指定 stage_uid")
            stage_steps = [s for s in all_steps if getattr(s, "stage_uid", None) == stage_uid]
            if not stage_steps:
                raise ConfigurationError(f"阶段 {stage_uid} 中没有步骤")
            return stage_steps
        
        elif mode == RunMode.FROM_STAGE:
            # 从指定阶段开始（包含该阶段及之后所有阶段的步骤）
            if not stage_uid:
                raise ConfigurationError("FROM_STAGE 模式需要指定 stage_uid")
            stage_map = get_stage_order_map(workflow.id)
            target_order = stage_map.get(stage_uid)
            if target_order is None:
                raise ConfigurationError(f"未找到阶段: {stage_uid}")
            # 收集目标阶段及之后所有阶段的步骤
            result = []
            for step in all_steps:
                step_stage_uid = getattr(step, "stage_uid", None)
                step_order = stage_map.get(step_stage_uid, 0)
                if step_order >= target_order:
                    result.append(step)
            if not result:
                raise ConfigurationError(f"阶段 {stage_uid} 及之后没有步骤")
            return result
        
        elif mode == RunMode.RETRY_FAILED:
            # 重试失败步骤
            latest_run = get_latest_run_history(
                workflow.id,
                exclude_statuses=[RunStatus.RUNNING.value, RunStatus.PENDING.value],
                only_finished=True,
            )
            if not latest_run:
                raise ConfigurationError("没有历史运行记录")

            step_logs = get_step_logs_by_run(latest_run.id)
            failed_step_ids = {
                log.step_id for log in step_logs
                if log.status == "failure"
            }
            
            if not failed_step_ids:
                self._emit_log("上次运行没有失败的步骤")
                return []
            
            return [s for s in all_steps if s.id in failed_step_ids]
        
        return all_steps

    def _get_single_script_step(self, workflow: Workflow) -> Optional[Step]:
        """获取或创建单脚本步骤"""
        steps = get_steps_by_workflow(workflow.id)
        for step in steps:
            if step.uid == "single_script":
                return step
        if workflow.single_script_path:
            ensure_single_script_step(
                workflow.id,
                step_type=workflow.single_script_type,
                script_path=workflow.single_script_path,
                args=workflow.get_single_args(),
                cwd=workflow.single_script_cwd
            )
            steps = get_steps_by_workflow(workflow.id)
            for step in steps:
                if step.uid == "single_script":
                    return step
        return None
    
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
        workflow = get_workflow_by_id(workflow_id)
        if not workflow:
            self._emit_log("错误：工作流不存在")
            return
        all_steps = get_steps_by_workflow(workflow_id)
        if not all_steps:
            self._emit_log("工作流没有步骤")
            return
        try:
            stage_map = get_stage_order_map(workflow_id)
            batches = self.compute_batches(workflow, all_steps, stage_map)
        except DependencyError as e:
            self._emit_log(f"[预演] 依赖错误: {e}")
            return
        
        stage_meta, ordered_stage_uids, unassigned_uid = self._build_stage_meta(
            workflow_id=workflow_id,
            steps=all_steps,
            stage_order_by_uid=stage_map,
        )

        # 执行组按用途阶段分组（stage barrier 下理论上不会跨阶段，但仍做防御）
        stage_uid_to_groups: Dict[object, List[List[Step]]] = {uid: [] for uid in ordered_stage_uids}
        for group in batches:
            raw_uid = getattr(group[0], "stage_uid", None) if group else None
            uid = self._normalize_stage_uid(raw_uid, stage_meta, ordered_stage_uids, unassigned_uid)
            stage_uid_to_groups.setdefault(uid, []).append(group)

        self._emit_log("═" * 40)
        self._emit_log("[预演] 按阶段执行预览：")

        shown_stages = 0
        for uid in ordered_stage_uids:
            meta = stage_meta.get(uid)
            if not meta or meta["step_count"] <= 0:
                continue
            groups = stage_uid_to_groups.get(uid, [])
            if not groups:
                continue

            shown_stages += 1
            self._emit_log(f"阶段 S{meta['index']} {meta['name']} · {meta['step_count']}步")

            if len(groups) == 1:
                group = groups[0]
                names = ", ".join(s.name for s in group)
                mode = "并行" if len(group) > 1 else ("前置(Gate)" if group[0].is_gate else "串行")
                self._emit_log(f"  {mode}：{names}")
            else:
                total = len(groups)
                for i, group in enumerate(groups, 1):
                    names = ", ".join(s.name for s in group)
                    mode = "并行" if len(group) > 1 else ("前置(Gate)" if group[0].is_gate else "串行")
                    self._emit_log(f"执行组 {i}/{total}（{mode}）：{names}")

        self._emit_log(
            f"共 {shown_stages} 个阶段，{len(batches)} 个执行组，{sum(len(b) for b in batches)} 个步骤"
        )
        self._emit_log("═" * 40)

    def _execute_steps(
        self,
        workflow: Workflow,
        steps: List[Step],
        run_history_id: int,
        log_dir: Path,
        signal_policy: RunSignalPolicy,
        run_cancel_event: threading.Event = None,
    ) -> bool:
        """执行步骤

        依赖与并行规则：
        - 依赖（depends_on）必须先完成
        - Gate 步骤（is_gate=True）优先单独执行
        - 自动并行：仅需 workflow.parallel_enabled=True，同依赖层步骤默认并行
        """
        total_steps = len(steps)
        completed_steps = 0
        failed_details = []  # 收集失败步骤摘要

        # R2-#1: 预取改为 local 变量，避免父子 sub_workflow 共享 self 属性互相覆盖
        # 沿调用链把 prev_step_status_map 传给 _execute_single_step / _execute_parallel_steps
        try:
            prev_step_status_map = _build_prev_step_status_map(
                workflow.id,
                exclude_run_history_id=run_history_id,
                running_status_value=RunStatus.RUNNING.value,
                pending_status_value=RunStatus.PENDING.value,
            )
        except Exception as e:
            logger.warning("预取上次步骤状态失败，回退按步查询: %s", e)
            prev_step_status_map = None

        stage_map = get_stage_order_map(workflow.id)
        batches = self.compute_batches(workflow, steps, stage_map)

        stage_meta, ordered_stage_uids, unassigned_uid = self._build_stage_meta(
            workflow_id=workflow.id,
            steps=steps,
            stage_order_by_uid=stage_map,
        )

        stage_uid_to_group_total: Dict[object, int] = {}
        for group in batches:
            if not group:
                continue
            raw_uid = getattr(group[0], "stage_uid", None)
            uid = self._normalize_stage_uid(raw_uid, stage_meta, ordered_stage_uids, unassigned_uid)
            stage_uid_to_group_total[uid] = stage_uid_to_group_total.get(uid, 0) + 1

        stage_uid_to_group_index: Dict[object, int] = {uid: 0 for uid in stage_uid_to_group_total.keys()}
        current_stage_uid = None

        for batch in batches:
            if self._is_run_cancelled(run_cancel_event):
                self._emit_log(f"运行已取消（已完成 {completed_steps}/{total_steps}）")
                if failed_details and signal_policy.emit_error_details:
                    self.error_details.emit(failed_details)
                return False

            # 阶段标题（阶段变化时打印一次）
            if batch:
                raw_uid = getattr(batch[0], "stage_uid", None)
            else:
                raw_uid = None
            stage_uid = self._normalize_stage_uid(raw_uid, stage_meta, ordered_stage_uids, unassigned_uid)
            if stage_uid != current_stage_uid and stage_uid in stage_meta:
                meta = stage_meta[stage_uid]
                self._emit_log(f"══ 阶段 S{meta['index']} {meta['name']}（{meta['step_count']}步）══")
                current_stage_uid = stage_uid

            # 执行组提示（仅当该阶段存在多个执行组时显示）
            if batch and stage_uid in stage_uid_to_group_total:
                group_total = stage_uid_to_group_total.get(stage_uid, 1)
                names = ", ".join(s.name for s in batch)
                mode = "并行" if len(batch) > 1 else ("前置(Gate)" if batch[0].is_gate else "串行")
                if group_total > 1:
                    stage_uid_to_group_index[stage_uid] = stage_uid_to_group_index.get(stage_uid, 0) + 1
                    idx = stage_uid_to_group_index[stage_uid]
                    self._emit_log(f"执行组 {idx}/{group_total}（{mode}）：{names}")
                else:
                    self._emit_log(f"  {mode}：{names}")

            # 执行步骤
            if len(batch) == 1:
                step = batch[0]
                result = self._execute_single_step(
                    workflow, step, run_history_id, log_dir, signal_policy,
                    prev_step_status_map=prev_step_status_map,
                    run_cancel_event=run_cancel_event,
                )
                completed_steps += 1
                if signal_policy.emit_progress_signals:
                    self.progress_updated.emit(completed_steps, total_steps)

                # 取消状态：直接退出，不当作失败
                if result.status == "cancelled":
                    return False

                if not result.success:
                    failed_details.append({
                        "step_id": step.id,
                        "step_name": step.name,
                        "error_message": result.error_message or "未知错误",
                        "suggested_fix": result.suggested_fix or ""
                    })
                    if signal_policy.emit_error_details:
                        self.error_details.emit(failed_details)
                    return False
            else:
                results = self._execute_parallel_steps(
                    workflow, batch, run_history_id, log_dir, signal_policy,
                    prev_step_status_map=prev_step_status_map,
                    run_cancel_event=run_cancel_event,
                )
                completed_steps += len(batch)
                if signal_policy.emit_progress_signals:
                    self.progress_updated.emit(completed_steps, total_steps)

                has_failure = False
                has_cancelled = False
                for step, result in zip(batch, results):
                    if result.status == "cancelled":
                        has_cancelled = True
                        break
                    if not result.success:
                        has_failure = True
                        failed_details.append({
                            "step_id": step.id,
                            "step_name": step.name,
                            "error_message": result.error_message or "未知错误",
                            "suggested_fix": result.suggested_fix or ""
                        })

                if has_cancelled:
                    # M3 修复：取消之前若已收集到失败摘要，先 emit 再返回
                    if failed_details and signal_policy.emit_error_details:
                        self.error_details.emit(failed_details)
                    return False
                if has_failure:
                    if signal_policy.emit_error_details:
                        self.error_details.emit(failed_details)
                    return False
        
        return True

    def _build_stage_meta(
        self,
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
        stage_names: Dict[object, str] = {}
        try:
            stages = list_stages(workflow_id)
            stage_names.update({s.uid: s.name for s in stages})
        except Exception as e:
            logger.warning("获取阶段列表失败: %s", e)
            stages = []

        ordered_uids: List[object] = [uid for uid, _ in sorted(stage_order_by_uid.items(), key=lambda kv: kv[1])]
        max_order = max(stage_order_by_uid.values(), default=-1)

        # 汇总 steps 中出现但不在 stage_map 的 stage_uid（或 None）→ 归入「未归类」
        missing = False
        for s in steps:
            suid = getattr(s, "stage_uid", None)
            if not suid or suid not in stage_order_by_uid:
                missing = True
                break

        unassigned_uid = "__unassigned__" if missing else None
        if unassigned_uid:
            if unassigned_uid not in ordered_uids:
                ordered_uids.append(unassigned_uid)
            stage_names.setdefault(unassigned_uid, "未归类")
            stage_order_by_uid = dict(stage_order_by_uid)
            stage_order_by_uid[unassigned_uid] = max_order + 1

        # 统计每个 stage 的步骤数
        step_count_by_uid: Dict[object, int] = {uid: 0 for uid in ordered_uids}
        for s in steps:
            suid = getattr(s, "stage_uid", None)
            uid = suid if suid in step_count_by_uid else (unassigned_uid or suid)
            if uid in step_count_by_uid:
                step_count_by_uid[uid] += 1

        # 构建元信息：按 order 排序决定 S 序号
        ordered_uids = [uid for uid, _ in sorted({uid: stage_order_by_uid.get(uid, 10**9) for uid in ordered_uids}.items(), key=lambda kv: kv[1])]
        stage_meta: Dict[object, dict] = {}
        idx = 0
        for uid in ordered_uids:
            # 只给「存在步骤」的阶段编号，避免空阶段把序号冲散
            if step_count_by_uid.get(uid, 0) <= 0:
                continue
            idx += 1
            stage_meta[uid] = {
                "index": idx,
                "name": stage_names.get(uid, "阶段"),
                "order": stage_order_by_uid.get(uid, idx - 1),
                "step_count": step_count_by_uid.get(uid, 0),
            }

        # ordered_stage_uids：仅输出有步骤的阶段（与日志一致）
        ordered_stage_uids = [uid for uid in ordered_uids if uid in stage_meta]
        return stage_meta, ordered_stage_uids, unassigned_uid

    def _normalize_stage_uid(
        self,
        stage_uid: object,
        stage_meta: Dict[object, dict],
        ordered_stage_uids: List[object],
        unassigned_uid: Optional[str],
    ) -> object:
        """将未知/缺失 stage_uid 归一化为日志可展示的阶段 uid。"""
        if stage_uid in stage_meta:
            return stage_uid
        if unassigned_uid and unassigned_uid in stage_meta:
            return unassigned_uid
        # 回退：使用最后一个可展示阶段
        if ordered_stage_uids:
            return ordered_stage_uids[-1]
        return stage_uid

    def _cleanup_old_logs_async(self, workflow: Workflow):
        """在后台线程执行日志清理，避免阻塞工作流启动"""
        def cleanup():
            try:
                self._cleanup_old_logs(workflow)
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

        thread = threading.Thread(target=cleanup, daemon=True)
        thread.start()

    def _cleanup_old_logs(self, workflow: Workflow):
        """自动清理过期日志目录

        M1 修复：使用严格正则匹配日志目录名（YYYYMMDD_HHMMSS 或带 _xxxx 后缀），
        避免共享前缀但非日志目录被误删。
        L6 修复：跳过仍处于 running 状态的 RunHistory 引用的目录，
        防止用户回拨系统时间后误删当前正在写入的日志目录。
        """
        import re
        log_dir_pattern = re.compile(r"^\d{8}_\d{6}(?:_[0-9a-fA-F]{4,8})?$")
        try:
            retention_days = getattr(workflow, 'log_retention_days', 30) or 30
            wf_log_dir = LOG_DIR / workflow.uid
            if not wf_log_dir.exists():
                return
            cutoff = datetime.now() - timedelta(days=retention_days)
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
            removed = 0
            for sub in sorted(wf_log_dir.iterdir()):
                if not sub.is_dir():
                    continue
                if not log_dir_pattern.match(sub.name):
                    continue
                if sub.name in active_dir_names:
                    continue  # L6: 跳过活跃运行
                try:
                    dir_time = datetime.strptime(sub.name[:15], "%Y%m%d_%H%M%S")
                    if dir_time < cutoff:
                        shutil.rmtree(sub, ignore_errors=True)
                        removed += 1
                except (ValueError, IndexError):
                    continue
            if removed:
                self._emit_log(f"已清理 {removed} 个过期日志目录（保留 {retention_days} 天）")
        except Exception as e:
            logger.exception("日志清理出错: %s", e)
            self._emit_log(f"日志清理出错: {e}")

    def _execute_single_step(
        self,
        workflow: Workflow,
        step: Step,
        run_history_id: int,
        log_dir: Path,
        signal_policy: RunSignalPolicy,
        prev_step_status_map: Optional[dict] = None,
        run_cancel_event: threading.Event = None,
    ) -> StepResult:
        """执行单个步骤（带重试）"""
        # #7: skip_on_success 检查与落库拆开，让 step_started 信号在 DB 写入之前发出
        # R2-#1: prev_step_status_map 来自 _execute_steps 的 local，避免父子工作流共享 self 属性互相覆盖
        if _should_skip_on_success(
            step=step,
            run_history_id=run_history_id,
            running_status_value=RunStatus.RUNNING.value,
            pending_status_value=RunStatus.PENDING.value,
            prev_step_status_map=prev_step_status_map,
        ):
            self._emit_log(f"跳过步骤 [{step.order}] {step.name}（上次已成功）")
            if signal_policy.emit_step_signals:
                self.step_started.emit(step.id, step.name)
            # 此处再写 StepLog（skipped）——确保任何 step_started 监听器同步查 DB 时看不到 skipped 漂移
            skip_decision = _record_skip_on_success(step=step, run_history_id=run_history_id)
            result = StepResult(
                step_id=step.id,
                step_name=step.name,
                status="skipped",
                exit_code=0,
                start_time=skip_decision.start_time,
                end_time=skip_decision.end_time,
                error_message=skip_decision.note,
            )
            if signal_policy.emit_step_signals:
                self.step_finished.emit(step.id, step.name, result.status, result.duration_seconds)
            return result

        step_log_dir = log_dir / f"step_{step.order:02d}_{step.uid}"
        step_log_dir.mkdir(parents=True, exist_ok=True)

        # 创建步骤日志
        step_log = create_step_log(
            run_history_id=run_history_id,
            step_id=step.id,
            order=step.order
        )

        if signal_policy.emit_step_signals:
            self.step_started.emit(step.id, step.name)
        self._emit_log(f"开始步骤 [{step.order}] {step.name}")

        # 更新状态
        update_step_log(step_log.id, status="running", start_time=datetime.now())

        # 获取执行器
        try:
            executor = get_executor(step.step_type)
        except ValueError as e:
            result = StepResult(
                step_id=step.id,
                step_name=step.name,
                status="failure",
                exit_code=1,
                error_message=str(e)
            )
            self._finish_step(step, step_log.id, result, signal_policy=signal_policy)
            return result

        # 执行（带重试）
        max_retries = step.retry_count + 1
        last_error = None
        cancel_event = threading.Event()

        # CA2: 用 engine_core.cancel.install_cancel_watcher 启动后台线程
        # 把 self.is_cancelled 的状态变化映射到 cancel_event，及时通知执行器
        cancel_watcher = _install_cancel_watcher(
            lambda: self._is_run_cancelled(run_cancel_event),
            cancel_event,
            poll_interval=0.2,
        )

        try:
            for attempt in range(max_retries):
                # 每次重试前检查取消
                if self._is_run_cancelled(run_cancel_event):
                    self._emit_log(f"步骤 [{step.order}] {step.name} 已取消")
                    result = StepResult(
                        step_id=step.id,
                        step_name=step.name,
                        status="cancelled",
                        exit_code=-1,
                        error_message="用户取消"
                    )
                    self._finish_step(step, step_log.id, result, signal_policy=signal_policy)
                    return result

                if attempt > 0:
                    # 指数退避（可被取消中断）
                    # CA2: cancel_event 已由 _watch_cancel 线程映射 self.is_cancelled，
                    # 用 wait(delay) 替代手写的 elapsed 循环，返回 True 即代表期间被取消
                    delay = min(2 ** attempt, 60)
                    self._emit_log(f"第 {attempt + 1} 次重试，等待 {delay} 秒...")
                    if cancel_event.wait(delay):
                        self._emit_log(f"步骤 [{step.order}] {step.name} 重试等待期间已取消")
                        result = StepResult(
                            step_id=step.id,
                            step_name=step.name,
                            status="cancelled",
                            exit_code=-1,
                            error_message="用户取消"
                        )
                        self._finish_step(step, step_log.id, result, signal_policy=signal_policy)
                        return result

                try:
                    exec_result = executor.execute(
                        script_path=step.script_path,
                        args=step.get_args(),
                        cwd=step.cwd,
                        log_dir=step_log_dir,
                        timeout=step.timeout_seconds,
                        chart_theme=step.chart_theme or workflow.chart_theme,
                        workflow_id=workflow.id,
                        workflow_runner=self.run_sub_workflow,
                        cancel_event=cancel_event
                    )

                    if self._is_run_cancelled(run_cancel_event) or cancel_event.is_set():
                        self._emit_log(f"步骤 [{step.order}] {step.name} 已取消")
                        result = StepResult(
                            step_id=step.id,
                            step_name=step.name,
                            status="cancelled",
                            exit_code=exec_result.exit_code if exec_result.exit_code not in (None, 0) else -1,
                            start_time=exec_result.start_time,
                            end_time=exec_result.end_time,
                            error_message="用户取消",
                            log_dir=str(step_log_dir)
                        )
                        self._finish_step(step, step_log.id, result, exec_result, signal_policy)
                        return result

                    if exec_result.success:
                        result = StepResult(
                            step_id=step.id,
                            step_name=step.name,
                            status="success",
                            exit_code=exec_result.exit_code,
                            start_time=exec_result.start_time,
                            end_time=exec_result.end_time,
                            log_dir=str(step_log_dir)
                        )
                        self._finish_step(step, step_log.id, result, exec_result, signal_policy)
                        return result

                    last_error = exec_result.error_message

                except Exception as e:
                    logger.warning("步骤执行异常: %s", e)
                    last_error = str(e)

            # 所有重试都失败 - 集成智能诊断
            diagnosis = ErrorDiagnostician.diagnose(
                error_message=last_error,
                step_type=step.step_type,
                context={"timeout": step.timeout_seconds, "script_path": step.script_path}
            )
            result = StepResult(
                step_id=step.id,
                step_name=step.name,
                status="failure",
                exit_code=1,
                error_message=last_error,
                log_dir=str(step_log_dir),
                suggested_fix=diagnosis["suggested_fix"]
            )
            self._finish_step(step, step_log.id, result, signal_policy=signal_policy)
            return result
        finally:
            cancel_event.set()
            cancel_watcher.join(timeout=1)
            # #17: 守护线程理论上不卡进程，但 alive 仍存表示轮询回调异常，记一行便于诊断
            if cancel_watcher.is_alive():
                logger.warning(
                    "cancel_watcher join 超时未退出: step_id=%s order=%s",
                    getattr(step, "id", None), getattr(step, "order", None),
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
    ) -> List[StepResult]:
        """并行执行多个步骤（Fan-Out/Fan-In 模式）

        CA2: 调度逻辑下沉到 engine_core.scheduler.run_steps_parallel
        MA2: 尊重 workflow.max_workers，避免独占资源的步骤一窝蜂打入
        R2-#1: prev_step_status_map 由 caller 透传，避免 self 属性被并行/嵌套覆盖
        """
        max_workers = max(1, int(getattr(workflow, "max_workers", 0) or 1))

        def _step_runner(step):
            try:
                return self._execute_single_step(
                    workflow, step, run_history_id, log_dir, signal_policy,
                    prev_step_status_map=prev_step_status_map,
                    run_cancel_event=run_cancel_event,
                )
            finally:
                cleanup_session()

        def _on_exception(step, e):
            return StepResult(
                step_id=step.id,
                step_name=step.name,
                status="failure",
                exit_code=1,
                error_message=str(e),
            )

        return _run_steps_parallel(
            steps,
            executor=self._executor,
            max_workers=max_workers,
            step_runner=_step_runner,
            on_exception=_on_exception,
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
        signal_policy = signal_policy or RunSignalPolicy()
        # 更新步骤日志
        update_data = {
            "status": result.status,
            "exit_code": result.exit_code,
            "end_time": result.end_time or datetime.now(),
            "error_message": result.error_message
        }

        if exec_result:
            update_data["stdout_path"] = exec_result.stdout_path
            update_data["stderr_path"] = exec_result.stderr_path
        elif result.log_dir:
            # M2 修复：cancelled / failure 路径下若 exec_result 为 None，
            # 仍从 result.log_dir 推导出 stdout/stderr 路径，避免历史日志丢失
            from os.path import join, isfile
            stdout_guess = join(str(result.log_dir), "stdout.txt")
            stderr_guess = join(str(result.log_dir), "stderr.txt")
            if isfile(stdout_guess):
                update_data["stdout_path"] = stdout_guess
            if isfile(stderr_guess):
                update_data["stderr_path"] = stderr_guess

        update_step_log(step_log_id, **update_data)

        # 发送信号
        status_text = {
            "success": "成功",
            "skipped": "已跳过",
            "cancelled": "已取消",
        }.get(result.status, "失败")
        duration_text = format_duration_short(result.duration_seconds)
        suffix = f" · 耗时 {duration_text}" if duration_text else ""
        self._emit_log(f"步骤 [{step.order}] {step.name} {status_text}{suffix}")
        if signal_policy.emit_step_signals:
            self.step_finished.emit(step.id, step.name, result.status, result.duration_seconds)
