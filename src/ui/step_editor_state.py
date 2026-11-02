# -*- coding: utf-8 -*-
"""Apply editor view/write permissions through the panel compatibility seam."""

def apply_enabled_state(panel):
    can_edit = panel._edit_enabled
    has_step = panel._step_id is not None
    can_edit_step = can_edit and has_step
    # 编辑模式只做「写操作门禁」，不应让用户无法查看/复制字段内容
    panel.section.setEnabled(True)
    panel.section.set_collapsed(False)
    panel.btn_save.setEnabled(can_edit_step)

    # 基础字段：只读/可编辑
    panel._safe_update_control_state(
        "基础字段",
        lambda: (
            panel.edit_name.setReadOnly(not can_edit_step),
            panel.edit_script.setReadOnly(not can_edit_step),
        ),
    )
    panel._safe_update_control_state("浏览脚本按钮", lambda: panel.btn_browse.setEnabled(can_edit_step))
    panel._safe_update_control_state("浏览工作目录按钮", lambda: panel.btn_browse_cwd.setEnabled(can_edit_step))
    panel._safe_update_control_state("依赖快捷按钮", lambda: panel.btn_dep_quick.setEnabled(can_edit_step))
    panel._safe_update_control_state("阶段下拉框", lambda: panel.combo_stage.setEnabled(can_edit_step))

    # 高级设置：可见但写操作禁用（避免误操作）
    panel.advanced.setEnabled(can_edit_step)
    panel._safe_update_control_state(
        "高级设置",
        lambda: (
            panel.combo_type.setEnabled(can_edit_step),
            panel.edit_args.setReadOnly(not can_edit_step),
            panel.edit_saved_run_args.setReadOnly(not can_edit_step),
            panel.edit_output_paths.setReadOnly(not can_edit_step),
            panel.edit_cwd.setReadOnly(not can_edit_step),
            panel.edit_theme.setReadOnly(not can_edit_step),
            panel.edit_timeout.setReadOnly(not can_edit_step),
            panel.edit_retry.setReadOnly(not can_edit_step),
            panel.check_gate.setEnabled(can_edit_step),
            panel.check_skip_on_success.setEnabled(can_edit_step),
            panel.dep_list.setEnabled(can_edit_step),
            panel.combo_target_workflow.setEnabled(can_edit_step),
        ),
    )
    panel._safe_update_control_state("更多按钮", lambda: panel.btn_more.setEnabled(has_step))
    panel._safe_update_control_state(
        "运行按钮",
        lambda: (
            panel.btn_run_only_step.setEnabled(has_step),
            panel.btn_run_from_step.setEnabled(has_step),
        ),
    )
    panel._safe_update_control_state(
        "删除按钮",
        lambda: (
            panel.btn_delete.setVisible(has_step),
            panel.btn_delete.setEnabled(can_edit_step),
        ),
    )
    panel._update_action_tooltips()
