# -*- coding: utf-8 -*-
"""主窗口运行生命周期处理（自 main_window 纯移动提取，行为不变）。

覆盖运行开始/结束、步骤状态、进度与失败汇总、运行锁面板守卫以及
「后台运行中」指示器。每个函数的首个参数 ``window`` 即 MainWindow 实例；
跨方法调用一律走 ``window._xxx`` 委托方法，保持原有动态分发语义。
"""

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox

from ui.error_summary import ErrorSummaryDialog
from ui.main_window_setup import set_header_run_button_state
from ui.run_state import compute_run_lock_state
from ui.theme import msg_information, msg_warning, msg_question

logger = logging.getLogger(__name__)


def confirm_switch_while_running(window, target) -> str:
    """R4-#3 / R5-#4: 运行中切换工作流弹窗。

    Returns:
        "cancel"        → 留在当前，不切换
        "stop"          → 切换且应在后续合适时机停止运行
        "keep_running"  → 切换并保留后台运行
    本函数不再直接调用 engine.cancel()——延迟到所有确认串联通过后再 commit，
    避免用户在第二个弹窗反悔时旧运行已被不可逆停止。
    """
    from PySide6.QtWidgets import QMessageBox
    # R5-#1: 文案改为如实说明——后台继续会失去可视化反馈通道
    running_wf_name = "?"
    try:
        from database import get_workflow_by_id as _gwf
        wf = _gwf(window._current_workflow_id)
        if wf:
            running_wf_name = wf.name
    except Exception:
        pass
    box = QMessageBox(window)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("运行进行中")
    box.setText(
        f"工作流「{running_wf_name}」正在运行中。\n\n"
        "• 停止运行并切换：终止当前运行后再切换\n"
        "• 后台继续运行并切换：切换到新工作流，原运行继续，"
        "但将失去对它的进度可见性与停止入口（需返回原工作流才能查看/停止）\n"
        "• 留在当前：不切换"
    )
    stop_and_switch = box.addButton("停止运行并切换", QMessageBox.DestructiveRole)
    keep_running_switch = box.addButton("后台继续运行并切换", QMessageBox.AcceptRole)
    cancel = box.addButton("留在当前", QMessageBox.RejectRole)
    box.setDefaultButton(cancel)
    box.exec_()
    clicked = box.clickedButton()
    if clicked is cancel:
        return "cancel"
    if clicked is stop_and_switch:
        return "stop"
    return "keep_running"


def refresh_bg_running_label_theme(window) -> None:
    """R7-#2 / R8-#2: 后台运行标签——浅主题用 #B25000 (~5.0:1)、暗主题保持 #FF9500；
    用 QFont.setUnderline 而非 QSS text-decoration（QLabel QSS 不支持后者）。
    """
    try:
        dark = getattr(window, "_dark_mode", False)
        color = "#FF9500" if dark else "#B25000"
        window._bg_running_label.setStyleSheet(
            f"color: {color}; padding: 0 8px; font-weight: 600;"
        )
        # R8-#2: QLabel QSS 不识别 text-decoration，必须走 QFont
        from PySide6.QtGui import QFont as _QFont
        f = _QFont(window._bg_running_label.font())
        f.setUnderline(True)
        window._bg_running_label.setFont(f)
    except Exception:
        pass


def refresh_run_lock_panels(window) -> None:
    """R5-#1 / R6-#1: 仅当显示的工作流 == 正在运行的工作流时锁定编辑面板。

    否则用户后台运行旧工作流又切到新工作流，新工作流面板会被无理由禁用。
    额外更新"后台运行中"持久指示器（QLabel，常驻状态栏）。
    """
    running_id = getattr(window, "_running_workflow_id", None)
    current_id = window._current_workflow_id
    stopping = getattr(window, "_stopping_in_progress", False)
    state = compute_run_lock_state(
        running_id=running_id,
        current_id=current_id,
        engine_running=bool(getattr(window.engine, "is_running", False)),
        stopping=stopping,
        running_name=getattr(window, "_running_workflow_name", None),
    )
    # R6-#4: 兜底——若 engine.is_running 已为 False 但 _running_workflow_id 还非空
    # （理论上 finished 信号一定会清；这里防御未来 signal_policy 不对称导致永久卡住）
    if state.clear_stale_running:
        window._running_workflow_id = None
        window._running_workflow_name = None
        window._stopping_in_progress = False
        running_id = None
    lock_panels = state.lock_panels
    try:
        window.workflow_config.setEnabled(not lock_panels)
        window.step_table.setEnabled(not lock_panels)
        window.step_editor.setEnabled(not lock_panels)
    except Exception:
        pass
    # R6-#1: 后台运行（运行中但用户切走了）→ 持久指示器；同步可见性
    # R6-#3: stop 请求已发出但 finished 信号未到的窗口，暂不显示"后台运行"标签
    try:
        if state.show_background_label:
            window._bg_running_label.setText(state.background_label_text)
            window._bg_running_label.setVisible(True)
        else:
            window._bg_running_label.setVisible(False)
    except Exception:
        pass


