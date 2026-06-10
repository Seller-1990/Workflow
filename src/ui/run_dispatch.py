# -*- coding: utf-8 -*-
"""主窗口运行请求分发与停止控制（自 main_window 纯移动提取，行为不变）。

每个函数的首个参数 ``window`` 即 MainWindow 实例；跨方法调用一律走
``window._xxx`` 委托方法，保持原有动态分发语义。
"""

import logging
import threading

from ui.run_actions import run_engine_mode
from ui.theme import msg_warning

logger = logging.getLogger(__name__)


def on_run_requested(window, mode: str, param):
    """运行请求"""
    if not window._current_workflow_id:
        msg_warning(window, window._dark_mode, "警告", "请先选择一个工作流")
        return

    if mode == "cancel":
        window.engine.cancel()
        window.statusbar.showMessage("正在停止...")
        return

    # R6-#2 / R7-#1: 主线程预检——已有运行时给三按钮弹窗（停止/切回/取消），
    # 而不是单纯告知（避免用户被迫手工编排）
    if getattr(window.engine, "is_running", False):
        running_id = getattr(window, "_running_workflow_id", None)
        running_name = getattr(window, "_running_workflow_name", None) or (
            f"#{running_id}" if running_id is not None else "(未知)"
        )
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(window)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("已有运行中")
        box.setText(
            f"工作流「{running_name}」正在运行中。\n请选择一项操作："
        )
        stop_run_new_btn = box.addButton(
            "停止当前并运行新的", QMessageBox.DestructiveRole
        )
        goto_running_btn = box.addButton("切回当前运行", QMessageBox.AcceptRole)
        cancel_btn = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is cancel_btn:
            return
        if clicked is goto_running_btn:
            # 复用切回逻辑
            window._on_bg_running_label_clicked(None)
            return
        # stop_run_new_btn：先取消，等 finished 信号到再触发新运行
        try:
            window.engine.cancel()
            window.statusbar.showMessage("已请求停止当前运行，等待后再启动新运行...", 5000)
        except Exception as e:
            logger.warning("请求停止失败: %s", e)

        target_workflow_id = window._current_workflow_id
        target_mode = mode
        target_param = param

        # R8-#1: 多次点「停止并运行新的」时不再累积回调——
        # 新建前先断开旧的（_pending_retry_cb 持有上次的闭包引用）
        prev_cb = getattr(window, "_pending_retry_cb", None)
        if prev_cb is not None:
            try:
                window.engine.workflow_finished.disconnect(prev_cb)
            except Exception:
                pass
            window._pending_retry_cb = None

        def _retry_after_stop(_wid, _run_id, _status):
            try:
                window.engine.workflow_finished.disconnect(_retry_after_stop)
            except Exception:
                pass
            window._pending_retry_cb = None
            # 异步重新触发请求，让 Qt 完整跑完 finished 逻辑
            from PySide6.QtCore import QTimer as _QTimer
            if window._current_workflow_id == target_workflow_id:
                _QTimer.singleShot(
                    50,
                    lambda: window._on_run_requested(target_mode, target_param),
                )
            else:
                # R8-#3: 用户在等待期间切了工作流——放弃重试，但显式告知
                window.statusbar.showMessage(
                    "已取消待执行的新运行（工作流已切换）", 4000
                )

        try:
            window.engine.workflow_finished.connect(_retry_after_stop)
            window._pending_retry_cb = _retry_after_stop
        except Exception as e:
            logger.warning("连接 finished 信号失败: %s", e)
        return

    workflow_id = window._current_workflow_id

    def run_in_thread():
        try:
            run_engine_mode(
                window.engine,
                workflow_id=workflow_id,
                mode=mode,
                param=param,
            )
        except Exception as e:
            from PySide6.QtCore import QMetaObject, Qt, Q_ARG
            QMetaObject.invokeMethod(
                window.engine, "_emit_log",
                Qt.QueuedConnection,
                Q_ARG(str, f"运行异常: {e}")
            )

    window._run_thread = threading.Thread(target=run_in_thread, daemon=True)
    window._run_thread.start()


def stop_workflow(window):
    """停止工作流"""
    window.engine.cancel()
    window.statusbar.showMessage("正在停止...")


def on_statusbar_stop_clicked(window):
    """R5-#5: 状态栏停止按钮过渡态——点击后立即禁用并改文案，与 run_control 一致"""
    try:
        window._statusbar_stop_btn.setEnabled(False)
        window._statusbar_stop_btn.setText("⏹ 正在停止...")
    except Exception as exc:
        logger.warning("更新状态栏停止按钮失败", exc_info=exc)
    window._stop_workflow()
