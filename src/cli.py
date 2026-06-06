# -*- coding: utf-8 -*-
"""
Workflow CLI - 无需 GUI 即可操作工作流

用法:
    python cli.py list                          # 列出所有工作流
    python cli.py run "月度报表"                # 运行整个工作流
    python cli.py run "月度报表" --stage "数据导入"    # 只运行某个阶段
    python cli.py run "月度报表" --from-stage "数据导入" # 从某个阶段开始
    python cli.py run "月度报表" --only "清洗数据"      # 只运行某个步骤
    python cli.py run "月度报表" --from "清洗数据"      # 从某个步骤开始
    python cli.py retry "月度报表"              # 重试失败步骤
    python cli.py history "月度报表"            # 查看运行历史
    python cli.py steps "月度报表"              # 查看工作流步骤
    python cli.py stages "月度报表"             # 查看工作流阶段
    python cli.py export "月度报表" [path]      # 导出工作流（默认脱敏 Webhook URL）
    python cli.py import <json_path>            # 导入工作流
    python cli.py backup                        # 自动备份所有工作流
    python cli.py clone "月度报表" [name]       # 克隆工作流
    python cli.py delete "月度报表"             # 删除工作流
    python cli.py dry-run "月度报表"            # 预览执行计划
"""

import sys
import argparse
from datetime import datetime
from pathlib import Path

# 确保 src 目录在 Python 路径中
src_dir = Path(__file__).resolve().parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# WorkflowEngine 继承 QObject，需要 QApplication 存在
# 在 CLI 模式下创建一个离屏 QApplication
# MA6（部分）：仅在真正实例化 WorkflowEngine 的命令路径里调用 _ensure_qapp。
# list / history / steps / stages / export / import / backup / clone / delete 这些
# 纯查询命令不再启动 QApplication，冷启动从 ~700ms 降到 ~150ms。
from PySide6.QtWidgets import QApplication
from duration_utils import format_duration_short

_app = None


def _ensure_qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)


from database import (
    init_db, list_workflows, get_workflow_by_id, get_workflow_by_uid,
    get_workflow_by_name, search_workflows,
    get_step_by_name, search_steps,
    get_stage_by_name, search_stages, list_stages,
    delete_workflow, clone_workflow,
    export_to_json, import_from_json,
    get_run_histories_by_workflow, get_step_logs_by_run,
    get_steps_by_workflow, auto_backup_workflows,
)
from engine import WorkflowEngine, RunStatus, RunMode, RunSignalPolicy


# ============== 名称解析工具 ==============

def resolve_workflow_id(identifier) -> int:
    """将工作流名称或ID解析为数据库ID

    支持三种方式：
    1. 精确名称匹配 → 返回对应ID（优先，避免名为 "123" 的工作流无法用名称调用）
    2. 精确 UID 匹配 → 返回对应ID
    3. 纯数字 → 作为数据库ID
    4. 模糊匹配 → 如果只有一个结果则自动选择，多个结果则列出供选择

    M6 修复：调整顺序——先按名称查，再 fallback 到数字 ID。
    """
    name = str(identifier).strip()

    # 1. 优先按精确名称查（不论是否是纯数字）
    wf = get_workflow_by_name(name)
    if wf:
        return wf.id

    # 2. 精确 UID 匹配
    wf = get_workflow_by_uid(name)
    if wf:
        print(f"已匹配工作流 UID: {wf.name} (ID: {wf.id})")
        return wf.id

    # 3. 纯数字 → fallback 到数据库 ID
    if isinstance(identifier, int) or (isinstance(identifier, str) and name.isdigit()):
        wid = int(identifier)
        wf = get_workflow_by_id(wid)
        if wf:
            return wid
        print(f"工作流 ID {wid} 不存在")
        sys.exit(1)

    # 4. 模糊匹配
    results = search_workflows(name)
    if not results:
        print(f"未找到匹配的工作流: {name}")
        print("可用工作流:")
        _print_workflow_list(list_workflows())
        sys.exit(1)

    if len(results) == 1:
        print(f"已匹配工作流: {results[0].name} (ID: {results[0].id})")
        return results[0].id

    # 多个匹配结果
    print(f"找到 {len(results)} 个匹配的工作流，请指定更精确的名称:")
    for wf in results:
        print(f"  - {wf.name} (ID: {wf.id})")
    sys.exit(1)