def on_bg_running_label_clicked(window, _event) -> None:
    """R6-#1: 点击「后台运行：XX」标签 → 切回正在运行的工作流"""
    running_id = getattr(window, "_running_workflow_id", None)
    if running_id is None:
        return
    try:
        lw = getattr(window.workflow_list, "list_widget", None)
        if lw is None:
            return
        for i in range(lw.count()):
            it = lw.item(i)
            if it and it.data(Qt.UserRole) == running_id:
                lw.setCurrentItem(it)
                return
    except Exception as e:
        logger.warning("切回运行工作流失败: %s", e)


def on_workflow_started(window, workflow_id: int, run_id: str):
    """工作流开始"""
    # R5-#1: 记录正在运行的 workflow_id，供面板锁定守卫与切换显示判断使用
    window._running_workflow_id = workflow_id
    # R6-#1: 缓存名字，避免每次切换都查 DB
    try:
        from database import get_workflow_by_id as _gwf
        wf = _gwf(workflow_id)
        window._running_workflow_name = wf.name if wf else None
    except Exception:
        window._running_workflow_name = None
    window.statusbar.showMessage(f"运行中... ({run_id})", 5000)
    window.lbl_run_state.setText("● 运行中")
    window.lbl_run_state.setToolTip(f"当前运行中：{run_id}")
    set_header_run_button_state(window, "running")
    window._apply_run_splitter_profile("running")

    window.run_control.set_running(True)
    window.log_panel.set_running(True)
    # R3-#5: 启用 Shift+F5 停止快捷键
    try:
        window.action_stop_shortcut.setEnabled(True)
    except Exception:
        pass

    # U-P1-7 / R5-#1: 仅当当前显示的工作流 == 正在运行的工作流，才禁用编辑面板。
    # 用户后台运行旧工作流又切到新工作流时，新工作流面板不应被锁。
    window._refresh_run_lock_panels()

    sizes = window.main_splitter.sizes()
    if len(sizes) >= 3 and sizes[2] <= 0:
        sizes[2] = max(getattr(window, "_right_last_size", 340), 320)
        window.main_splitter.setSizes(sizes)
    window.step_table.reset_all_status()
    window.workbench_board.reset_all_status()


def on_workflow_finished(window, workflow_id: int, run_id: str, status: str):
    """工作流结束"""
    # R5-#1 / R6-#1 / R6-#3: 清理 running_workflow_id + 缓存名字 + stopping 标记
    window._running_workflow_id = None
    window._running_workflow_name = None
    window._stopping_in_progress = False
    window.run_control.set_running(False)
    window.log_panel.set_running(False)
    window.lbl_run_state.setText("● 就绪")
    window.lbl_run_state.setToolTip("当前运行状态：就绪")
    set_header_run_button_state(window, "idle")
    window._apply_run_splitter_profile("idle")
    # R3-#5: 禁用 Shift+F5 停止快捷键
    try:
        window.action_stop_shortcut.setEnabled(False)
    except Exception:
        pass

    # U-P1-7 / R5-#1: 用统一守卫恢复面板可编辑性
    window._refresh_run_lock_panels()

    status_map = {
        "success": "完成",
        "failure": "失败",
        "cancelled": "已取消",
    }
    text = status_map.get(status, status)
    window.statusbar.showMessage(f"运行{text} ({run_id})", 5000)

    if window._current_workflow_id == workflow_id:
        # R4-#10: 推迟到下一轮事件循环，避免 finished 信号到达瞬间主线程
        # 立刻执行 get_run_histories + summary 查询（~30-80ms 卡顿）
        QTimer.singleShot(0, lambda wid=workflow_id: window._async_load_history(wid))


