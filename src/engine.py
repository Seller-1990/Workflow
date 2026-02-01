# -*- coding: utf-8 -*-
"""工作流编排引擎

基于 workflow-orchestration-patterns 和 error-handling-patterns 技能实现：
- Fan-Out/Fan-In 并行执行
- 自定义异常层次结构
- 重试与指数退避
- 优雅降级
"""

import time
import threading
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
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
    ensure_single_script_step
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
    workflow_finished = Signal(int, str, bool)  # workflow_id, run_id, success
    step_started = Signal(int, str)  # step_id, step_name
    step_finished = Signal(int, str, bool)  # step_id, step_name, success
    log_output = Signal(str)  # message
    progress_updated = Signal(int, int)  # current, total
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._cancelled = False
        self._current_run_history_id = None
        self._lock = threading.Lock()
        self._watch_thread = None
        self._watch_stop = threading.Event()
    
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

    def start_watch(self, workflow: Workflow):
        """启动文件监听"""
        self.stop_watch()
        if not workflow.watch_enabled:
            return
        folders = workflow.get_watch_folders()
        if not folders:
            return
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

    def stop_watch(self):
        """停止文件监听"""
        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_stop.set()
            self._watch_thread = None

    def _watch_loop(self, workflow_id: int, folders: list, cooldown: int, settle: int, mode: str):
        """监听循环"""
        last_mtime = self._scan_mtime(folders)
        last_trigger_time = last_mtime
        pending_since = None
        while not self._watch_stop.is_set():
            time.sleep(cooldown)
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
        if self._running:
            self._emit_log("错误：已有工作流正在运行")
            return False
        
        with self._lock:
            self._running = True
            self._cancelled = False
        
        try:
            # 获取工作流
            workflow = get_workflow_by_id(workflow_id)
            if not workflow:
                raise ConfigurationError(f"工作流不存在: {workflow_id}")
            
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
            self._current_run_history_id = run_history.id
            
            # 创建日志目录
            log_dir = LOG_DIR / workflow.uid / run_history.run_id
            log_dir.mkdir(parents=True, exist_ok=True)
            
            # 更新运行状态
            update_run_history(
                run_history.id,
                status=RunStatus.RUNNING.value,
                start_time=datetime.now(),
                log_dir=str(log_dir)
            )
            
            self.workflow_started.emit(workflow_id, run_history.run_id)
            self._emit_log(f"开始运行工作流: {workflow.name}")
            self._emit_log(f"运行模式: {mode.value}")
            self._emit_log(f"日志目录: {log_dir}")
            
            # 执行步骤
            success = self._execute_steps(workflow, steps, run_history.id, log_dir)
            
            # 更新运行结果
            final_status = RunStatus.SUCCESS if success else RunStatus.FAILURE
            if self._cancelled:
                final_status = RunStatus.CANCELLED
            
            update_run_history(
                run_history.id,
                status=final_status.value,
                end_time=datetime.now()
            )
            
            self.workflow_finished.emit(workflow_id, run_history.run_id, success)
            self._emit_log(f"工作流运行{'成功' if success else '失败'}")
            
            # 发送钉钉通知
            self._send_notification(
                workflow=workflow,
                run_id=run_history.run_id,
                status=final_status.value,
                log_dir=str(log_dir),
                reason=reason,
                start_time=run_history.start_time,
                end_time=datetime.now()
            )
            
            return success
            
        except WorkflowError as e:
            self._emit_log(f"错误: {e}")
            return False
        except Exception as e:
            self._emit_log(f"未知错误: {e}")
            return False
        finally:
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
        - 并行仅在 workflow.parallel_enabled=True 且步骤 is_parallel=True 时生效
        """
        # 校验依赖
        self._validate_dependencies(steps)
        
        total_steps = len(steps)
        completed_steps = 0
        
        pending = list(sorted(steps, key=lambda s: s.order))
        completed_success = set()
        
        while pending:
            if self._cancelled:
                self._emit_log("运行已取消")
                return False
            
            runnable = []
            for step in pending:
                deps = step.get_depends_on()
                if all(dep in completed_success for dep in deps):
                    runnable.append(step)
            
            if not runnable:
                raise DependencyError("依赖形成循环或未满足")
            
            # 选择本轮执行批次
            batch = []
            if not workflow.parallel_enabled:
                batch = [runnable[0]]
            else:
                gate_steps = [s for s in runnable if s.is_gate]
                if gate_steps:
                    batch = [gate_steps[0]]
                else:
                    parallel_steps = [s for s in runnable if s.is_parallel]
                    if parallel_steps:
                        batch = parallel_steps
                    else:
                        batch = [runnable[0]]
            
            # 执行批次
            if len(batch) == 1:
                step = batch[0]
                result = self._execute_single_step(
                    workflow, step, run_history_id, log_dir
                )
                completed_steps += 1
                self.progress_updated.emit(completed_steps, total_steps)
                
                if not result.success:
                    return False
                
                completed_success.add(step.uid)
                pending = [s for s in pending if s.id != step.id]
            else:
                results = self._execute_parallel_steps(
                    workflow, batch, run_history_id, log_dir
                )
                completed_steps += len(batch)
                self.progress_updated.emit(completed_steps, total_steps)
                
                if any(not r.success for r in results):
                    return False
                
                for step in batch:
                    completed_success.add(step.uid)
                batch_ids = {s.id for s in batch}
                pending = [s for s in pending if s.id not in batch_ids]
        
        return True

    def _validate_dependencies(self, steps: List[Step]):
        """校验依赖配置"""
        step_uids = {s.uid for s in steps}
        for step in steps:
            for dep in step.get_depends_on():
                if dep not in step_uids:
                    raise DependencyError(f"步骤依赖不存在: {dep}")
    
    def _execute_single_step(
        self,
        workflow: Workflow,
        step: Step,
        run_history_id: int,
        log_dir: Path
    ) -> StepResult:
        """执行单个步骤（带重试）"""
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
                    workflow_id=workflow.id
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
