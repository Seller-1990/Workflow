# -*- coding: utf-8 -*-
"""
批量运行工作流脚本

用法:
    # 导入最新工作流（从 workflows_export.json）
    python _import_and_run.py import
    python _import_and_run.py --workflows-json D:/path/workflows_export.json import

    # 运行指定工作流（默认：月度数据处理），启用钉钉通知
    python _import_and_run.py run "月度数据处理"
    python _import_and_run.py run "人员数据处理分析"
    python _import_and_run.py run 5              # 通过 ID 运行

    # 导入后直接运行月度数据处理
    python _import_and_run.py --auto
"""
import sys
import os
from pathlib import Path

# Windows 子进程在非 UTF-8 活动代码页下会把中文输出编码成本地编码，
# 但测试与 CI 按 UTF-8 读取；显式重配可避免 CLI 合同输出乱码。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import argparse
import logging
from PySide6.QtWidgets import QApplication

from database import (
    init_db, import_from_json_with_warnings, list_workflows, get_workflow_by_id,
    get_workflow_by_name, get_run_histories_by_workflow, get_step_logs_by_run
)
from engine import WorkflowEngine, RunMode, RunSignalPolicy

_app = QApplication.instance() or QApplication(sys.argv)

DEFAULT_WORKFLOWS_JSON = Path(__file__).resolve().parent / "workflows_export.json"


def cmd_import(workflows_json: Path):
    workflows_json = Path(workflows_json)
    if not workflows_json.exists():
        raise FileNotFoundError(f"工作流导入文件不存在: {workflows_json}")

    with open(workflows_json, 'r', encoding='utf-8') as f:
        import json
        data = json.load(f)

    for wf in data.get("workflows", []):
        uid = wf.get("id", "")
        name = wf.get("name", "")
        print(f"  [{uid}] {name}", flush=True)

    result = import_from_json_with_warnings(workflows_json)
    print(f"导入完成: {result.imported_count} 个工作流", flush=True)
    for warning in result.warnings:
        print(f"警告: {warning}", flush=True)
    print(flush=True)
    list_workflows()


def find_workflow(name_or_id):
    try:
        wid = int(name_or_id)
        wf = get_workflow_by_id(wid)
        if wf:
            return wf
    except ValueError:
        pass

    wf = get_workflow_by_name(name_or_id)
    if wf:
        return wf

    all_wf = list_workflows()
    for wf in all_wf:
        if name_or_id.lower() in wf.name.lower():
            return wf

    print(f"未找到工作流: {name_or_id}", flush=True)
    print("可用工作流:", flush=True)
    for wf in all_wf:
        print(f"  ID={wf.id}  {wf.name}", flush=True)
    return None


def cmd_run(workflow_name):
    wf = find_workflow(workflow_name)
    if not wf:
        sys.exit(1)

    print(f"工作流: {wf.name} (ID: {wf.id})\n", flush=True)

    engine = WorkflowEngine()

    def on_log(msg):
        print(msg, flush=True)

    def on_step_started(sid, name):
        print(f"  > {name} ...", flush=True)

    def on_step_finished(sid, name, status):
        tag = "OK" if status == "success" else "FAIL"
        print(f"  {tag} [{name}] {status}", flush=True)

    def on_wf_started(wid, rid):
        print(f"\n{'='*60}", flush=True)
        print(f"  工作流开始 | Run ID: {rid}", flush=True)
        print(f"{'='*60}", flush=True)

    def on_wf_finished(wid, rid, status):
        st = {"success": "成功", "failure": "失败", "cancelled": "已取消"}.get(status, status)
        print(f"\n{'='*60}", flush=True)
        print(f"  工作流结束 | 状态: {st} | Run ID: {rid}", flush=True)
        print(f"{'='*60}", flush=True)

    engine.log_output.connect(on_log)
    engine.step_started.connect(on_step_started)
    engine.step_finished.connect(on_step_finished)
    engine.workflow_started.connect(on_wf_started)
    engine.workflow_finished.connect(on_wf_finished)

    result = engine.run(
        wf.id, RunMode.FULL, reason="cli",
        signal_policy=RunSignalPolicy(send_notification=True)
    )

    for _ in range(100):
        _app.processEvents()
        if not engine.is_running:
            break

    print(f"\n最终结果: {'成功' if result else '失败'}", flush=True)

    if not result:
        rh = get_run_histories_by_workflow(wf.id, limit=1)
        if rh:
            logs = get_step_logs_by_run(rh[0].id)
            for sl in logs:
                if sl.status == "failure":
                    print(f"  失败: {sl.error_message}", flush=True)

    # 钉钉通知由引擎提交到内部线程池异步发送；若不先 shutdown(wait=True) 等通知任务收尾、
    # 再刷一轮事件队列，进程退出时"钉钉通知…"成功/失败反馈日志会直接丢失。
    try:
        engine.shutdown(wait=True)
    except (RuntimeError, OSError) as exc:
        print(f"警告: 引擎收尾失败: {exc}", flush=True)
    for _ in range(100):
        _app.processEvents()

    sys.exit(0 if result else 1)


def main():
    # 让 logger.warning（如导入脱敏 webhook 跳过创建提示）对 CLI 用户可见（默认输出到 stderr）
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    init_db()

    parser = argparse.ArgumentParser(
        description="批量运行工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--auto", action="store_true", help="导入后自动运行月度数据处理")
    parser.add_argument(
        "--workflows-json",
        type=Path,
        default=DEFAULT_WORKFLOWS_JSON,
        help=f"工作流导入 JSON 路径（默认: {DEFAULT_WORKFLOWS_JSON}）",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_import = sub.add_parser("import", help="从 workflows_export.json 导入工作流")
    p_run = sub.add_parser("run", help="运行工作流")
    p_run.add_argument("name", help="工作流名称或 ID")

    args = parser.parse_args()

    try:
        if args.auto:
            cmd_import(args.workflows_json)
            print("\n" + "="*60, flush=True)
            cmd_run("月度数据处理")
        elif args.cmd == "import":
            cmd_import(args.workflows_json)
        elif args.cmd == "run":
            cmd_run(args.name)
        else:
            parser.print_help()
    except FileNotFoundError as exc:
        sys.stdout.buffer.write((str(exc) + "\n").encode("utf-8"))
        sys.stdout.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