def on_step_started(window, step_id: int, step_name: str):
    """步骤开始"""
    window.step_table.highlight_step(step_id, "running")
    if hasattr(window, "workbench_board"):
        window.workbench_board.highlight_step(step_id, "running")


def on_step_finished(window, step_id: int, step_name: str, status: str, duration_seconds=None):
    """步骤结束"""
    window.step_table.highlight_step(step_id, status)
    if hasattr(window, "workbench_board"):
        window.workbench_board.highlight_step(step_id, status, duration_seconds)


def on_progress_updated(window, current: int, total: int):
    """进度更新"""
    window.statusbar.showMessage(f"进度: {current}/{total}")


def on_error_details(window, error_list: list):
    """失败汇总：日志内联 + 弹窗"""
    window.log_panel.append_error_details(error_list)
    dialog = ErrorSummaryDialog(error_list, window, workflow_id=window._current_workflow_id)
    dialog.navigate_to_step.connect(window._focus_step)
    dialog.retry_failed.connect(lambda: window._on_run_requested("retry_failed", None))
    dialog.open_step_log.connect(lambda sid: window._open_step_log_for_step(sid))
    dialog.exec_()


def focus_step(window, step_id: int):
    """定位到步骤（列表选中 + 打开编辑器 + 滚动到可见）"""
    if not step_id:
        return
    try:
        window.step_table.select_step(step_id)
        window._on_step_selected(step_id)
        window.center_scroll.ensureWidgetVisible(window.step_table)
    except Exception:
        return


def open_step_log_for_step(window, step_id: int):
    """打开指定步骤在最新一次运行中的日志（复用 LogPanel 的上下文）"""
    if not window._current_workflow_id or not step_id:
        return
    try:
        window.log_panel.set_context(workflow_id=window._current_workflow_id, step_id=step_id)
        window.log_panel.open_step_log()
    except Exception:
        return


def open_failures_for_history(window, history_id: int):
    """从运行历史打开失败步骤汇总"""
    if not window._current_workflow_id or not history_id:
        return
    try:
        from database import get_step_logs_by_run, get_steps_by_workflow

        steps = get_steps_by_workflow(window._current_workflow_id)
        step_name_by_id = {s.id: s.name for s in steps}
        logs = get_step_logs_by_run(history_id)
        failures = [
            {
                "step_id": l.step_id,
                "step_name": step_name_by_id.get(l.step_id, f"步骤#{l.step_id}"),
                "error_message": getattr(l, "error_message", "") or "",
            }
            for l in logs
            if l.status == "failure"
        ]
        if not failures:
            msg_information(window, window._dark_mode, "提示", "该次运行没有失败步骤。")
            return
        dialog = ErrorSummaryDialog(failures, window, workflow_id=window._current_workflow_id)
        dialog.navigate_to_step.connect(window._focus_step)
        dialog.retry_failed.connect(lambda: window._on_run_requested("retry_failed", None))
        dialog.open_step_log.connect(lambda sid: window._open_step_log_for_step(sid))
        dialog.exec_()
    except Exception as e:
        msg_warning(window, window._dark_mode, "打开失败汇总失败", str(e))


def on_dry_run(window):
    """预演模式"""
    if not window._current_workflow_id:
        msg_warning(window, window._dark_mode, "警告", "请先选择一个工作流")
        return
    window.engine.dry_run(window._current_workflow_id)


def on_force_stop_run(window, run_history_id: int):
    """强制停止运行历史中的任务"""
    reply = msg_question(
        window, window._dark_mode, "确认强制停止",
        "确定要强制停止该运行吗？\n未完成的步骤将被标记为已取消。",
    )
    if reply == QMessageBox.Yes:
        window.engine.force_stop_run(run_history_id)
        if window._current_workflow_id:
            window.run_history.load_history(window._current_workflow_id)