def resolve_step_id(workflow_id: int, identifier) -> int:
    """将步骤名称或ID解析为数据库ID
    
    支持三种方式：
    1. 纯数字 → 直接作为数据库ID
    2. 精确名称匹配 → 返回对应ID
    3. 精确 UID 匹配 → 返回对应ID
    4. 模糊匹配 → 如果只有一个结果则自动选择
    """
    steps = get_steps_by_workflow(workflow_id)

    # 1. 纯数字 → 直接作为ID
    if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.strip().isdigit()):
        sid = int(identifier)
        for s in steps:
            if s.id == sid:
                return sid
        print(f"步骤 ID {sid} 在该工作流中不存在")
        sys.exit(1)
    
    name = str(identifier).strip()
    
    # 2. 精确名称匹配
    step = get_step_by_name(workflow_id, name)
    if step:
        return step.id

    # 3. 精确 UID 匹配
    for s in steps:
        if s.uid == name:
            print(f"已匹配步骤 UID: {s.name} (ID: {s.id})")
            return s.id
    
    # 4. 模糊匹配
    results = search_steps(workflow_id, name)
    if not results:
        print(f"未找到匹配的步骤: {name}")
        print("可用步骤:")
        _print_step_list(workflow_id)
        sys.exit(1)
    
    if len(results) == 1:
        print(f"已匹配步骤: {results[0].name} (ID: {results[0].id})")
        return results[0].id
    
    # 多个匹配结果
    print(f"找到 {len(results)} 个匹配的步骤，请指定更精确的名称:")
    for s in results:
        print(f"  - {s.name} (ID: {s.id}, 顺序: {s.order})")
    sys.exit(1)


def _print_workflow_list(workflows):
    """打印工作流列表"""
    if not workflows:
        print("  (暂无工作流)")
        return
    print(f"  {'ID':<6} {'名称'}")
    print(f"  {'-'*40}")
    for wf in workflows:
        print(f"  {wf.id:<6} {wf.name}")


def _print_step_list(workflow_id):
    """打印步骤列表"""
    steps = get_steps_by_workflow(workflow_id)
    if not steps:
        print("  (暂无步骤)")
        return
    print(f"  {'ID':<6} {'顺序':<6} {'名称'}")
    print(f"  {'-'*50}")
    for s in steps:
        print(f"  {s.id:<6} {s.order:<6} {s.name}")


def resolve_stage_uid(workflow_id: int, identifier) -> str:
    """将阶段名称解析为阶段UID
    
    支持两种方式：
    1. 精确名称匹配 → 返回对应UID
    2. 精确 UID 匹配 → 返回对应UID
    3. 模糊匹配 → 如果只有一个结果则自动选择
    """
    name = str(identifier).strip()
    
    # 1. 精确名称匹配
    stage = get_stage_by_name(workflow_id, name)
    if stage:
        return stage.uid

    stages = list_stages(workflow_id)
    for stage in stages:
        if stage.uid == name:
            print(f"已匹配阶段 UID: {stage.name}")
            return stage.uid
    
    # 3. 模糊匹配
    results = search_stages(workflow_id, name)
    if not results:
        print(f"未找到匹配的阶段: {name}")
        print("可用阶段:")
        _print_stage_list(workflow_id)
        sys.exit(1)
    
    if len(results) == 1:
        print(f"已匹配阶段: {results[0].name}")
        return results[0].uid
    
    # 多个匹配结果
    print(f"找到 {len(results)} 个匹配的阶段，请指定更精确的名称:")
    for s in results:
        print(f"  - {s.name} (顺序: {s.order})")
    sys.exit(1)


def _print_stage_list(workflow_id):
    """打印阶段列表"""
    stages = list_stages(workflow_id)
    if not stages:
        print("  (暂无阶段)")
        return
    print(f"  {'顺序':<6} {'名称'}")
    print(f"  {'-'*40}")
    for s in stages:
        print(f"  {s.order:<6} {s.name}")


# ============== CLI Engine ==============

