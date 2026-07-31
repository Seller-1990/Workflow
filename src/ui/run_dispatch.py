# -*- coding: utf-8 -*-
"""主窗口运行请求分发与停止控制（自 main_window 纯移动提取，行为不变）。

每个函数的首个参数 ``window`` 即 MainWindow 实例；跨方法调用一律走
``window._xxx`` 委托方法，保持原有动态分发语义。
"""

import json
import logging

from ui.run_worker import RunWorker
from ui.theme import msg_warning
from ui.script_run_args_dialog import prompt_run_arg_overrides

logger = logging.getLogger(__name__)


def _is_edit_mode_enabled(window) -> bool:
    is_edit_mode = getattr(window, "is_edit_mode", None)
    if callable(is_edit_mode):
        return bool(is_edit_mode())
    return bool(getattr(window, "_edit_mode", False))


def on_run_requested(window, mode: str, param):
    """运行请求"""
    if not window._current_workflow_id:
        msg_warning(window, window._dark_mode, "警告", "请先选择一个工作流")
        return

    if mode == "cancel":
        stop_workflow(window)
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
            stop_workflow(window)
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
            except (TypeError, RuntimeError):
                pass
            window._pending_retry_cb = None

        def _retry_after_stop(_wid, _run_id, _status):
            try:
                window.engine.workflow_finished.disconnect(_retry_after_stop)
            except (TypeError, RuntimeError):
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

    run_arg_overrides = {}
    if mode == "only_step":
        try:
            run_arg_overrides = _collect_run_arg_overrides(window, mode, param)
            if run_arg_overrides is None:
                return  # 用户取消或参数错误
        except Exception as e:
            logger.exception("收集临时运行参数失败: %s", e)
            msg_warning(window, window._dark_mode, "参数错误", f"无法准备临时参数: {e}")
            return

    window._run_thread = RunWorker(
        window.engine,
        workflow_id=workflow_id,
        mode=mode,
        param=param,
        run_arg_overrides=run_arg_overrides,
    )
    window._run_thread.start()


def stop_workflow(window):
    """停止工作流"""
    window._stopping_in_progress = True
    try:
        from ui.main_window_setup import set_header_run_button_state

        set_header_run_button_state(window, "stopping")
    except Exception:
        pass
    window.engine.cancel()
    window.statusbar.showMessage("正在停止...")


def _collect_run_arg_overrides(window, mode: str, param):
    """在启动 RunWorker 前收集临时参数。返回 None 表示用户取消。"""
    from config import StepType

    workflow_id = window._current_workflow_id

    from database import get_steps_by_workflow, get_workflow_by_id, update_step

    workflow = get_workflow_by_id(workflow_id)
    if workflow is None:
        msg_warning(window, window._dark_mode, "警告", "工作流不存在")
        return None

    all_steps = get_steps_by_workflow(workflow_id) or []
    steps = all_steps
    try:
        from engine import RunMode

        mode_map = {
            "full": RunMode.FULL,
            "from_step": RunMode.FROM_STEP,
            "only_step": RunMode.ONLY_STEP,
            "only_stage": RunMode.ONLY_STAGE,
            "from_stage": RunMode.FROM_STAGE,
        }
        run_mode = mode_map.get(mode)
        if run_mode is not None and hasattr(window.engine, "_select_steps"):
            step_id = param if mode in {"from_step", "only_step"} else None
            stage_uid = param if mode in {"only_stage", "from_stage"} else None
            steps = window.engine._select_steps(
                all_steps, run_mode, step_id, workflow, stage_uid=stage_uid,
            ) or []
    except Exception as e:
        logger.warning("预选步骤失败，回退全部步骤: %s", e)
        steps = all_steps

    def is_python(step) -> bool:
        return getattr(step, "step_type", None) == StepType.PYTHON

    allow_save_defaults = _is_edit_mode_enabled(window)
    accepted, overrides, saved_updates = prompt_run_arg_overrides(
        window,
        steps,
        dark=getattr(window, "_dark_mode", False),
        is_python=is_python,
        allow_save_defaults=allow_save_defaults,
    )
    if not accepted:
        return None
    if saved_updates and not _is_edit_mode_enabled(window):
        require_edit_mode = getattr(window, "_require_edit_mode", None)
        if callable(require_edit_mode):
            require_edit_mode("保存运行参数")
        else:
            msg_warning(
                window,
                getattr(window, "_dark_mode", False),
                "需要开启编辑",
                "保存运行参数前请先开启编辑模式。",
            )
        return None
    steps_by_uid = {str(step.uid): step for step in steps if getattr(step, "uid", None)}
    for step_uid, saved_args in saved_updates.items():
        if not isinstance(saved_args, list) or not all(
            isinstance(arg, str) for arg in saved_args
        ):
            raise ValueError(f"无法保存运行参数：步骤参数必须是字符串数组 ({step_uid})")
        step = steps_by_uid.get(step_uid)
        if step is None:
            raise ValueError(f"无法保存运行参数：步骤不存在 ({step_uid})")
        updated = update_step(
            step.id,
            saved_run_args=json.dumps(saved_args, ensure_ascii=False) if saved_args else None,
        )
        if updated is None:
            raise ValueError(f"无法保存运行参数：步骤不存在 ({step_uid})")
    return overrides
