# -*- coding: utf-8 -*-
"""步骤详情编辑器"""

import logging

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QPushButton,
    QToolButton,
    QFileDialog,
    QMessageBox,
    QListWidgetItem,
    QLabel,
    QMenu,
    QStyle,
    QScrollArea,
    QSizePolicy,
)
import json
from PySide6.QtCore import Signal, Slot, Qt, QTimer

from config import StepType
from database import (
    get_session, update_step, get_steps_by_workflow,
    list_workflows, update_recent_workflow,
    has_cross_workflow_cycle, list_stages, get_stage_order_map,
    get_step_by_id
)
from models import Step
from ui import step_editor_build, step_editor_io
from ui.collapsible_section import CollapsibleSection
from ui.step_editor_sections import (
    create_advanced_settings_section,
    create_dependency_summary_section,
)
from ui.theme import (
    COLORS,
    get_colors,
    get_menu_stylesheet,
    get_danger_button_stylesheet,
    msg_warning,
    msg_critical,
    msg_question,
)

logger = logging.getLogger(__name__)


class StepEditorPanel(QWidget):
    """步骤详情编辑器"""
    
    # 信号
    step_saved = Signal()
    step_delete_requested = Signal(int)
    step_run_requested = Signal(str, int)  # mode, step_id
    navigate_to_step = Signal(int)  # step_id（用于依赖摘要定位）
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = False
        self._step_id = None
        self._single_script_mode = False
        self._workflow_targets = []
        self._current_target_uid = None  # 当前选中的子工作流 UID
        self._current_workflow_id = None  # 当前步骤所属的工作流 ID
        self._edit_enabled = False
        self._parallel_available = True
        self._type_manual_override = False
        self._suppress_type_override = False
        self._prev_step_uid = None
        self._extra_sections_visible = False
        # #5: 脏标记 + 加载/保存抑制旗——加载时禁止 _mark_dirty 误置 True
        self._is_dirty = False
        self._suppress_dirty = False
        # 防抖定时器（依赖预览刷新）
        self._dep_refresh_timer = QTimer(self)
        self._dep_refresh_timer.setSingleShot(True)
        self._dep_refresh_timer.setInterval(300)
        self._dep_refresh_timer.timeout.connect(self._do_refresh_dependency_preview)
        self._setup_ui()
        # #5: setup 完成后再接脏检测，避免初始化期间 setValue/setText 触发
        self._connect_dirty_tracking()
    
    def _setup_ui(self):
        """设置 UI（实现在 ui.step_editor_build）"""
        step_editor_build.setup_ui(self)

    def refresh_theme(self, dark: bool):
        self._dark = dark
        colors = get_colors(dark)
        self.section.refresh_theme(dark)
        self.dep_summary.refresh_theme(dark)
        self.advanced.refresh_theme(dark)
        # 任务10：刷新 mini DAG 主题
        if hasattr(self, "mini_dag"):
            self.mini_dag.refresh_theme(dark)
        self._more_menu.setStyleSheet(get_menu_stylesheet(dark))
        self._refresh_context_banner_style(colors)
        # V9.2：刷新空状态分隔线（原硬编码 #E4E4E7，主题切换不刷新）
        if hasattr(self, "empty_sep"):
            self.empty_sep.setStyleSheet(f"background: {colors['border']}; margin: 8px 0;")
        self.btn_delete.setStyleSheet(get_danger_button_stylesheet(dark, radius=10, padding="0px 14px"))
        self.dep_inline_hint.setStyleSheet(f"color:{colors['warning']}; font-size:11px;")
        self.dep_warning.setStyleSheet(f"color:{colors['warning']}; font-size:11px;")
        self._dep_lists.setStyleSheet(f"""
            QLabel {{ color:{colors['text_secondary']}; font-size:11px; font-weight:600; }}
            QListWidget {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
            }}
            QListWidget::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid {colors['border']};
                border-radius: 4px;
                background: {colors['background']};
            }}
            QListWidget::indicator:checked {{
                background: {colors['primary']};
                border: 1px solid {colors['primary']};
            }}
            QListWidget::item {{ padding: 6px 8px; }}
            QListWidget::item:selected {{ background: {colors['selected_bg']}; }}
        """)
        self._dep_summary_hint.setStyleSheet(f"color:{colors['text_tertiary']}; font-size:11px;")
        indicator_bg = colors['background']
        indicator_border = colors['border']
        self.dep_list.setStyleSheet(f"""
            QListWidget::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid {indicator_border};
                border-radius: 4px;
                background: {indicator_bg};
            }}
            QListWidget::indicator:checked {{
                background: {colors['primary']};
                border: 1px solid {colors['primary']};
            }}
        """)
        self._update_action_tooltips()

    def _refresh_context_banner_style(self, colors: dict):
        self.context_banner.setStyleSheet(
            f"""
            QLabel {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
                padding: 5px 8px;
                color: {colors['text_secondary']};
                font-size: 11px;
            }}
            """
        )

    def _set_context_banner(self, text: str):
        self.context_banner.setText(text)

    def show_empty_state(self, workflow_id):
        """任务4：未选中步骤时展示工作流摘要 + 快捷键 + 最近运行 + 新建按钮"""
        self.show_empty_context()
        if workflow_id is None:
            self.empty_summary.setText("未选择工作流")
            self.empty_stats.setText("从左侧列表选择一个工作流开始")
            self.empty_last_run.setText("")
            self.btn_empty_new_step.setEnabled(False)
            return
        try:
            from database import get_latest_run_history
            steps = get_steps_by_workflow(workflow_id)
            stages = list_stages(workflow_id)
            last_run = get_latest_run_history(workflow_id)
        except Exception:
            steps, stages, last_run = [], [], None
        self.empty_summary.setText("工作流摘要")
        self.empty_stats.setText(f"{len(stages)} 阶段 · {len(steps)} 步")
        if last_run is not None:
            status_map = {"success": "成功", "failure": "失败", "cancelled": "已取消", "running": "运行中"}
            raw = getattr(last_run, "status", "") or ""
            status = status_map.get(raw, raw)
            started = getattr(last_run, "start_time", "") or ""
            self.empty_last_run.setText(f"最近运行：{status} · {started}")
        else:
            self.empty_last_run.setText("最近运行：无")
        self.btn_empty_new_step.setEnabled(self._edit_enabled)

    def show_step_context(self):
        """任务4：选中步骤时隐藏空白状态，显示步骤编辑器"""
        self.empty_state_widget.hide()
        self.context_banner.show()

    def show_empty_context(self):
        """任务4：未选中步骤时显示空白状态"""
        self.empty_state_widget.show()
        self.context_banner.hide()

    def _update_action_tooltips(self):
        can_edit = self._edit_enabled and (not self._single_script_mode)
        has_step = self._step_id is not None
        self.btn_more.setToolTip("更多操作：高级设置、依赖摘要" if has_step else "请先选中一个步骤")
        self.btn_save.setToolTip("保存当前步骤配置" if can_edit and has_step else "保存当前步骤配置（需要先选中步骤并开启编辑）")
        self.btn_delete.setToolTip("删除当前步骤" if can_edit and has_step else "删除当前步骤（需要先选中步骤并开启编辑）")
        self.btn_browse.setToolTip("浏览并选择脚本或文件" if can_edit and has_step else "浏览脚本或文件（需要先选中步骤并开启编辑）")
        self.btn_browse_cwd.setToolTip("浏览并选择工作目录" if can_edit and has_step else "浏览工作目录（需要先选中步骤并开启编辑）")
        self.btn_dep_quick.setToolTip("点击快速设置上游依赖：无 / 依赖上一步 / 自定义" if can_edit and has_step else "上游依赖快速设置（需要先选中步骤并开启编辑）")
        self.btn_run_only_step.setToolTip("只运行当前选中的步骤" if has_step else "只运行此步骤（需要先选中步骤）")
        self.btn_run_from_step.setToolTip("从当前步骤开始运行后续步骤" if has_step else "从此步骤开始（需要先选中步骤）")

    def _stage_label_for_step(self, step: Step) -> str:
        try:
            stages = list_stages(step.workflow_id)
        except Exception:
            stages = []
        stage_uid_to_label = {st.uid: f"S{i + 1} {st.name}" for i, st in enumerate(stages)}
        return stage_uid_to_label.get(getattr(step, "stage_uid", None), "未分配阶段")

    def _request_delete_step(self):
        if self._step_id is None:
            return
        self.step_delete_requested.emit(int(self._step_id))

    def _request_step_run(self, mode: str):
        if self._step_id is None:
            return
        self.step_run_requested.emit(mode, int(self._step_id))

    def set_single_script_mode(self, enabled: bool):
        """设置单脚本模式"""
        self._single_script_mode = enabled
        self._apply_enabled_state()

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = enabled
        self._apply_enabled_state()
        # 任务4：空白状态的新建步骤按钮跟随编辑模式联动
        if hasattr(self, "btn_empty_new_step"):
            self.btn_empty_new_step.setEnabled(enabled and self._step_id is None)

    def set_parallel_available(self, enabled: bool):
        self._parallel_available = enabled
        self._apply_enabled_state()

    def _safe_update_control_state(self, label: str, update) -> None:
        try:
            update()
        except Exception:
            logger.warning("更新步骤编辑器控件状态失败: %s", label, exc_info=True)

    def _apply_enabled_state(self):
        can_edit = self._edit_enabled and (not self._single_script_mode)
        has_step = self._step_id is not None
        can_edit_step = can_edit and has_step
        # 编辑模式只做「写操作门禁」，不应让用户无法查看/复制字段内容
        self.section.setEnabled(True)
        self.section.set_collapsed(False)
        self.btn_save.setEnabled(can_edit_step)

        # 基础字段：只读/可编辑
        self._safe_update_control_state(
            "基础字段",
            lambda: (
                self.edit_name.setReadOnly(not can_edit_step),
                self.edit_script.setReadOnly(not can_edit_step),
            ),
        )
        self._safe_update_control_state("浏览脚本按钮", lambda: self.btn_browse.setEnabled(can_edit_step))
        self._safe_update_control_state("浏览工作目录按钮", lambda: self.btn_browse_cwd.setEnabled(can_edit_step))
        self._safe_update_control_state("依赖快捷按钮", lambda: self.btn_dep_quick.setEnabled(can_edit_step))
        self._safe_update_control_state("阶段下拉框", lambda: self.combo_stage.setEnabled(can_edit_step))

        # 高级设置：可见但写操作禁用（避免误操作）
        self.advanced.setEnabled(can_edit_step)
        self._safe_update_control_state(
            "高级设置",
            lambda: (
                self.combo_type.setEnabled(can_edit_step),
                self.edit_args.setReadOnly(not can_edit_step),
                self.edit_saved_run_args.setReadOnly(not can_edit_step),
                self.edit_output_paths.setReadOnly(not can_edit_step),
                self.edit_cwd.setReadOnly(not can_edit_step),
                self.edit_theme.setReadOnly(not can_edit_step),
                self.edit_timeout.setReadOnly(not can_edit_step),
                self.edit_retry.setReadOnly(not can_edit_step),
                self.check_gate.setEnabled(can_edit_step),
                self.check_skip_on_success.setEnabled(can_edit_step),
                self.dep_list.setEnabled(can_edit_step),
                self.combo_target_workflow.setEnabled(can_edit_step),
            ),
        )
        self._safe_update_control_state("更多按钮", lambda: self.btn_more.setEnabled(has_step))
        self._safe_update_control_state(
            "运行按钮",
            lambda: (
                self.btn_run_only_step.setEnabled(has_step),
                self.btn_run_from_step.setEnabled(has_step),
            ),
        )
        self._safe_update_control_state(
            "删除按钮",
            lambda: (
                self.btn_delete.setVisible(has_step),
                self.btn_delete.setEnabled(can_edit_step),
            ),
        )
        self._update_action_tooltips()

    def _on_gate_state_changed(self, _state: int):
        # 自动并行语义下，「检查点」仅用于强制关键步骤单独执行；这里无需联动并行开关
        return

    def _auto_detect_type_from_script(self):
        """根据脚本/文件后缀自动识别步骤类型（可在高级设置中手动覆盖）"""
        if self._type_manual_override:
            return
        current = self.combo_type.currentData()
        if current == "sub_workflow":
            return

        path = (self.edit_script.text() or "").strip().lower()
        if not path:
            return

        detected = None
        if path.endswith(".py"):
            detected = "python"
        elif path.endswith((".xlsx", ".xlsm", ".xlsb", ".xls")):
            detected = "excel_powerquery"
        elif path.endswith(".pbix"):
            detected = "powerbi_refresh"

        if not detected or detected == current:
            return

        idx = self.combo_type.findData(detected)
        if idx < 0:
            return

        self._suppress_type_override = True
        try:
            self.combo_type.setCurrentIndex(idx)
        finally:
            self._suppress_type_override = False
        # 仍允许后续继续自动识别
        self._type_manual_override = False

    def _refresh_prev_dep_quick_toggle(self, step: Step):
        """根据当前步骤 order 计算「上一执行步骤」，用于依赖快捷菜单"""
        self._prev_step_uid = None

        # 与「执行阶段顺序 + step.order」的展示/执行心智一致：上一「执行步骤」应基于该顺序计算
        try:
            stage_map = get_stage_order_map(step.workflow_id)
        except Exception:
            stage_map = {}

        def _purpose_stage_order(s):
            return int(stage_map.get(getattr(s, "stage_uid", None), 0) or 0)

        steps = sorted(get_steps_by_workflow(step.workflow_id), key=lambda s: (_purpose_stage_order(s), s.order))
        current_idx = None
        for i, s in enumerate(steps):
            if s.id == step.id:
                current_idx = i
                break
        if current_idx is None or current_idx == 0:
            return

        prev_step = steps[current_idx - 1]
        self._prev_step_uid = prev_step.uid

    def _show_dep_quick_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(get_menu_stylesheet(self._dark))
        act_none = menu.addAction("（无）")
        act_prev = menu.addAction("依赖上一步")
        menu.addSeparator()
        act_custom = menu.addAction("自定义依赖…")

        if not self._prev_step_uid:
            act_prev.setEnabled(False)

        chosen = menu.exec_(self.btn_dep_quick.mapToGlobal(self.btn_dep_quick.rect().bottomLeft()))
        if not chosen:
            return
        if chosen == act_none:
            self._set_dep_quick_mode("none")
        elif chosen == act_prev:
            self._set_dep_quick_mode("prev")
        elif chosen == act_custom:
            # 防御：高级设置默认隐藏；选择「自定义依赖」时需自动展开并显示依赖多选列表
            if not self._extra_sections_visible:
                self._extra_sections_visible = True
                self.dep_summary.setVisible(True)
                self.advanced.setVisible(True)
                self._act_toggle_details.setText("隐藏高级设置")
            self.advanced.set_collapsed(False)
            self._notify_status("自定义上游依赖：请在下方「上游依赖」中勾选依赖项，然后点击保存。")
            # 展开后再滚动定位（让布局先完成），避免用户感觉「点了没反应」
            QTimer.singleShot(0, lambda: self._ensure_widget_visible(self.dep_list))
            try:
                self.dep_list.setFocus()
            except Exception:
                pass

    def _set_dep_quick_mode(self, mode: str):
        """快捷设置依赖（通过高级依赖多选列表落地，保持能力一致）"""
        if mode == "none":
            for i in range(self.dep_list.count()):
                self.dep_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        elif mode == "prev" and self._prev_step_uid:
            for i in range(self.dep_list.count()):
                item = self.dep_list.item(i)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if item.data(Qt.ItemDataRole.UserRole) == self._prev_step_uid
                    else Qt.CheckState.Unchecked
                )
        self._refresh_dep_quick_text()
        self._refresh_dependency_preview()

    def _refresh_dep_quick_text(self):
        deps = []
        for i in range(self.dep_list.count()):
            it = self.dep_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                deps.append(it.data(Qt.ItemDataRole.UserRole))
        if not deps:
            self.btn_dep_quick.setText("(无) ▾")
        elif self._prev_step_uid and deps == [self._prev_step_uid]:
            self.btn_dep_quick.setText("上一步 ▾")
        else:
            self.btn_dep_quick.setText(f"{len(deps)} 项 ▾")

    def _notify_status(self, message: str):
        try:
            win = self.window()
            if win and hasattr(win, "statusBar"):
                sb = win.statusBar()
                if sb:
                    sb.showMessage(message, 5000)
        except Exception:
            return

    def _get_selected_dep_uids_from_ui(self) -> list[str]:
        deps: list[str] = []
        for i in range(self.dep_list.count()):
            it = self.dep_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                uid = it.data(Qt.ItemDataRole.UserRole)
                if uid:
                    deps.append(str(uid))
        return deps

    def _refresh_dependency_preview(self):
        """当 UI 中依赖选择发生变化时，启动防抖定时器刷新预览。"""
        self._dep_refresh_timer.start()

    def _do_refresh_dependency_preview(self):
        """防抖后的实际刷新"""
        if self._step_id is None:
            return
        try:
            sid = int(self._step_id)
        except (ValueError, TypeError):
            return
        try:
            with get_session() as session:
                step = session.query(Step).filter(Step.id == sid).first()
                if not step:
                    return
                self._refresh_dependency_summary(step, override_dep_uids=self._get_selected_dep_uids_from_ui())
        except Exception as exc:
            logger.warning("刷新依赖预览失败: step_id=%s", sid, exc_info=True)
            self._show_dependency_preview_error(f"依赖预览刷新失败：{exc}")

    def _show_dependency_preview_error(self, message: str) -> None:
        try:
            self.dep_warning.setText(message)
            self.dep_summary.setVisible(True)
            self.dep_summary.set_collapsed(False)
        except Exception:
            logger.warning("显示依赖预览错误失败", exc_info=True)

    def _ensure_widget_visible(self, widget: QWidget):
        """尽量把某个控件滚动到可见（用于「自定义依赖」后把依赖多选列表带到视口内）。"""
        try:
            win = self.window()
            scroll = getattr(win, "center_scroll", None)
            if scroll and hasattr(scroll, "ensureWidgetVisible"):
                scroll.ensureWidgetVisible(widget)
                return
            # 兜底：在更深层布局/嵌套滚动场景下，向上找最近的 QScrollArea
            p = self.parentWidget()
            while p:
                if isinstance(p, QScrollArea):
                    p.ensureWidgetVisible(widget)
                    break
                p = p.parentWidget()
        except Exception:
            pass

    def _toggle_extra_sections(self):
        self._extra_sections_visible = not self._extra_sections_visible
        self.dep_summary.setVisible(self._extra_sections_visible)
        self.advanced.setVisible(self._extra_sections_visible)
        self._act_toggle_details.setText("隐藏高级设置" if self._extra_sections_visible else "显示高级设置")

    def _show_dep_summary(self):
        self.dep_summary.setVisible(True)
        self.dep_summary.set_collapsed(False)
    
    def load_step(self, step_id: int):
        """加载步骤（实现在 ui.step_editor_io）"""
        step_editor_io.load_step(self, step_id)

    def _load_dependencies(self, step: Step):
        """加载上游依赖步骤列表（实现在 ui.step_editor_io）"""
        step_editor_io.load_dependencies(self, step)

    def _emit_navigate_from_item(self, item: QListWidgetItem):
        try:
            step_id = item.data(Qt.UserRole)
            if step_id:
                self.navigate_to_step.emit(int(step_id))
        except Exception:
            return

    def _refresh_dependency_summary(self, step: Step, *, override_dep_uids: list[str] | None = None):
        """刷新依赖摘要（只读展示 + 定位）

        override_dep_uids:
          - 用于 UI 预览（未保存前也能看到「已选依赖」）
          - 不改变数据库中 step.depends_on
        """
        self.list_depends_on.clear()
        self.list_dependents.clear()
        self.dep_warning.setVisible(False)
        self.dep_warning.setText("")

        steps = get_steps_by_workflow(step.workflow_id)
        by_uid = {s.uid: s for s in steps}
        by_id = {s.id: s for s in steps}

        depends_uids = list(override_dep_uids if override_dep_uids is not None else (step.get_depends_on() or []))
        depends_steps = [by_uid.get(uid) for uid in depends_uids if by_uid.get(uid)]
        dependents = [s for s in steps if step.uid in set(s.get_depends_on() or [])]

        # 执行阶段标签（用于 tooltip）
        try:
            from database import list_stages, get_stage_order_map
            stages = list_stages(step.workflow_id)
            stage_uid_to_label = {st.uid: f"S{i + 1} {st.name}" for i, st in enumerate(stages)}
            stage_order = get_stage_order_map(step.workflow_id)
        except Exception:
            stage_uid_to_label = {}
            stage_order = {}

        def _label_for(s: Step) -> str:
            suid = getattr(s, "stage_uid", None)
            return stage_uid_to_label.get(suid, "")

        # 「我依赖的步骤」
        if not depends_steps:
            item = QListWidgetItem("（无显式依赖）")
            item.setFlags(Qt.ItemIsEnabled)
            self.list_depends_on.addItem(item)
        else:
            for s in sorted(depends_steps, key=lambda x: x.order):
                it = QListWidgetItem(f"{s.order + 1}. {s.name}")
                it.setData(Qt.UserRole, s.id)
                tip = _label_for(s)
                if tip:
                    it.setToolTip(f"{tip}\nuid={s.uid}")
                self.list_depends_on.addItem(it)

        # 「依赖我的步骤」
        if not dependents:
            item = QListWidgetItem("（暂无步骤依赖我）")
            item.setFlags(Qt.ItemIsEnabled)
            self.list_dependents.addItem(item)
        else:
            for s in sorted(dependents, key=lambda x: x.order):
                it = QListWidgetItem(f"{s.order + 1}. {s.name}")
                it.setData(Qt.UserRole, s.id)
                tip = _label_for(s)
                if tip:
                    it.setToolTip(f"{tip}\nuid={s.uid}")
                self.list_dependents.addItem(it)

        # 轻量校验提示：依赖未来阶段（严格规则）
        try:
            cur_stage = int(stage_order.get(getattr(step, "stage_uid", None), 0) or 0)
            bad = []
            for uid in depends_uids:
                dep = by_uid.get(uid)
                if not dep:
                    continue
                dep_stage = int(stage_order.get(getattr(dep, "stage_uid", None), 0) or 0)
                if dep_stage > cur_stage:
                    bad.append(dep.name)
            if bad:
                self.dep_warning.setText(
                    "当前上游依赖包含「未来阶段」的步骤（运行/保存阶段顺序时将被阻止）："
                    + "、".join(bad[:6])
                    + ("…" if len(bad) > 6 else "")
                )
                self.dep_warning.setVisible(True)
        except Exception:
            pass

        # 默认收起，但一旦出现风险提示则自动展开，确保问题可见
        has_warn = self.dep_warning.isVisible() and (self.dep_warning.text() or "").strip()
        self.dep_inline_hint.setVisible(bool(has_warn))
        self.dep_inline_hint.setText("⚠ 需调整" if has_warn else "")
        if has_warn:
            self.dep_summary.setVisible(True)
            self.dep_summary.set_collapsed(False)

        # 任务10：同步刷新 mini DAG
        if hasattr(self, "mini_dag"):
            self.mini_dag.set_data(step, depends_steps, dependents)
    
    def clear(self):
        """清空表单"""
        # #5: 清空属于"非用户编辑"，抑制脏标记
        self._suppress_dirty = True
        try:
            self._step_id = None
            self.edit_name.clear()
            self._type_manual_override = False
            self._suppress_type_override = True
            try:
                self.combo_type.setCurrentIndex(0)
            finally:
                self._suppress_type_override = False
            self._suppress_type_override = True
            try:
                self._on_type_changed()
            finally:
                self._suppress_type_override = False
            self.edit_script.clear()
            self.edit_args.clear()
            self.edit_saved_run_args.clear()
            self.edit_output_paths.clear()
            self.edit_cwd.clear()
            self.edit_theme.clear()
            self.edit_timeout.setValue(0)
            self.edit_retry.setValue(0)
            self.check_gate.setChecked(False)
            self.btn_dep_quick.setText("(无) ▾")
            self.dep_inline_hint.setVisible(False)
            self.dep_inline_hint.setText("")
            self.combo_stage.clear()
            self.check_skip_on_success.setChecked(False)
            self.dep_list.clear()
            self.list_depends_on.clear()
            self.list_dependents.clear()
            self.dep_warning.setVisible(False)
            self.dep_warning.setText("")
            self.dep_summary.set_collapsed(True)
            self.dep_summary.setVisible(False)
            self.advanced.setVisible(False)
            self._extra_sections_visible = False
            self._act_toggle_details.setText("显示高级设置")
            self._set_context_banner("未选中步骤。点击步骤可在此编辑；先点击阶段再点「添加步骤」，新步骤会默认进入该阶段。")
            self.combo_target_workflow.clear()
            self.edit_target_search.clear()
            self.combo_target_scope.setCurrentIndex(0)
            self._apply_enabled_state()
            # 任务4：clear 后显示空白状态（context_banner 隐藏，empty_state_widget 显示）
            self.show_empty_context()
            # 任务10：clear 后清空 mini DAG
            if hasattr(self, "mini_dag"):
                self.mini_dag.set_data(None, [], [])
        finally:
            self._suppress_dirty = False
        # clear 完毕复位脏标记
        self.reset_dirty_state()
    
    @Slot()
    def save_step(self) -> bool:
        """保存步骤

        R2-#2: 返回 bool。所有验证失败/异常分支返回 False，让外层（如未保存确认对话框）
        可以据此判断是否允许继续切换。
        """
        if not self._step_id:
            return False

        # 验证固定参数与已保存运行参数格式
        args_text = self.edit_args.text().strip()
        saved_run_args_text = self.edit_saved_run_args.text().strip()
        if args_text:
            try:
                args = json.loads(args_text)
                if not isinstance(args, list):
                    raise ValueError("参数必须是数组")
            except (json.JSONDecodeError, ValueError) as e:
                msg_warning(
                    self,
                    self._dark,
                    "参数格式错误",
                    f"固定参数必须是有效的 JSON 数组\n{e}",
                )
                return False
        if saved_run_args_text:
            try:
                saved_run_args = json.loads(saved_run_args_text)
                if not isinstance(saved_run_args, list) or not all(
                    isinstance(arg, str) for arg in saved_run_args
                ):
                    raise ValueError("保存运行参数必须是字符串数组")
            except (json.JSONDecodeError, ValueError) as e:
                msg_warning(
                    self,
                    self._dark,
                    "参数格式错误",
                    f"保存运行参数必须是有效的 JSON 字符串数组\n{e}",
                )
                return False

        # 验证超时时间（U-P2-5: QSpinBox 已限制 0..86400；M9: 0 落库为 NULL，由执行器按类型应用默认超时）
        timeout_value = int(self.edit_timeout.value())
        timeout = timeout_value if timeout_value > 0 else None

        # 验证重试次数（U-P2-5: QSpinBox 已限制 0..99）
        retry = int(self.edit_retry.value())

        # 更新步骤
        step_type = self.combo_type.currentData()
        script_path = self.edit_script.text().strip()
        if step_type == "sub_workflow":
            uid = self.combo_target_workflow.currentData()
            if not uid:
                msg_warning(self, self._dark, "输入错误", "请选择目标工作流")
                return False
            if not self._validate_sub_workflow_cycle(uid):
                return False
            script_path = uid
        else:
            # 非子工作流类型需要检查脚本路径
            if not script_path:
                msg_warning(self, self._dark, "输入错误", "请输入脚本路径")
                return False

        # 验证脚本路径存在性：允许跨机器同步场景，但必须由用户显式确认。
        import os
        if script_path and step_type != "sub_workflow":
            if not os.path.exists(script_path):
                reply = msg_question(
                    self, self._dark,
                    "路径提示",
                    f"脚本路径不存在：\n{script_path}\n\n仍要保存这个配置吗？",
                )
                if reply != QMessageBox.Yes:
                    return False

        deps = []
        for i in range(self.dep_list.count()):
            item = self.dep_list.item(i)
            if item.checkState() == Qt.Checked:
                deps.append(item.data(Qt.UserRole))

        # ROI-2: 显式输出声明，分号分隔；留空保存为 NULL（监听冲突检测回退到推断）
        output_paths = [p.strip() for p in self.edit_output_paths.text().split(";") if p.strip()]

        try:
            update_step(
                self._step_id,
                name=self.edit_name.text().strip(),
                step_type=step_type,
                script_path=script_path,
                args=args_text if args_text else None,
                saved_run_args=saved_run_args_text if saved_run_args_text else None,
                cwd=self.edit_cwd.text().strip() or None,
                chart_theme=self.edit_theme.text().strip() or None,
                timeout_seconds=timeout,
                retry_count=retry,
                is_gate=self.check_gate.isChecked(),
                skip_on_success=self.check_skip_on_success.isChecked(),
                depends_on=json.dumps(deps, ensure_ascii=False) if deps else None,
                output_paths=json.dumps(output_paths, ensure_ascii=False) if output_paths else None,
                stage_uid=self.combo_stage.currentData() if self.combo_stage.count() else None,
            )
        except Exception as e:
            msg_critical(self, self._dark, "保存失败", str(e))
            return False
        if step_type == "sub_workflow" and script_path:
            update_recent_workflow(script_path)

        # #5: 保存成功后复位脏标记
        self.reset_dirty_state()
        self._notify_status("已保存步骤配置。")
        self.step_saved.emit()
        return True

    # ==================== #5 脏标记 ====================
    def is_dirty(self) -> bool:
        """是否有未保存的编辑"""
        return self._is_dirty and self._step_id is not None

    def reset_dirty_state(self) -> None:
        self._is_dirty = False

    def discard_changes(self) -> None:
        if self._step_id:
            self.load_step(self._step_id)
            return
        self.clear()

    def _mark_dirty(self, *_args, **_kwargs):
        """所有可编辑控件信号都接到这里"""
        if self._suppress_dirty:
            return
        self._is_dirty = True

    def _connect_dirty_tracking(self) -> None:
        """把可编辑控件的变化信号都接到 _mark_dirty。
        signal 调用时机各异（textChanged / valueChanged / stateChanged / currentIndexChanged 等），
        统一变体签名用 *args / **kwargs 容忍。
        """
        # 文本输入
        for w in (
            self.edit_name,
            self.edit_script,
            self.edit_args,
            self.edit_saved_run_args,
            self.edit_output_paths,
            self.edit_cwd,
            self.edit_theme,
        ):
            try:
                w.textChanged.connect(self._mark_dirty)
            except Exception:
                pass
        # 数值
        for w in (self.edit_timeout, self.edit_retry):
            try:
                w.valueChanged.connect(self._mark_dirty)
            except Exception:
                pass
        # 复选
        for w in (self.check_gate, self.check_skip_on_success):
            try:
                w.stateChanged.connect(self._mark_dirty)
            except Exception:
                pass
        # 下拉
        for w in (self.combo_type, self.combo_stage, self.combo_target_workflow):
            try:
                w.currentIndexChanged.connect(self._mark_dirty)
            except Exception:
                pass
        # 依赖列表 itemChanged 覆盖勾选变化
        try:
            self.dep_list.itemChanged.connect(self._mark_dirty)
        except Exception:
            pass
    
    def _reset(self):
        """重置表单"""
        if self._step_id:
            self.load_step(self._step_id)
    
    def _browse_script(self):
        """浏览脚本文件"""
        step_type = self.combo_type.currentData()
        if step_type == "sub_workflow":
            return
        
        if step_type == "python":
            filter_str = "Python Files (*.py);;All Files (*)"
        elif step_type == "bat":
            filter_str = "Batch Files (*.bat *.cmd);;All Files (*)"
        elif step_type == "excel_powerquery":
            filter_str = "Excel Files (*.xlsx *.xlsm *.xlsb);;All Files (*)"
        elif step_type == "powerbi_refresh":
            filter_str = "Power BI Files (*.pbix);;All Files (*)"
        else:
            filter_str = "All Files (*)"
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "", filter_str
        )
        
        if file_path:
            self.edit_script.setText(file_path)
            self._auto_detect_type_from_script()
    
    def _browse_cwd(self):
        """浏览工作目录"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择工作目录"
        )
        
        if dir_path:
            self.edit_cwd.setText(dir_path)

    def _load_workflow_targets(self, current_uid: str = None):
        """加载可选的子工作流列表（实现在 ui.step_editor_io）"""
        step_editor_io.load_workflow_targets(self, current_uid)

    def _refresh_target_options(self, text: str = ""):
        """刷新目标工作流下拉选项（实现在 ui.step_editor_io）"""
        step_editor_io.refresh_target_options(self, text)

    def _on_type_changed(self):
        """步骤类型变更时更新 UI"""
        if (not self._suppress_type_override) and (self._step_id is not None):
            self._type_manual_override = True

        step_type = self.combo_type.currentData()
        is_sub = step_type == "sub_workflow"
        
        # 切换脚本行和子工作流选择行的可见性
        self.script_label.setVisible(not is_sub)
        self.script_row.setVisible(not is_sub)
        self.target_workflow_row.setVisible(is_sub)
        self.sub_workflow_filter_widget.setVisible(is_sub)
        
        # 子工作流类型时隐藏工作目录（子工作流不需要）
        self.label_cwd.setVisible(not is_sub)
        self.cwd_row.setVisible(not is_sub)
        
        if is_sub:
            # 确保工作流列表已加载
            if not self._workflow_targets:
                self._load_workflow_targets(self._current_target_uid)

    def _on_target_changed(self):
        """目标工作流变更时更新"""
        # 不再需要更新 edit_script，因为子工作流类型时使用下拉框
        pass

    def _validate_sub_workflow_cycle(self, target_uid: str) -> bool:
        with get_session() as session:
            step = session.query(Step).filter(Step.id == self._step_id).first()
            if not step:
                return False
            parent_id = step.workflow_id
        if has_cross_workflow_cycle(parent_id, target_uid):
            msg_warning(self, self._dark, "循环依赖", "检测到跨工作流循环依赖，请选择其他工作流")
            return False
        return True
