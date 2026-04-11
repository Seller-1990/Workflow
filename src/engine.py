# -*- coding: utf-8 -*-
"""工作流编排引擎

基于 workflow-orchestration-patterns 和 error-handling-patterns 技能实现：
- Fan-Out/Fan-In 并行执行
- 自定义异常层次结构
- 重试与指数退避
- 优雅降级
"""

import shutil
import time
import threading
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any

from PySide6.QtCore import QObject, Signal

from config import LOG_DIR
from database import (
    get_session, get_workflow_by_id, get_steps_by_workflow,
    create_run_history, update_run_history,
    create_step_log, update_step_log,
    get_latest_run_history, get_step_logs_by_run,
    ensure_single_script_step, get_stage_order_map, list_stages
)
from models import Workflow, Step, RunHistory, StepLog
from executors import get_executor, ExecutorResult
from notifier import send_workflow_notification
from database import get_webhook_by_id


# ============== 自定义异常层次结构 ==============

class WorkflowError(Exception):
    """工作流基础异常"""
    pass


class ConfigurationError(WorkflowError):
    """配置错误（不可恢复）"""
    pass


class ExecutionError(WorkflowError):
    """执行错误（可能可恢复）"""
    
    def __init__(self, message: str, step_id: int = None, retryable: bool = True):
        super().__init__(message)
        self.step_id = step_id
        self.retryable = retryable


class DependencyError(WorkflowError):
    """依赖错误"""
    pass


class TimeoutError(WorkflowError):
    """超时错误"""
    pass


# ============== 运行模式与状态 ==============

