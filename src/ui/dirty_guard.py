# -*- coding: utf-8 -*-
"""主窗口未保存改动守卫（自 main_window 纯移动提取，行为不变）。首参 window 即 MainWindow 实例。

跨方法调用一律走 ``window._xxx`` 委托方法，保持原有动态分发语义。
"""

import logging

logger = logging.getLogger(__name__)


def confirm_discard_unsaved(window, *, reason: str, new_target) -> bool:
    """如果当前上下文有脏改动，弹"保存 / 不保存 / 取消"三选项。

    Returns:
        True  → 调用方可继续切换
        False → 调用方应中止切换

    R2-#2: save_step 已返回 bool。验证失败时返回 False，本函数据此重新评估。
    R2-#3: 取消路径用 blockSignals 包裹 reselect，避免再次触发 _on_workflow_selected
           造成对话框无限重弹。
    """
    try:
        config_dirty = window._should_check_workflow_config_dirty(reason) and window._is_panel_dirty(
            window.workflow_config,
            "workflow_config",
        )
        step_dirty = window._is_panel_dirty(window.step_editor, "step_editor")
    except Exception:
        window._restore_selection_silently(reason)
        return False
    if not config_dirty and not step_dirty:
        return True

    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(window)
    box.setIcon(QMessageBox.Question)
    # R3-#7 / R4-#8: 文案明确「取消」具体取消什么；标题区分工作流/步骤
    if reason == "switch_workflow":
        box.setWindowTitle("切换工作流前是否保存？")
        box.setText(window._build_dirty_message(reason, config_dirty=config_dirty, step_dirty=step_dirty))
        save_btn = box.addButton("保存并切换", QMessageBox.AcceptRole)
        discard_btn = box.addButton("不保存直接切换", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("留在当前", QMessageBox.RejectRole)
    elif reason == "switch_step":
        box.setWindowTitle("切换步骤前是否保存？")
        box.setText(window._build_dirty_message(reason, config_dirty=config_dirty, step_dirty=step_dirty))
        save_btn = box.addButton("保存并切换", QMessageBox.AcceptRole)
        discard_btn = box.addButton("不保存直接切换", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("留在当前", QMessageBox.RejectRole)
    elif reason == "switch_stage":
        box.setWindowTitle("切换阶段前是否保存？")
        box.setText(window._build_dirty_message(reason, config_dirty=config_dirty, step_dirty=step_dirty))
        save_btn = box.addButton("保存并切换", QMessageBox.AcceptRole)
        discard_btn = box.addButton("不保存直接切换", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("留在当前", QMessageBox.RejectRole)
    elif reason == "close":
        box.setWindowTitle("关闭前是否保存？")
        box.setText(window._build_dirty_message(reason, config_dirty=config_dirty, step_dirty=step_dirty))
        save_btn = box.addButton("保存并关闭", QMessageBox.AcceptRole)
        discard_btn = box.addButton("不保存直接关闭", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("留在当前", QMessageBox.RejectRole)
    else:
        box.setWindowTitle("未保存的修改")
        box.setText(window._build_dirty_message(reason, config_dirty=config_dirty, step_dirty=step_dirty))
        save_btn = box.addButton("保存", QMessageBox.AcceptRole)
        discard_btn = box.addButton("不保存", QMessageBox.DestructiveRole)
        cancel_btn = box.addButton("取消", QMessageBox.RejectRole)
    box.setDefaultButton(save_btn)
    # Qt 同步对话框：阻塞直到用户做出选择
    box.exec_()
    clicked = box.clickedButton()
    if clicked is save_btn:
        if not window._save_dirty_panels(config_dirty=config_dirty, step_dirty=step_dirty):
            window._restore_selection_silently(reason)
            return False
        return True
    if clicked is discard_btn:
        if not window._discard_dirty_panels(config_dirty=config_dirty, step_dirty=step_dirty):
            window._restore_selection_silently(reason)
            return False
        return True
    # 取消：恢复 UI 上的选中状态到旧值
    window._restore_selection_silently(reason)
    return False


def should_check_workflow_config_dirty(window, reason: str) -> bool:
    return reason in {"switch_workflow", "close"}


def is_panel_dirty(window, panel, panel_name: str) -> bool:
    if panel is None:
        return False
    dirty_getter = getattr(panel, "is_dirty", None)
    if dirty_getter is None:
        return False
    try:
        return bool(dirty_getter())
    except Exception as exc:
        logger.warning("检查 %s dirty 状态失败: %s", panel_name, exc)
        raise


def build_dirty_message(window, reason: str, *, config_dirty: bool, step_dirty: bool) -> str:
    if config_dirty and step_dirty:
        body = "当前工作流配置和步骤编辑器都有未保存的修改。"
    elif config_dirty:
        body = "当前工作流配置有未保存的修改。"
    else:
        body = "当前步骤编辑器有未保存的修改。"

    if reason == "switch_workflow":
        suffix = "切换工作流前要先保存吗？"
    elif reason == "switch_step":
        suffix = "切换步骤前要先保存吗？"
    elif reason == "switch_stage":
        suffix = "切换阶段前要先保存吗？"
    elif reason == "close":
        suffix = "关闭前要先保存吗？"
    else:
        suffix = "是否保存？"
    return f"{body}\n{suffix}"


def save_dirty_panels(window, *, config_dirty: bool, step_dirty: bool) -> bool:
    if config_dirty:
        try:
            config_ok = bool(window.workflow_config.save_config())
        except Exception as exc:
            logger.warning("自动保存工作流配置失败: %s", exc)
            return False
        if not config_ok:
            return False
        try:
            if window.workflow_config.is_dirty():
                return False
        except Exception as exc:
            logger.warning("保存后复查 workflow_config dirty 失败: %s", exc)
            return False
    if step_dirty:
        try:
            step_ok = bool(window.step_editor.save_step())
        except Exception as exc:
            logger.warning("自动保存步骤失败: %s", exc)
            return False
        if not step_ok:
            return False
        try:
            if window.step_editor.is_dirty():
                return False
        except Exception as exc:
            logger.warning("保存后复查 step_editor dirty 失败: %s", exc)
            return False
    return True


def discard_dirty_panels(window, *, config_dirty: bool, step_dirty: bool) -> bool:
    if config_dirty and not window._discard_panel_changes(window.workflow_config, "workflow_config"):
        return False
    if step_dirty and not window._discard_panel_changes(window.step_editor, "step_editor"):
        return False
    return True


def discard_panel_changes(window, panel, panel_name: str) -> bool:
    if panel is None:
        return True
    discarder = getattr(panel, "discard_changes", None)
    if discarder is not None:
        try:
            discarder()
            return True
        except Exception as exc:
            logger.warning("丢弃 %s 修改失败: %s", panel_name, exc)
            return False
    return window._reset_panel_dirty_state(panel, panel_name)


def reset_panel_dirty_state(window, panel, panel_name: str) -> bool:
    if panel is None:
        return True
    resetter = getattr(panel, "reset_dirty_state", None)
    if resetter is None:
        logger.warning("%s 缺少公开 dirty reset/discard API", panel_name)
        return False
    try:
        resetter()
        return True
    except Exception as exc:
        logger.warning("重置 %s dirty 状态失败: %s", panel_name, exc)
        return False
