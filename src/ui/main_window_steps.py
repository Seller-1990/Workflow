# -*- coding: utf-8 -*-
"""Step/stage selection restoration helpers for MainWindow."""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer

from database import get_step_by_id, list_stages

logger = logging.getLogger(__name__)
RECOVERABLE_UI_ERRORS = (RuntimeError, AttributeError, TypeError, ValueError)


def reload_steps_views(
    window,
    workflow_id: int,
    *,
    restore_step_id: int | None = None,
    restore_stage_uid: str | None = None,
    reload_editor: bool = False,
    get_step_by_id_func=get_step_by_id,
    list_stages_func=list_stages,
) -> None:
    window.step_table.load_steps(workflow_id)
    window.workbench_board.load_workflow(workflow_id)
    window._refresh_workbench_header(workflow_id)

    def clear_step_context() -> None:
        try:
            window.step_table.set_selected_stage_context(None, clear_step_selection=True)
        except RECOVERABLE_UI_ERRORS as exc:
            logger.warning("清空步骤表阶段上下文失败: workflow_id=%s, error=%s", workflow_id, exc, exc_info=True)
        window.step_editor.clear()
        window.lbl_inspector_kind.setText("Inspector")
        window.lbl_inspector_title.setText("选择步骤或阶段")
        window.run_control.set_selected_step(None, None)
        window.log_panel.set_context(workflow_id=workflow_id, step_id=None)

    def restore_stage_context(stage_uid: str | None) -> None:
        if not stage_uid:
            clear_step_context()
            return
        stage_label = stage_uid
        try:
            for idx, stage in enumerate(list_stages_func(workflow_id), start=1):
                if stage.uid == stage_uid:
                    stage_label = f"S{idx} {stage.name}"
                    break
        except RECOVERABLE_UI_ERRORS as exc:
            logger.warning("恢复阶段标题失败: workflow_id=%s, stage_uid=%s, error=%s", workflow_id, stage_uid, exc)
        try:
            window.workbench_board.select_stage(stage_uid, emit_signal=False)
            window.step_table.set_selected_stage_context(stage_uid, clear_step_selection=True)
        except RECOVERABLE_UI_ERRORS as exc:
            logger.warning("恢复阶段上下文失败: stage_uid=%s, error=%s", stage_uid, exc, exc_info=True)
            return
        window.lbl_inspector_kind.setText("选中阶段")
        window.lbl_inspector_title.setText(stage_label)
        window.step_editor.clear()
        window.run_control.set_selected_step(None, stage_uid)
        window.log_panel.set_context(workflow_id=workflow_id, step_id=None)

    def restore_step_context(step_id: int | None, fallback_stage_uid: str | None) -> None:
        if not step_id or not window.step_table.has_step(int(step_id)):
            restore_stage_context(fallback_stage_uid)
            return
        try:
            window.step_table.select_step(int(step_id), emit_signal=False)
            window.workbench_board.select_step(int(step_id), emit_signal=False)
        except RECOVERABLE_UI_ERRORS as exc:
            logger.warning("恢复步骤选中失败: step_id=%s, error=%s", step_id, exc, exc_info=True)
            restore_stage_context(fallback_stage_uid)
            return
        if reload_editor:
            try:
                window.step_editor.load_step(int(step_id))
            except RECOVERABLE_UI_ERRORS as exc:
                logger.warning("恢复步骤编辑器失败: step_id=%s, error=%s", step_id, exc, exc_info=True)
                restore_stage_context(fallback_stage_uid)
                return
        try:
            step = get_step_by_id_func(int(step_id))
            if step:
                window.lbl_inspector_kind.setText("选中步骤")
                window.lbl_inspector_title.setText(step.name)
        except RECOVERABLE_UI_ERRORS as exc:
            logger.warning("恢复步骤 Inspector 标题失败: step_id=%s, error=%s", step_id, exc)
        stage_uid = fallback_stage_uid
        if stage_uid is None:
            try:
                stage_uid = window.step_table.get_stage_uid_for_step(int(step_id))
            except RECOVERABLE_UI_ERRORS as exc:
                logger.warning("恢复步骤阶段上下文失败: step_id=%s, error=%s", step_id, exc)
                stage_uid = None
        window.run_control.set_selected_step(int(step_id), stage_uid)
        window.log_panel.set_context(workflow_id=workflow_id, step_id=int(step_id))

    QTimer.singleShot(0, lambda sid=restore_step_id, stage_uid=restore_stage_uid: restore_step_context(sid, stage_uid))