class CLIEngine:
    """命令行引擎 - 在无 GUI 环境下运行工作流"""

    def __init__(self):
        _ensure_qapp()
        init_db()
        self.engine = WorkflowEngine()
        self._cancelled = False
        self._last_run_id = None
        self._last_start_time = None
        self._last_end_time = None
        self._last_duration_seconds = None
        # 连接信号到 CLI 回调
        self.engine.log_output.connect(self._on_log)
        self.engine.workflow_started.connect(self._on_workflow_started)
        self.engine.workflow_finished.connect(self._on_workflow_finished)
        self.engine.step_started.connect(self._on_step_started)
        self.engine.step_finished.connect(self._on_step_finished)

    def _on_log(self, message):
        tag = ""
        if "[ERROR]" in message:
            tag = "\033[91m"
        elif "[WARNING]" in message:
            tag = "\033[93m"
        elif "[SUCCESS]" in message:
            tag = "\033[92m"
        elif "[INFO]" in message:
            tag = "\033[94m"
        reset = "\033[0m"
        print(f"{tag}{message}{reset}" if tag else message)

    def _on_workflow_started(self, workflow_id, run_id):
        self._last_run_id = run_id
        self._last_start_time = datetime.now()
        print(f"\n{'='*60}")
        print(f"  工作流开始运行 | Run ID: {run_id}")
        print(f"{'='*60}")

    def _on_workflow_finished(self, workflow_id, run_id, status):
        self._last_run_id = run_id
        self._last_end_time = datetime.now()
        if self._last_start_time and self._last_end_time:
            self._last_duration_seconds = max(
                0.0,
                (self._last_end_time - self._last_start_time).total_seconds(),
            )
        status_text = {"success": "成功", "failure": "失败", "cancelled": "已取消"}.get(status, status)
        print(f"\n{'='*60}")
        print(f"  工作流结束 | 状态: {status_text} | Run ID: {run_id}")
        print(f"{'='*60}\n")

    def _on_step_started(self, step_id, step_name):
        print(f"  > {step_name} ...")

    def _on_step_finished(self, step_id, step_name, status, duration_seconds=None):
        duration_text = format_duration_short(duration_seconds)
        suffix = f" · 耗时 {duration_text}" if duration_text else ""
        if status == "success":
            print(f"  OK [{step_name}] 完成{suffix}")
        else:
            print(f"  FAIL [{step_name}] 状态: {status}{suffix}")

    def run(self, workflow_id, mode="full", step_id=None, stage_uid=None, notify_on_complete=True, notify_on_error=True):
        """运行工作流
        
        Args:
            workflow_id: 工作流ID
            mode: 运行模式 (full/from_step/only_step/only_stage/from_stage/retry)
            step_id: 步骤ID（用于from_step/only_step模式）
            stage_uid: 阶段UID（用于only_stage/from_stage模式）
            notify_on_complete: 运行完成时是否发送通知（默认True）
            notify_on_error: 运行出错时是否发送通知（默认True）
        """
        from database import get_webhook_by_id
        from notifier import send_workflow_notification
        
        workflow = get_workflow_by_id(workflow_id)
        if not workflow:
            print(f"工作流 ID {workflow_id} 不存在")
            return False

        print(f"工作流: {workflow.name} (ID: {workflow_id})")
        
        # 记录运行结果和错误信息
        self._run_result = None
        self._run_status = None
        self._error_messages = []
        self._last_run_id = None
        self._last_start_time = None
        self._last_end_time = None
        self._last_duration_seconds = None
        
        # 连接错误收集信号
        def on_error_details(error_list):
            self._error_messages = error_list
        self.engine.error_details.connect(on_error_details)

        try:
            # MA4: 使用公开 run() 入口，禁用引擎自动发送通知（由 CLI 控制）
            policy = RunSignalPolicy(send_notification=False)
            if mode == "full":
                result = self.engine.run(workflow_id, RunMode.FULL, reason="cli", signal_policy=policy)
            elif mode == "from_step" and step_id:
                result = self.engine.run(
                    workflow_id, RunMode.FROM_STEP, step_id=step_id, reason="cli", signal_policy=policy
                )
            elif mode == "only_step" and step_id:
                result = self.engine.run(
                    workflow_id, RunMode.ONLY_STEP, step_id=step_id, reason="cli", signal_policy=policy
                )
            elif mode == "only_stage" and stage_uid:
                result = self.engine.run(
                    workflow_id, RunMode.ONLY_STAGE, stage_uid=stage_uid, reason="cli", signal_policy=policy
                )
            elif mode == "from_stage" and stage_uid:
                result = self.engine.run(
                    workflow_id, RunMode.FROM_STAGE, stage_uid=stage_uid, reason="cli", signal_policy=policy
                )
            elif mode == "retry":
                result = self.engine.run(
                    workflow_id, RunMode.RETRY_FAILED, reason="cli", signal_policy=policy
                )
            else:
                print(f"未知运行模式: {mode}")
                return False

            # MA4: 退出前刷一次事件队列，把 finished/error_details 等队列信号兑现给本地 slot
            if _app:
                for _ in range(100):
                    _app.processEvents()
                    if not self.engine.is_running:
                        break
            self._refresh_last_run_metadata(workflow_id)
            
            # 根据运行结果发送通知
            self._send_cli_notification(workflow, result, notify_on_complete, notify_on_error)
            
            return result
            
        except KeyboardInterrupt:
            print("\n收到取消信号，正在停止...")
            self.engine.cancel()
            self._send_cli_notification(workflow, False, notify_on_complete, notify_on_error, cancelled=True)
            return False
        except Exception as e:
            print(f"运行异常: {e}")
            self._error_messages.append({"step_name": "系统", "error_message": str(e)})
            self._refresh_last_run_metadata(workflow_id)
            self._send_cli_notification(workflow, False, notify_on_complete, notify_on_error)
            return False

    def _refresh_last_run_metadata(self, workflow_id: int):
        histories = get_run_histories_by_workflow(workflow_id, limit=1)
        if not histories:
            return
        latest = histories[0]
        self._last_run_id = latest.run_id or self._last_run_id
        self._last_start_time = latest.start_time or self._last_start_time
        self._last_end_time = latest.end_time or self._last_end_time
        if getattr(latest, "duration_seconds", None) is not None:
            self._last_duration_seconds = latest.duration_seconds
        elif self._last_start_time and self._last_end_time:
            self._last_duration_seconds = max(
                0.0,
                (self._last_end_time - self._last_start_time).total_seconds(),
            )
    
    def _send_cli_notification(self, workflow, success, notify_on_complete, notify_on_error, cancelled=False):
        """CLI模式下发送通知"""
        from database import get_webhook_by_id
        from notifier import send_workflow_notification
        from datetime import datetime
        
        # 检查是否需要发送通知
        should_notify = False
        
        if cancelled and notify_on_complete:
            status = "cancelled"
            should_notify = True
        elif not success and notify_on_error:
            status = "failure"
            should_notify = True
        elif success and notify_on_complete:
            status = "success"
            should_notify = True
        
        if not should_notify:
            return
        
        # 获取通知配置
        notify_config = workflow.get_notify_config()
        if not notify_config.get("enabled"):
            return
        
        webhook_id = notify_config.get("webhook_id")
        if not webhook_id:
            return
        
        webhook = get_webhook_by_id(webhook_id)
        if not webhook:
            return
        
        # 构建错误信息
        error_msg = ""
        if self._error_messages:
            error_parts = [f"{e.get('step_name', '未知步骤')}: {e.get('error_message', '')}" 
                          for e in self._error_messages[:3]]
            error_msg = "\n".join(error_parts)
        
        template = notify_config.get("message_template", "{工作流名称} - {状态} - 编号={运行编号}")
        run_id = self._last_run_id or ("cli_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        start_time = self._last_start_time or datetime.now()
        end_time = self._last_end_time or datetime.now()
        duration_seconds = self._last_duration_seconds
        if duration_seconds is None:
            duration_seconds = max(0.0, (end_time - start_time).total_seconds())
        
        # 发送通知
        success_send, msg = send_workflow_notification(
            webhook_url=webhook.webhook_url,
            keyword=webhook.keyword or "",
            template=template,
            workflow_name=workflow.name,
            workflow_uid=workflow.uid,
            status=status,
            run_id=run_id,
            log_dir="",
            reason="cli",
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration_seconds,
            failure_summary=error_msg if error_msg else ""
        )
        
        if success_send:
            print(f"[通知] 已发送运行状态通知到【{webhook.name}】")

    def dry_run(self, workflow_id):
        """预览执行计划"""
        self.engine.dry_run(workflow_id)

    def close(self):
        self.engine.stop_watch()


# ============== 命令处理 ==============

def cmd_list(args):
    """列出所有工作流"""
    init_db()
    workflows = list_workflows()
    if not workflows:
        print("暂无工作流")
        return

    print(f"\n{'ID':<6} {'名称':<30} {'步骤数':<8} {'创建时间'}")
    print("-" * 70)
    for wf in workflows:
        steps = get_steps_by_workflow(wf.id)
        created = wf.created_at.strftime("%Y-%m-%d %H:%M") if wf.created_at else "N/A"
        print(f"{wf.id:<6} {wf.name:<30} {len(steps):<8} {created}")
    print(f"\n共 {len(workflows)} 个工作流\n")


def cmd_run(args):
    """运行工作流"""
    init_db()
    workflow_id = resolve_workflow_id(args.workflow_id)
    step_id = None
    stage_uid = None
    mode = "full"

    # 阶段参数优先级高于步骤参数
    if args.stage:
        stage_uid = resolve_stage_uid(workflow_id, args.stage)
        mode = "only_stage"
    elif args.from_stage:
        stage_uid = resolve_stage_uid(workflow_id, args.from_stage)
        mode = "from_stage"
    elif args.from_step:
        step_id = resolve_step_id(workflow_id, args.from_step)
        mode = "from_step"
    elif args.only_step:
        step_id = resolve_step_id(workflow_id, args.only_step)
        mode = "only_step"

    cli = CLIEngine()
    success = cli.run(workflow_id, mode=mode, step_id=step_id, stage_uid=stage_uid)
    cli.close()
    sys.exit(0 if success else 1)


def cmd_retry(args):
    """重试失败步骤"""
    init_db()
    workflow_id = resolve_workflow_id(args.workflow_id)
    cli = CLIEngine()
    success = cli.run(workflow_id, mode="retry")
    cli.close()
    sys.exit(0 if success else 1)


def _step_log_name(log) -> str:
    step = getattr(log, "step", None)
    name = getattr(step, "name", None) if step is not None else None
    return name or getattr(log, "step_name", None) or f"步骤#{getattr(log, 'step_id', '?')}"


def _step_log_duration(log) -> str:
    duration = getattr(log, "duration_seconds", None)
    if duration is None:
        start_time = getattr(log, "start_time", None)
        end_time = getattr(log, "end_time", None)
        if start_time and end_time:
            duration = (end_time - start_time).total_seconds()
    return format_duration_short(duration)


def cmd_history(args):
    """查看运行历史"""
    init_db()
    workflow_id = resolve_workflow_id(args.workflow_id)
    histories = get_run_histories_by_workflow(workflow_id, limit=args.limit)
    if not histories:
        print("暂无运行历史")
        return

    print(f"\n{'Run ID':<22} {'状态':<10} {'触发原因':<10} {'开始时间':<20} {'耗时'}")
    print("-" * 80)
    for h in histories:
        status_map = {
            RunStatus.RUNNING.value: "运行中",
            RunStatus.SUCCESS.value: "成功",
            RunStatus.FAILURE.value: "失败",
            RunStatus.CANCELLED.value: "已取消",
        }
        status = status_map.get(h.status, h.status or "未知")
        start = h.start_time.strftime("%Y-%m-%d %H:%M:%S") if h.start_time else "N/A"
        duration = ""
        if h.start_time and h.end_time:
            secs = (h.end_time - h.start_time).total_seconds()
            duration = f"{secs:.1f}s"
        reason = h.reason or "manual"
        print(f"{h.run_id:<22} {status:<10} {reason:<10} {start:<20} {duration}")

    if args.detail and histories:
        latest = histories[0]
        logs = get_step_logs_by_run(latest.id)
        if logs:
            print(f"\n最近一次运行的步骤日志 (Run ID: {latest.run_id}):")
            print(f"  {'步骤':<25} {'状态':<8} {'耗时':<10} {'错误信息'}")
            print(f"  {'-'*70}")
            for log in logs:
                status_map = {
                    "success": "OK",
                    "failure": "FAIL",
                    "running": "RUN",
                    "cancelled": "CANCEL",
                    "skipped": "SKIP",
                    "pending": "WAIT",
                }
                st = status_map.get(log.status, log.status or "UNKNOWN")
                dur = _step_log_duration(log)
                err = (log.error_message or "")[:40]
                print(f"  {_step_log_name(log):<25} {st:<8} {dur:<10} {err}")
    print()


def cmd_steps(args):
    """查看工作流步骤"""
    init_db()
    workflow_id = resolve_workflow_id(args.workflow_id)
    steps = get_steps_by_workflow(workflow_id)
    if not steps:
        print("工作流没有步骤")
        return

    workflow = get_workflow_by_id(workflow_id)
    print(f"\n工作流: {workflow.name if workflow else args.workflow_id}")
    print(f"{'顺序':<6} {'类型':<18} {'名称':<30} {'阶段':<15} {'依赖'}")
    print("-" * 85)
    
    # 加载阶段映射
    stages = list_stages(workflow_id)
    stage_uid_to_name = {s.uid: s.name for s in stages}
    
    for s in steps:
        stage_name = stage_uid_to_name.get(s.stage_uid, "") or ""
        deps = s.depends_on or ""
        print(f"{s.order:<6} {s.step_type:<18} {s.name:<30} {stage_name:<15} {deps}")
    print()


def cmd_stages(args):
    """查看工作流阶段"""
    init_db()
    workflow_id = resolve_workflow_id(args.workflow_id)
    workflow = get_workflow_by_id(workflow_id)
    stages = list_stages(workflow_id)
    if not stages:
        print("工作流没有阶段")
        return

    print(f"\n工作流: {workflow.name if workflow else args.workflow_id}")
    print(f"{'顺序':<6} {'名称':<30} {'步骤数'}")
    print("-" * 50)
    
    steps = get_steps_by_workflow(workflow_id)
    for s in stages:
        count = sum(1 for st in steps if st.stage_uid == s.uid)
        print(f"{s.order:<6} {s.name:<30} {count}")
    print()


def cmd_export(args):
    """导出工作流"""
    init_db()
    workflow_id = resolve_workflow_id(args.workflow_id)
    workflow = get_workflow_by_id(workflow_id)
    if not workflow:
        print(f"工作流不存在")
        return

    output = Path(args.output) if args.output else Path(f"{workflow.name}.json")
    include_secrets = bool(getattr(args, "include_secrets", False))
    export_to_json(output, workflow_ids=[workflow_id], include_secrets=include_secrets)
    print(f"工作流已导出到: {output.resolve()}")
    if not include_secrets:
        print("提示: Webhook URL 已脱敏；如需完整密钥导出，请显式使用 --include-secrets")


def cmd_import(args):
    """导入工作流"""
    init_db()
    json_path = Path(args.json_path)
    if not json_path.exists():
        print(f"文件不存在: {json_path}")
        return

    count = import_from_json(json_path)
    print(f"成功导入 {count} 个工作流")


def cmd_backup(args):
    """备份所有工作流"""
    init_db()
    backup_dir = Path(args.dir) if args.dir else None
    include_secrets = bool(getattr(args, "include_secrets", False))
    result = auto_backup_workflows(backup_dir, include_secrets=include_secrets)
    print(f"备份完成: {result}")
    if include_secrets:
        print("警告: 本次备份包含完整 Webhook URL，请勿同步或共享该文件")
    else:
        print("提示: Webhook URL 已脱敏；如需完整恢复备份，请显式使用 --include-secrets")


def cmd_clone(args):
    """克隆工作流"""
    init_db()
    workflow_id = resolve_workflow_id(args.workflow_id)
    new_wf = clone_workflow(workflow_id, args.name)
    if new_wf:
        print(f"已克隆: {new_wf.name} (ID: {new_wf.id})")
    else:
        print(f"克隆失败")


def cmd_delete(args):
    """删除工作流"""
    init_db()
    workflow_id = resolve_workflow_id(args.workflow_id)
    if not args.force:
        workflow = get_workflow_by_id(workflow_id)
        confirm = input(f"确认删除工作流「{workflow.name if workflow else workflow_id}」? (y/N): ")
        if confirm.lower() != 'y':
            print("已取消")
            return

    success = delete_workflow(workflow_id)
    if success:
        print(f"工作流已删除")
    else:
        print(f"删除失败")


def cmd_dry_run(args):
    """预览执行计划"""
    init_db()
    workflow_id = resolve_workflow_id(args.workflow_id)
    cli = CLIEngine()
    cli.dry_run(workflow_id)
    cli.close()


# ============== 主入口 ==============

def main():
    parser = argparse.ArgumentParser(
        description="Workflow CLI - 工作流命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # list
    subparsers.add_parser("list", aliases=["ls"], help="列出所有工作流")

    # run
    run_parser = subparsers.add_parser("run", aliases=["start"], help="运行工作流")
    run_parser.add_argument("workflow_id", help="工作流名称 / UID / ID")
    run_parser.add_argument("--stage", "-s", dest="stage", help="只运行指定阶段（名称 / UID）")
    run_parser.add_argument("--from-stage", "-S", dest="from_stage", help="从指定阶段开始运行（名称 / UID）")
    run_parser.add_argument("--only", "-o", dest="only_step", help="只运行指定步骤（名称 / UID / ID）")
    run_parser.add_argument("--from", "-f", dest="from_step", help="从指定步骤开始（名称 / UID / ID）")

    # retry
    retry_parser = subparsers.add_parser("retry", aliases=["rerun"], help="重试失败步骤")
    retry_parser.add_argument("workflow_id", help="工作流名称 / UID / ID")

    # history
    hist_parser = subparsers.add_parser("history", aliases=["hist"], help="查看运行历史")
    hist_parser.add_argument("workflow_id", help="工作流名称 / UID / ID")
    hist_parser.add_argument("--limit", "-n", type=int, default=20, help="显示条数 (默认 20)")
    hist_parser.add_argument("--detail", action="store_true", help="显示最近一次的步骤详情")

    # steps
    steps_parser = subparsers.add_parser("steps", aliases=["show"], help="查看工作流步骤")
    steps_parser.add_argument("workflow_id", help="工作流名称 / UID / ID")

    # stages
    stages_parser = subparsers.add_parser("stages", aliases=["stage"], help="查看工作流阶段")
    stages_parser.add_argument("workflow_id", help="工作流名称 / UID / ID")

    # dry-run
    dry_parser = subparsers.add_parser("dry-run", aliases=["preview"], help="预览执行计划")
    dry_parser.add_argument("workflow_id", help="工作流名称 / UID / ID")

    # export
    export_parser = subparsers.add_parser("export", help="导出工作流")
    export_parser.add_argument("workflow_id", help="工作流名称 / UID / ID")
    export_parser.add_argument("output", nargs="?", help="输出路径 (默认: 工作流名.json)")
    export_parser.add_argument(
        "--include-secrets",
        action="store_true",
        help="导出完整 Webhook URL；默认会脱敏，避免共享文件泄露 token",
    )

    # import
    import_parser = subparsers.add_parser("import", aliases=["load"], help="导入工作流")
    import_parser.add_argument("json_path", help="JSON 文件路径")

    # backup
    backup_parser = subparsers.add_parser("backup", aliases=["bak"], help="备份所有工作流")
    backup_parser.add_argument("--dir", "-d", help="备份目录 (默认: 自动)")
    backup_parser.add_argument(
        "--include-secrets",
        action="store_true",
        help="备份完整 Webhook URL；默认会脱敏，避免同步或共享备份时泄露 token",
    )
    backup_parser.add_argument(
        "--without-secrets",
        action="store_true",
        help="兼容旧参数；当前默认已脱敏",
    )

    # clone
    clone_parser = subparsers.add_parser("clone", aliases=["cp"], help="克隆工作流")
    clone_parser.add_argument("workflow_id", help="工作流名称 / UID / ID")
    clone_parser.add_argument("name", nargs="?", help="新名称 (默认: 原名_副本)")

    # delete
    delete_parser = subparsers.add_parser("delete", aliases=["rm"], help="删除工作流")
    delete_parser.add_argument("workflow_id", help="工作流名称 / UID / ID")
    delete_parser.add_argument("--force", "-f", "-y", action="store_true", help="跳过确认")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    COMMAND_ALIASES = {
        "ls": "list",
        "start": "run",
        "rerun": "retry",
        "hist": "history",
        "show": "steps",
        "stage": "stages",
        "preview": "dry-run",
        "load": "import",
        "bak": "backup",
        "cp": "clone",
        "rm": "delete",
    }

    commands = {
        "list": cmd_list,
        "run": cmd_run,
        "retry": cmd_retry,
        "history": cmd_history,
        "steps": cmd_steps,
        "stages": cmd_stages,
        "dry-run": cmd_dry_run,
        "export": cmd_export,
        "import": cmd_import,
        "backup": cmd_backup,
        "clone": cmd_clone,
        "delete": cmd_delete,
    }

    command_name = COMMAND_ALIASES.get(args.command, args.command)
    handler = commands.get(command_name)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