class RunMode(Enum):
    """运行模式"""
    FULL = "full"                    # 全流程运行
    FROM_STEP = "from_step"          # 从指定步骤开始
    ONLY_STEP = "only_step"          # 只运行指定步骤
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
    
    @property
    def success(self) -> bool:
        return self.status == "success"
    
    @property
    def duration_seconds(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


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
    step_finished = Signal(int, str, bool)  # step_id, step_name, success
    log_output = Signal(str)  # message
    progress_updated = Signal(int, int)  # current, total
    error_details = Signal(list)  # [{step_name, step_id, error_message}, ...]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._cancelled = False
        self._current_run_history_id = None
        self._lock = threading.Lock()
        self._watch_thread = None
        self._watch_stop = threading.Event()

    def validate_watch_folders(self, folders: list[str]) -> list[str]:
        """校验监听目录并返回去重后的绝对路径列表。"""
        if not folders:
            raise ValueError("未配置监听目录")

        system_root = Path(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or "")
        protected_roots = {
            p.resolve()
            for p in (
                system_root,
                Path(os.environ.get("ProgramFiles") or ""),
                Path(os.environ.get("ProgramFiles(x86)") or ""),
            )
            if str(p).strip()
        }

        validated: list[str] = []
        seen: set[str] = set()
        for raw_folder in folders:
            folder = (raw_folder or "").strip()
            if not folder:
                continue

            path = Path(folder).expanduser().resolve()
            path_str = str(path)
            if path_str in seen:
                continue
            if not path.exists():
                raise ValueError(f"监听目录不存在: {path}")
            if not path.is_dir():
                raise ValueError(f"监听路径不是目录: {path}")
            if path.parent == path:
                raise ValueError(f"不允许监听磁盘根目录: {path}")
            if any(path == protected or protected in path.parents for protected in protected_roots):
                raise ValueError(f"不允许监听系统目录: {path}")

            seen.add(path_str)
            validated.append(path_str)

        if not validated:
            raise ValueError("未配置有效的监听目录")
        return validated
    
    @property
    def is_running(self) -> bool:
        return self._running
    
    def cancel(self):
        """取消当前运行"""
        with self._lock:
            self._cancelled = True
    
    def _emit_log(self, message: str):
        """发送日志信号"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.emit(f"[{timestamp}] {message}")

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
        """发送钉钉通知"""
        try:
            notify_config = workflow.get_notify_config()
            if not notify_config.get("enabled"):
                return
            
            webhook_id = notify_config.get("webhook_id")
            if not webhook_id:
                self._emit_log("通知未配置机器人")
                return
            
            webhook = get_webhook_by_id(webhook_id)
            if not webhook:
                self._emit_log(f"未找到机器人配置: {webhook_id}")
                return
            
            template = notify_config.get("message_template", "{工作流名称} - {状态} - 编号={运行编号}")
            duration = None
            if start_time and end_time:
                duration = (end_time - start_time).total_seconds()
            
            success, msg = send_workflow_notification(
                webhook_url=webhook.webhook_url,
                keyword=webhook.keyword or "",
                template=template,
                workflow_name=workflow.name,
                workflow_uid=workflow.uid,
                status=status,
                run_id=run_id,
                log_dir=log_dir,
                reason=reason,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=duration
            )
            
            if success:
                self._emit_log(f"已发送钉钉通知到【{webhook.name}】")
            else:
                self._emit_log(f"钉钉通知发送失败: {msg}")
        except Exception as e:
            self._emit_log(f"发送通知出错: {e}")

    # ============== 监听触发 ==============

    def start_watch(self, workflow: Workflow) -> bool:
        """启动文件监听"""
        self.stop_watch()
        if not workflow.watch_enabled:
            return False
        folders = workflow.get_watch_folders()
        if not folders:
            return False
        try:
            folders = self.validate_watch_folders(folders)
        except ValueError as e:
            self._emit_log(f"监听未启动: {e}")
            return False
        cooldown = max(1, int(workflow.cooldown_seconds or 8))
        settle = max(0, int(workflow.settle_seconds or 15))
        mode = workflow.watch_mode or "any_change"
        self._watch_stop.clear()
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            args=(workflow.id, folders, cooldown, settle, mode),
            daemon=True
        )
        self._watch_thread.start()
        self._emit_log("已启动文件监听")
        return True

    def stop_watch(self, join_timeout: float = 1.0):
        """停止文件监听"""
        watch_thread = self._watch_thread
        if watch_thread and watch_thread.is_alive():
            self._watch_stop.set()
            watch_thread.join(timeout=max(0.0, float(join_timeout or 0.0)))
            if watch_thread.is_alive():
                self._emit_log("警告：文件监听线程未能及时退出")
        self._watch_thread = None

    def _watch_loop(self, workflow_id: int, folders: list, cooldown: int, settle: int, mode: str):
        """监听循环"""
        last_mtime = self._scan_mtime(folders)
        last_trigger_time = last_mtime
        pending_since = None
        while not self._watch_stop.is_set():
            if self._watch_stop.wait(cooldown):
                break
            folder_mtimes = self._scan_folder_mtimes(folders)
            current_mtime = max(folder_mtimes.values()) if folder_mtimes else 0
            
            triggered = False
            if mode == "all_folders_updated_since_success":
                if folder_mtimes and all(m > last_trigger_time for m in folder_mtimes.values()):
                    triggered = True
            else:
                if current_mtime > last_mtime:
                    triggered = True
            
            if triggered:
                if pending_since is None:
                    pending_since = time.time()
                elif time.time() - pending_since >= settle:
                    last_mtime = current_mtime
                    last_trigger_time = current_mtime
                    pending_since = None
                    if self._running:
                        self._emit_log("检测到变更，但当前正在运行，已跳过本次触发")
                        continue
                    self._emit_log("检测到文件变更，触发工作流运行")
                    self.run_all(workflow_id, reason="watch")
            else:
                pending_since = None

    def _scan_mtime(self, folders: list) -> float:
        """扫描目录最大修改时间"""
        max_mtime = 0.0
        folder_mtimes = self._scan_folder_mtimes(folders)
        if folder_mtimes:
            max_mtime = max(folder_mtimes.values())
        return max_mtime

    def _scan_folder_mtimes(self, folders: list) -> dict:
        """扫描目录每个文件夹最大修改时间"""
        folder_mtimes = {}
        for folder in folders:
            path = Path(folder)
            if not path.exists():
                continue
            max_mtime = 0.0
            for root, _, files in os.walk(path):
                for name in files:
                    try:
                        mtime = os.path.getmtime(os.path.join(root, name))
                        if mtime > max_mtime:
                            max_mtime = mtime
                    except Exception:
                        continue
            folder_mtimes[str(path)] = max_mtime
        return folder_mtimes
    
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
    
    def retry_failed(self, workflow_id: int, reason: str = "retry") -> bool:
        """重试失败步骤"""
        return self._run(workflow_id, RunMode.RETRY_FAILED, reason=reason)
    
    # ============== 核心执行逻辑 ==============
    
    def _run(
        self,
        workflow_id: int,
        mode: RunMode,
        step_id: int = None,
        reason: str = "manual"
    ) -> bool:
        """执行工作流
        
        Args:
            workflow_id: 工作流 ID
            mode: 运行模式
            step_id: 步骤 ID（用于 FROM_STEP 和 ONLY_STEP 模式）
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
        status = RunStatus.FAILURE.value
        success = False
        workflow = None

        # 原子启动：消除 UI/监听同时触发的双启动窗口
        with self._lock:
            if self._running:
                self._emit_log("错误：已有工作流正在运行")
                return False
            self._running = True
            self._cancelled = False
            start_time = datetime.now()
        
        try:
            # 获取工作流
            workflow = get_workflow_by_id(workflow_id)
            if not workflow:
                raise ConfigurationError(f"工作流不存在: {workflow_id}")
            
            # 自动清理过期日志
            self._cleanup_old_logs(workflow)
            
            # 获取步骤
            all_steps = get_steps_by_workflow(workflow_id)
            if not all_steps:
                raise ConfigurationError("工作流没有步骤")
            
            # 根据模式筛选步骤
            steps = self._select_steps(all_steps, mode, step_id, workflow_id)
            if not steps:
                self._emit_log("没有需要执行的步骤")
                return True
            
            # 创建运行历史
            run_history = create_run_history(
                workflow_id=workflow_id,
                run_mode=mode.value,
                run_mode_param=str(step_id) if step_id else None,
                reason=reason
            )
            run_history_id = run_history.id
            run_id = run_history.run_id
            self._current_run_history_id = run_history_id
            
            # 创建日志目录
            log_dir = LOG_DIR / workflow.uid / run_id
            log_dir.mkdir(parents=True, exist_ok=True)
            
            # 更新运行状态
            update_run_history(
                run_history_id,
                status=RunStatus.RUNNING.value,
                start_time=start_time,
                log_dir=str(log_dir)
            )
            
            self.workflow_started.emit(workflow_id, run_id)
            started_emitted = True
            self._emit_log(f"开始运行工作流: {workflow.name}")
            self._emit_log(f"运行模式: {mode.value}")
            self._emit_log(f"日志目录: {log_dir}")
            
            # 执行步骤
            success = self._execute_steps(workflow, steps, run_history_id, log_dir)
            
            # 更新运行结果
            if self._cancelled:
                status = RunStatus.CANCELLED.value
            else:
                status = RunStatus.SUCCESS.value if success else RunStatus.FAILURE.value
            
            return success
            
        except WorkflowError as e:
            self._emit_log(f"错误: {e}")
            return False
        except Exception as e:
            self._emit_log(f"未知错误: {e}")
            self._emit_log(traceback.format_exc())
            return False
        finally:
            end_time = datetime.now()

            # 运行结果落库 + 通知 + UI 解锁，必须在任何分支都“收尾”
            try:
                if run_history_id:
                    # cancelled 优先，否则按 success/failure
                    final_status = RunStatus.CANCELLED.value if self._cancelled else status
                    update_run_history(
                        run_history_id,
                        status=final_status,
                        end_time=end_time
                    )
            except Exception:
                # 落库失败不应阻断 UI 收尾
                self._emit_log("警告：更新运行历史失败")
                self._emit_log(traceback.format_exc())

            try:
                if started_emitted and run_id:
                    final_status = RunStatus.CANCELLED.value if self._cancelled else status
                    self.workflow_finished.emit(workflow_id, run_id, final_status)
                    if final_status == RunStatus.SUCCESS.value:
                        self._emit_log("工作流运行成功")
                    elif final_status == RunStatus.CANCELLED.value:
                        self._emit_log("工作流已取消")
                    else:
                        self._emit_log("工作流运行失败")

                    # 发送钉钉通知（若启用），确保 cancelled/failure 也能通知
                    if workflow and log_dir:
                        self._send_notification(
                            workflow=workflow,
                            run_id=run_id,
                            status=final_status,
                            log_dir=str(log_dir),
                            reason=reason,
                            start_time=start_time,
                            end_time=end_time,
                        )
            except Exception:
                self._emit_log("警告：运行收尾处理失败")
                self._emit_log(traceback.format_exc())

            with self._lock:
                self._running = False
                self._current_run_history_id = None
    
    def _select_steps(
        self,
        all_steps: List[Step],
        mode: RunMode,
        step_id: int,
        workflow_id: int
    ) -> List[Step]:
        """根据运行模式选择步骤"""
        workflow = get_workflow_by_id(workflow_id)
        if workflow and workflow.single_script_enabled:
            step = self._get_single_script_step(workflow)
            if not step:
                raise ConfigurationError("单脚本模式未配置脚本路径")
            if mode in (RunMode.FULL, RunMode.RETRY_FAILED):
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
        
        elif mode == RunMode.RETRY_FAILED:
            # 重试失败步骤
            latest_run = get_latest_run_history(workflow_id)
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
        # 校验依赖
        step_uids = {s.uid for s in steps}
        for step in steps:
            for dep in step.get_depends_on():
                if dep not in step_uids:
                    raise DependencyError(f"步骤依赖不存在: {dep}")

        # 用途阶段门槛（stage barrier）：默认按用途阶段顺序执行
        if stage_order_by_uid is None:
            stage_order_by_uid = {}

        def _stage_index(s: Step) -> int:
            return int(stage_order_by_uid.get(getattr(s, "stage_uid", None), 0) or 0)

        uid_to_stage = {s.uid: _stage_index(s) for s in steps}
        # 严格规则：禁止依赖未来用途阶段
        for step in steps:
            step_stage = _stage_index(step)
            for dep in step.get_depends_on():
                dep_stage = uid_to_stage.get(dep, 0)
                if dep_stage > step_stage:
                    raise DependencyError(
                        f"跨阶段依赖不允许：步骤“{step.name}”依赖未来阶段的步骤 uid={dep}"
                    )
        
        batches = []
        pending = list(sorted(steps, key=lambda s: (_stage_index(s), s.order)))
        completed_success = set()
        
        while pending:
            # stage barrier：只允许执行“当前最早用途阶段”的步骤
            min_stage = min(_stage_index(s) for s in pending)
            stage_pending = [s for s in pending if _stage_index(s) == min_stage]

            runnable = []
            for step in stage_pending:
                deps = step.get_depends_on()
                if all(dep in completed_success for dep in deps):
                    runnable.append(step)
            
            if not runnable:
                raise DependencyError("依赖形成循环或未满足")
            
            batch = []
            if not workflow.parallel_enabled:
                batch = [runnable[0]]
            else:
                gate_steps = [s for s in runnable if s.is_gate]
                if gate_steps:
                    batch = [gate_steps[0]]
                else:
                    first = runnable[0]
                    first_deps = frozenset(first.get_depends_on())
                    same_level = [
                        s for s in runnable
                        if frozenset(s.get_depends_on()) == first_deps
                    ]
                    # 自动并行：同依赖层（same_level）默认并行
                    # 为确定性：按 order 升序排序
                    batch = sorted(same_level, key=lambda s: s.order)
            
            batches.append(batch)
            for step in batch:
                completed_success.add(step.uid)
            batch_ids = {s.id for s in batch}
            pending = [s for s in pending if s.id not in batch_ids]
        
        return batches

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
                    self._emit_log(f"  执行组 {i}/{total}（{mode}）：{names}")

        self._emit_log(
            f"共 {shown_stages} 个阶段，{len(batches)} 个执行组，{sum(len(b) for b in batches)} 个步骤"
        )
        self._emit_log("═" * 40)

    def _execute_steps(
        self,
        workflow: Workflow,
        steps: List[Step],
        run_history_id: int,
        log_dir: Path
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
            if self._cancelled:
                self._emit_log(f"运行已取消（已完成 {completed_steps}/{total_steps}）")
                if failed_details:
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
                    workflow, step, run_history_id, log_dir
                )
                completed_steps += 1
                self.progress_updated.emit(completed_steps, total_steps)
                
                if not result.success:
                    failed_details.append({
                        "step_id": step.id,
                        "step_name": step.name,
                        "error_message": result.error_message or "未知错误"
                    })
                    self.error_details.emit(failed_details)
                    return False
            else:
                results = self._execute_parallel_steps(
                    workflow, batch, run_history_id, log_dir
                )
                completed_steps += len(batch)
                self.progress_updated.emit(completed_steps, total_steps)
                
                has_failure = False
                for step, result in zip(batch, results):
                    if not result.success:
                        has_failure = True
                        failed_details.append({
                            "step_id": step.id,
                            "step_name": step.name,
                            "error_message": result.error_message or "未知错误"
                        })
                
                if has_failure:
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
        except Exception:
            stages = []

        ordered_uids: List[object] = [uid for uid, _ in sorted(stage_order_by_uid.items(), key=lambda kv: kv[1])]
        max_order = max(stage_order_by_uid.values(), default=-1)

        # 汇总 steps 中出现但不在 stage_map 的 stage_uid（或 None）→ 归入“未归类”
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
            # 只给“存在步骤”的阶段编号，避免空阶段把序号冲散
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

    def _validate_dependencies(self, steps: List[Step]):
        """校验依赖配置"""
        step_uids = {s.uid for s in steps}
        for step in steps:
            for dep in step.get_depends_on():
                if dep not in step_uids:
                    raise DependencyError(f"步骤依赖不存在: {dep}")
    
    def _cleanup_old_logs(self, workflow: Workflow):
        """自动清理过期日志目录"""
        try:
            retention_days = getattr(workflow, 'log_retention_days', 30) or 30
            wf_log_dir = LOG_DIR / workflow.uid
            if not wf_log_dir.exists():
                return
            cutoff = datetime.now() - timedelta(days=retention_days)
            removed = 0
            for sub in sorted(wf_log_dir.iterdir()):
                if sub.is_dir():
                    # 日志目录名格式: YYYYMMDD_HHMMSS
                    try:
                        dir_time = datetime.strptime(sub.name, "%Y%m%d_%H%M%S")
                        if dir_time < cutoff:
                            shutil.rmtree(sub, ignore_errors=True)
                            removed += 1
                    except ValueError:
                        continue
            if removed:
                self._emit_log(f"已清理 {removed} 个过期日志目录（保留 {retention_days} 天）")
        except Exception as e:
            self._emit_log(f"日志清理出错: {e}")

    def _execute_single_step(
        self,
        workflow: Workflow,
        step: Step,
        run_history_id: int,
        log_dir: Path
    ) -> StepResult:
        """执行单个步骤（带重试）"""
        # Skip on Success 检查
        if getattr(step, 'skip_on_success', False):
            latest = get_latest_run_history(step.workflow_id)
            if latest and latest.id != run_history_id:
                from database import get_step_logs_by_run
                prev_logs = get_step_logs_by_run(latest.id)
                for pl in prev_logs:
                    if pl.step_id == step.id and pl.status == 'success':
                        self._emit_log(f"跳过步骤 [{step.order}] {step.name}（上次已成功）")
                        self.step_started.emit(step.id, step.name)
                        result = StepResult(
                            step_id=step.id,
                            step_name=step.name,
                            status="success",
                            exit_code=0
                        )
                        # 创建跳过的日志记录
                        skip_log = create_step_log(
                            run_history_id=run_history_id,
                            step_id=step.id,
                            order=step.order
                        )
                        update_step_log(skip_log.id, status="success",
                                       start_time=datetime.now(),
                                       end_time=datetime.now(),
                                       error_message="已跳过（上次成功）")
                        self.step_finished.emit(step.id, step.name, True)
                        return result
        
        step_log_dir = log_dir / f"step_{step.order:02d}_{step.uid}"
        step_log_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建步骤日志
        step_log = create_step_log(
            run_history_id=run_history_id,
            step_id=step.id,
            order=step.order
        )
        
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
            self._finish_step(step, step_log.id, result)
            return result
        
        # 执行（带重试）
        max_retries = step.retry_count + 1
        last_error = None
        
        for attempt in range(max_retries):
            if attempt > 0:
                # 指数退避
                delay = min(2 ** attempt, 60)
                self._emit_log(f"第 {attempt + 1} 次重试，等待 {delay} 秒...")
                time.sleep(delay)
            
            try:
                exec_result = executor.execute(
                    script_path=step.script_path,
                    args=step.get_args(),
                    cwd=step.cwd,
                    log_dir=step_log_dir,
                    timeout=step.timeout_seconds,
                    chart_theme=step.chart_theme or workflow.chart_theme,
                    workflow_id=workflow.id,
                    workflow_runner=self.run_all
                )
                
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
                    self._finish_step(step, step_log.id, result, exec_result)
                    return result
                
                last_error = exec_result.error_message
                
            except Exception as e:
                last_error = str(e)
        
        # 所有重试都失败
        result = StepResult(
            step_id=step.id,
            step_name=step.name,
            status="failure",
            exit_code=1,
            error_message=last_error,
            log_dir=str(step_log_dir)
        )
        self._finish_step(step, step_log.id, result)
        return result
    
    def _execute_parallel_steps(
        self,
        workflow: Workflow,
        steps: List[Step],
        run_history_id: int,
        log_dir: Path
    ) -> List[StepResult]:
        """并行执行多个步骤（Fan-Out/Fan-In 模式）"""
        max_workers = max(1, workflow.max_workers)
        results = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._execute_single_step,
                    workflow, step, run_history_id, log_dir
                ): step
                for step in steps
            }
            
            for future in as_completed(futures):
                step = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append(StepResult(
                        step_id=step.id,
                        step_name=step.name,
                        status="failure",
                        exit_code=1,
                        error_message=str(e)
                    ))
        
        # 按原始顺序排序
        results.sort(key=lambda r: next(
            (s.order for s in steps if s.id == r.step_id), 0
        ))
        
        return results
    
    def _finish_step(
        self,
        step: Step,
        step_log_id: int,
        result: StepResult,
        exec_result: ExecutorResult = None
    ):
        """完成步骤处理"""
        # 更新步骤日志
        update_data = {
            "status": result.status,
            "exit_code": result.exit_code,
            "end_time": datetime.now(),
            "error_message": result.error_message
        }
        
        if exec_result:
            update_data["stdout_path"] = exec_result.stdout_path
            update_data["stderr_path"] = exec_result.stderr_path
        
        update_step_log(step_log_id, **update_data)
        
        # 发送信号
        status_text = "成功" if result.success else "失败"
        self._emit_log(f"步骤 [{step.order}] {step.name} {status_text}")
        self.step_finished.emit(step.id, step.name, result.success)
