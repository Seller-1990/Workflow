# -*- coding: utf-8 -*-
"""步骤详情编辑器加载与目标工作流选项 IO（自 step_editor 纯移动提取，行为不变）。

每个函数的首个参数 ``panel`` 即 StepEditorPanel 实例；跨方法调用一律走
``panel._xxx`` 委托方法，保持原有动态分发语义。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from database import (
    get_step_by_id,
    get_steps_by_workflow,
    list_stages,
    list_workflows,
)
from models import Step


def load_step(panel, step_id: int):
    """加载步骤"""
    # #5: 加载属于"非用户编辑"，全程抑制脏标记
    panel._suppress_dirty = True
    try:
        panel._step_id = step_id

        step = get_step_by_id(step_id)
        if not step:
            panel._suppress_dirty = False  # 让 clear 自己控制
            panel.clear()
            return

        # 保存当前工作流 ID（用于排除自引用）
        panel._current_workflow_id = step.workflow_id

        panel.edit_name.setText(step.name)

        # 设置步骤类型
        index = panel.combo_type.findData(step.step_type)
        if index >= 0:
            panel._suppress_type_override = True
            try:
                panel.combo_type.setCurrentIndex(index)
            finally:
                panel._suppress_type_override = False
        panel._type_manual_override = False

        panel.edit_script.setText(step.script_path or "")
        panel.edit_args.setText(step.args or "")
        # ROI-2: 显式输出声明用「; 」拼接展示，保存时按「;」拆分
        panel.edit_output_paths.setText("; ".join(str(p) for p in step.get_output_paths()))
        panel.edit_cwd.setText(step.cwd or "")
        panel.edit_theme.setText(step.chart_theme or "")
        panel.edit_timeout.setValue(int(step.timeout_seconds) if step.timeout_seconds else 0)
        panel.edit_retry.setValue(int(step.retry_count) if step.retry_count else 0)
        panel.check_gate.setChecked(step.is_gate)
        panel.check_skip_on_success.setChecked(getattr(step, 'skip_on_success', False))

        # 执行阶段
        panel.combo_stage.blockSignals(True)
        try:
            panel.combo_stage.clear()
            stages = list_stages(step.workflow_id)
            for idx, st in enumerate(stages, start=1):
                panel.combo_stage.addItem(f"S{idx} {st.name}", st.uid)
            suid = getattr(step, "stage_uid", None)
            if suid:
                i = panel.combo_stage.findData(suid)
                if i >= 0:
                    panel.combo_stage.setCurrentIndex(i)
        finally:
            panel.combo_stage.blockSignals(False)

        # 上游依赖列表
        panel._load_dependencies(step)
        panel.dep_summary.set_collapsed(True)
        panel._refresh_dependency_summary(step)
        panel._load_workflow_targets(step.script_path)
        stage_label = panel._stage_label_for_step(step)
        gate_text = " · 检查点" if step.is_gate else ""
        panel._set_context_banner(f"当前编辑：{step.name} · {stage_label}{gate_text}")
        panel._suppress_type_override = True
        try:
            panel._on_type_changed()
        finally:
            panel._suppress_type_override = False
        panel._refresh_prev_dep_quick_toggle(step)
        panel._refresh_dep_quick_text()
        panel._apply_enabled_state()
        # 任务4：加载步骤后切换到步骤上下文（隐藏空白状态）
        panel.show_step_context()
    finally:
        panel._suppress_dirty = False
    # load 完毕复位脏标记
    panel.reset_dirty_state()


def load_dependencies(panel, step: Step):
    """加载上游依赖步骤列表"""
    panel.dep_list.clear()
    steps = get_steps_by_workflow(step.workflow_id)
    selected = set(step.get_depends_on())
    for s in steps:
        if s.id == step.id:
            continue
        item = QListWidgetItem(f"{s.order + 1}. {s.name}")
        item.setData(Qt.UserRole, s.uid)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if s.uid in selected else Qt.Unchecked)
        panel.dep_list.addItem(item)
    panel._refresh_dep_quick_text()


def load_workflow_targets(panel, current_uid: str = None):
    """加载可选的子工作流列表"""
    workflows = list_workflows()
    # 排除当前步骤所属的工作流（避免自引用）
    panel._workflow_targets = [
        (wf.name, wf.uid) for wf in workflows
        if panel._current_workflow_id is None or wf.id != panel._current_workflow_id
    ]
    panel._current_target_uid = current_uid  # 保存当前选中的 UID
    panel._refresh_target_options()


def refresh_target_options(panel, text: str = ""):
    """刷新目标工作流下拉选项"""
    keyword = (text or "").strip().lower()
    scope = panel.combo_target_scope.currentData()
    recent_uids = set()
    if scope == "recent":
        from database import list_recent_workflows
        recent_uids = set(list_recent_workflows())

    panel.combo_target_workflow.blockSignals(True)  # 防止触发信号
    panel.combo_target_workflow.clear()

    for name, uid in panel._workflow_targets:
        if scope == "recent" and uid not in recent_uids:
            continue
        if keyword and keyword not in name.lower():
            continue
        panel.combo_target_workflow.addItem(name, uid)

    # 恢复选中状态
    if panel._current_target_uid:
        idx = panel.combo_target_workflow.findData(panel._current_target_uid)
        if idx >= 0:
            panel.combo_target_workflow.setCurrentIndex(idx)

    panel.combo_target_workflow.blockSignals(False)
