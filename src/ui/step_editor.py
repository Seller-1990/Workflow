# -*- coding: utf-8 -*-
"""步骤详情编辑器"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QTextEdit,
    QComboBox,
    QCheckBox,
    QPushButton,
    QToolButton,
    QFileDialog,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QGridLayout,
    QLabel,
    QMenu,
    QStyle,
    QScrollArea,
)
import json
from PySide6.QtCore import Signal, Slot, Qt, QTimer

from config import StepType
from database import (
    get_session, update_step, get_steps_by_workflow,
    list_workflows, update_recent_workflow,
    has_cross_workflow_cycle, list_stages, get_stage_order_map
)
from models import Step
from ui.collapsible_section import CollapsibleSection
from ui.theme import COLORS

class StepEditorPanel(QWidget):
    """步骤详情编辑器"""
    
    # 信号
    step_saved = Signal()
    navigate_to_step = Signal(int)  # step_id（用于依赖摘要定位）
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._step_id = None
        self._single_script_mode = False
        self._workflow_targets = []
        self._current_target_uid = None  # 当前选中的子工作流 UID
        self._current_workflow_id = None  # 当前步骤所属的工作流 ID
        self._edit_enabled = True
        self._parallel_available = True
        self._type_manual_override = False
        self._suppress_type_override = False
        self._prev_step_uid = None
        self._extra_sections_visible = False
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 卡片区块（iOS 极简一致性：与 DAG/运行历史相同的 CollapsibleSection）
        self.section = CollapsibleSection("步骤详情编辑器", collapsed=False)
        group_layout = self.section.body_layout

        # 右侧“更多”：默认隐藏高级区块，保持定稿 UI 的紧凑外观
        self.btn_more = QToolButton()
        self.btn_more.setAutoRaise(True)
        self.btn_more.setIcon(self.style().standardIcon(QStyle.SP_TitleBarMenuButton))
        self.btn_more.setToolTip("更多")
        self.section.header_actions_layout.addWidget(self.btn_more)

        self._more_menu = QMenu(self)
        self._act_toggle_details = self._more_menu.addAction("显示高级设置")
        self._act_toggle_details.triggered.connect(self._toggle_extra_sections)
        self._act_show_dep = self._more_menu.addAction("查看依赖摘要")
        self._act_show_dep.triggered.connect(self._show_dep_summary)
        self.btn_more.setMenu(self._more_menu)
        self.btn_more.setPopupMode(QToolButton.InstantPopup)
        # ── 基础信息（按 Pencil：nameRow / depRow 同行） ──
        basic_widget = QWidget()
        basic_layout = QVBoxLayout(basic_widget)
        basic_layout.setContentsMargins(0, 0, 0, 0)
        basic_layout.setSpacing(10)

        # Row 0: 步骤名称 + 脚本路径（同一行）
        name_row = QWidget()
        name_row_layout = QHBoxLayout(name_row)
        name_row_layout.setContentsMargins(0, 0, 0, 0)
        name_row_layout.setSpacing(10)

        name_row_layout.addWidget(QLabel("步骤名称"))
        self.edit_name = QLineEdit()
        self.edit_name.setFixedSize(180, 32)
        name_row_layout.addWidget(self.edit_name)

        # 脚本路径行（非子工作流类型使用）
        self.script_label = QLabel("脚本路径")
        name_row_layout.addWidget(self.script_label)

        script_layout = QHBoxLayout()
        script_layout.setContentsMargins(0, 0, 0, 0)
        script_layout.setSpacing(8)
        self.edit_script = QLineEdit()
        self.edit_script.setFixedHeight(32)
        self.edit_script.setPlaceholderText("选择脚本或文件路径…")
        self.edit_script.editingFinished.connect(self._auto_detect_type_from_script)
        script_layout.addWidget(self.edit_script, stretch=1)
        self.btn_browse = QPushButton("浏览")
        self.btn_browse.setFixedSize(64, 32)
        self.btn_browse.setToolTip("浏览脚本/文件")
        self.btn_browse.clicked.connect(self._browse_script)
        script_layout.addWidget(self.btn_browse)
        self.script_row = QWidget()
        self.script_row.setLayout(script_layout)
        name_row_layout.addWidget(self.script_row, stretch=1)

        # 子工作流选择行（子工作流类型使用，与脚本行同位置）
        self.sub_workflow_label = QLabel("目标工作流")
        self.combo_target_workflow = QComboBox()
        self.combo_target_workflow.setFixedHeight(32)
        self.combo_target_workflow.currentIndexChanged.connect(self._on_target_changed)
        self.sub_workflow_label.setVisible(False)
        self.combo_target_workflow.setVisible(False)
        name_row_layout.addWidget(self.sub_workflow_label)
        name_row_layout.addWidget(self.combo_target_workflow, stretch=1)

        basic_layout.addWidget(name_row)

        # Row 1: 前置依赖 + 执行阶段（同一行）
        dep_row = QWidget()
        dep_row_layout = QHBoxLayout(dep_row)
        dep_row_layout.setContentsMargins(0, 0, 0, 0)
        dep_row_layout.setSpacing(10)

        dep_row_layout.addWidget(QLabel("前置依赖"))
        self.btn_dep_quick = QPushButton("(无)")
        self.btn_dep_quick.setObjectName("inputLike")
        self.btn_dep_quick.setFixedSize(180, 32)
        self.btn_dep_quick.setToolTip("点击快速设置：无 / 依赖上一步 / 自定义")
        self.btn_dep_quick.clicked.connect(self._show_dep_quick_menu)
        dep_row_layout.addWidget(self.btn_dep_quick)

        self.dep_inline_hint = QLabel("")
        self.dep_inline_hint.setVisible(False)
        self.dep_inline_hint.setStyleSheet(f"color:{COLORS['warning']}; font-size:11px;")
        dep_row_layout.addWidget(self.dep_inline_hint)

        dep_row_layout.addWidget(QLabel("执行阶段"))
        self.combo_stage = QComboBox()
        self.combo_stage.setFixedHeight(32)
        dep_row_layout.addWidget(self.combo_stage, stretch=1)

        basic_layout.addWidget(dep_row)

        # Save row（按 Pencil：右对齐，单按钮）
        save_row = QWidget()
        save_row_layout = QHBoxLayout(save_row)
        save_row_layout.setContentsMargins(0, 0, 0, 0)
        save_row_layout.setSpacing(8)
        save_row_layout.addStretch()
        self.btn_save = QPushButton("保存")
        self.btn_save.setObjectName("primaryRect")
        self.btn_save.setFixedSize(72, 32)
        self.btn_save.clicked.connect(self.save_step)
        save_row_layout.addWidget(self.btn_save)
        basic_layout.addWidget(save_row)

        group_layout.addWidget(basic_widget)

        # ── 依赖摘要（可理解 + 可定位，不改变依赖配置本身） ──
        self.dep_summary = CollapsibleSection("依赖摘要（只读）", collapsed=True)
        dep_sum_layout = self.dep_summary.body_layout

        self.dep_warning = QLabel("")
        self.dep_warning.setVisible(False)
        self.dep_warning.setWordWrap(True)
        self.dep_warning.setStyleSheet(f"color:{COLORS['warning']}; font-size:11px;")
        dep_sum_layout.addWidget(self.dep_warning)

        dep_lists = QWidget()
        dep_lists_layout = QHBoxLayout(dep_lists)
        dep_lists_layout.setContentsMargins(0, 0, 0, 0)
        dep_lists_layout.setSpacing(12)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(QLabel("我依赖的步骤"))
        self.list_depends_on = QListWidget()
        self.list_depends_on.setMaximumHeight(110)
        self.list_depends_on.itemDoubleClicked.connect(lambda item: self._emit_navigate_from_item(item))
        left_layout.addWidget(self.list_depends_on)
        dep_lists_layout.addWidget(left, stretch=1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(QLabel("依赖我的步骤"))
        self.list_dependents = QListWidget()
        self.list_dependents.setMaximumHeight(110)
        self.list_dependents.itemDoubleClicked.connect(lambda item: self._emit_navigate_from_item(item))
        right_layout.addWidget(self.list_dependents)
        dep_lists_layout.addWidget(right, stretch=1)

        dep_lists.setStyleSheet(f"""
            QLabel {{ color:{COLORS['text_secondary']}; font-size:11px; font-weight:600; }}
            QListWidget {{
                background: {COLORS['surface']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
            QListWidget::item {{ padding: 6px 8px; }}
            QListWidget::item:selected {{ background: {COLORS['selected_bg']}; }}
        """)
        dep_sum_layout.addWidget(dep_lists)

        hint = QLabel("提示：双击条目可定位到对应步骤（列表选中 + 打开编辑器）。")
        hint.setStyleSheet(f"color:{COLORS['text_tertiary']}; font-size:11px;")
        dep_sum_layout.addWidget(hint)

        group_layout.addWidget(self.dep_summary)
        self.dep_summary.setVisible(False)

        # ── 高级设置（默认折叠） ──
        self.advanced = CollapsibleSection("高级设置", collapsed=True)
        adv_layout = self.advanced.body_layout

        adv_widget = QWidget()
        grid = QGridLayout(adv_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        row = 0
        # 前置(Gate)（放在高级设置：避免与“依赖”概念混淆）
        self.check_gate = QCheckBox("检查点：单独先执行")
        self.check_gate.setToolTip("前置(Gate) 是检查点/闸门：会被单独优先执行，用于关键校验或准备步骤；不是常规“依赖”。")
        self.check_gate.stateChanged.connect(self._on_gate_state_changed)
        grid.addWidget(QLabel("前置(Gate)"), row, 0)
        grid.addWidget(self.check_gate, row, 1, 1, 3)
        row += 1

        # 步骤类型（允许覆盖自动识别）
        self.combo_type = QComboBox()
        for value, display in StepType.choices():
            self.combo_type.addItem(display, value)
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        self.label_type = QLabel("步骤类型")
        grid.addWidget(self.label_type, row, 0)
        grid.addWidget(self.combo_type, row, 1)

        # 工作目录
        cwd_layout = QHBoxLayout()
        cwd_layout.setContentsMargins(0, 0, 0, 0)
        self.edit_cwd = QLineEdit()
        self.edit_cwd.setPlaceholderText("留空使用脚本所在目录")
        cwd_layout.addWidget(self.edit_cwd)
        self.btn_browse_cwd = QPushButton("浏览...")
        self.btn_browse_cwd.setFixedWidth(60)
        self.btn_browse_cwd.clicked.connect(self._browse_cwd)
        cwd_layout.addWidget(self.btn_browse_cwd)
        self.cwd_row = QWidget()
        self.cwd_row.setLayout(cwd_layout)
        self.label_cwd = QLabel("工作目录")
        grid.addWidget(self.label_cwd, row, 2)
        grid.addWidget(self.cwd_row, row, 3)
        row += 1

        # 子工作流搜索过滤行（仅子工作流类型显示）
        self.sub_workflow_filter_widget = QWidget()
        sub_filter_layout = QHBoxLayout(self.sub_workflow_filter_widget)
        sub_filter_layout.setContentsMargins(0, 0, 0, 0)
        sub_filter_layout.setSpacing(10)

        sub_filter_layout.addWidget(QLabel("搜索:"))
        self.edit_target_search = QLineEdit()
        self.edit_target_search.setPlaceholderText("输入关键词过滤...")
        self.edit_target_search.textChanged.connect(lambda t: self._refresh_target_options(t))
        self.edit_target_search.setMaximumWidth(200)
        sub_filter_layout.addWidget(self.edit_target_search)

        sub_filter_layout.addWidget(QLabel("范围:"))
        self.combo_target_scope = QComboBox()
        self.combo_target_scope.addItem("全部", "all")
        self.combo_target_scope.addItem("最近使用", "recent")
        self.combo_target_scope.currentIndexChanged.connect(
            lambda: self._refresh_target_options(self.edit_target_search.text())
        )
        self.combo_target_scope.setMaximumWidth(120)
        sub_filter_layout.addWidget(self.combo_target_scope)
        sub_filter_layout.addStretch()

        self.sub_workflow_filter_widget.setVisible(False)
        grid.addWidget(self.sub_workflow_filter_widget, row, 0, 1, 4)
        row += 1

        # 参数（JSON 格式）
        self.edit_args = QLineEdit()
        self.edit_args.setPlaceholderText('例如: ["--output", "result.txt"]')
        grid.addWidget(QLabel("参数(JSON)"), row, 0)
        grid.addWidget(self.edit_args, row, 1, 1, 3)
        row += 1

        # 图表主题
        self.edit_theme = QLineEdit()
        self.edit_theme.setPlaceholderText("留空使用工作流默认主题")
        grid.addWidget(QLabel("图表主题"), row, 0)
        grid.addWidget(self.edit_theme, row, 1)

        # 超时时间
        self.edit_timeout = QLineEdit()
        self.edit_timeout.setPlaceholderText("秒数，留空不限制")
        grid.addWidget(QLabel("超时时间(秒)"), row, 2)
        grid.addWidget(self.edit_timeout, row, 3)
        row += 1

        # 重试次数
        self.edit_retry = QLineEdit()
        self.edit_retry.setPlaceholderText("默认 0")
        grid.addWidget(QLabel("重试次数"), row, 0)
        grid.addWidget(self.edit_retry, row, 1)

        # 上次成功则跳过
        self.check_skip_on_success = QCheckBox("启用（自动化运行时跳过已成功步骤）")
        self.check_skip_on_success.setToolTip("勾选后，若上次运行该步骤成功，本次将自动跳过")
        grid.addWidget(QLabel("上次成功跳过"), row, 2)
        grid.addWidget(self.check_skip_on_success, row, 3)
        row += 1

        # 依赖步骤（高级多选）
        self.dep_list = QListWidget()
        self.dep_list.setMaximumHeight(140)
        self.dep_list.itemChanged.connect(lambda _it: (self._refresh_dep_quick_text(), self._refresh_dependency_preview()))
        grid.addWidget(QLabel("依赖步骤"), row, 0)
        grid.addWidget(self.dep_list, row, 1, 1, 3)

        adv_layout.addWidget(adv_widget)
        group_layout.addWidget(self.advanced)
        self.advanced.setVisible(False)

        layout.addWidget(self.section)

    def set_single_script_mode(self, enabled: bool):
        """设置单脚本模式"""
        self._single_script_mode = enabled
        self._apply_enabled_state()

    def set_edit_enabled(self, enabled: bool):
        self._edit_enabled = enabled
        self._apply_enabled_state()

    def set_parallel_available(self, enabled: bool):
        self._parallel_available = enabled
        self._apply_enabled_state()

    def _apply_enabled_state(self):
        can_edit = self._edit_enabled and (not self._single_script_mode)
        # 编辑模式只做“写操作门禁”，不应让用户无法查看/复制字段内容
        self.section.setEnabled(True)
        self.btn_save.setEnabled(can_edit)

        # 基础字段：只读/可编辑
        try:
            self.edit_name.setReadOnly(not can_edit)
            self.edit_script.setReadOnly(not can_edit)
        except Exception:
            pass
        try:
            self.btn_browse.setEnabled(can_edit)
        except Exception:
            pass
        try:
            self.btn_browse_cwd.setEnabled(can_edit)
        except Exception:
            pass
        try:
            self.btn_dep_quick.setEnabled(can_edit)
        except Exception:
            pass
        try:
            self.combo_stage.setEnabled(can_edit)
        except Exception:
            pass

        # 高级设置：可见但写操作禁用（避免误操作）
        self.advanced.setEnabled(can_edit)
        try:
            self.combo_type.setEnabled(can_edit)
            self.edit_args.setReadOnly(not can_edit)
            self.edit_cwd.setReadOnly(not can_edit)
            self.edit_theme.setReadOnly(not can_edit)
            self.edit_timeout.setReadOnly(not can_edit)
            self.edit_retry.setReadOnly(not can_edit)
            self.check_gate.setEnabled(can_edit)
            self.check_skip_on_success.setEnabled(can_edit)
            self.dep_list.setEnabled(can_edit)
            self.combo_target_workflow.setEnabled(can_edit)
        except Exception:
            pass

    def _on_gate_state_changed(self, _state: int):
        # 自动并行语义下，“前置”仅用于强制关键步骤单独执行；这里无需联动并行开关
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
        """根据当前步骤 order 计算“上一执行步骤”，用于依赖快捷菜单"""
        self._prev_step_uid = None

        # 与“用途阶段顺序 + step.order”的展示/执行心智一致：上一“执行步骤”应基于该顺序计算
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
            # 防御：高级设置默认隐藏；选择“自定义依赖”时需自动展开并显示依赖多选列表
            if not self._extra_sections_visible:
                self._extra_sections_visible = True
                self.dep_summary.setVisible(True)
                self.advanced.setVisible(True)
                self._act_toggle_details.setText("隐藏高级设置")
            self.advanced.set_collapsed(False)
            self._notify_status("自定义依赖：请在下方“依赖步骤”中勾选依赖项，然后点击保存。")
            # 展开后再滚动定位（让布局先完成），避免用户感觉“点了没反应”
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
            self.btn_dep_quick.setText("(无)")
        elif self._prev_step_uid and deps == [self._prev_step_uid]:
            self.btn_dep_quick.setText("上一步")
        else:
            self.btn_dep_quick.setText(f"{len(deps)} 项")

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
        """当 UI 中依赖选择发生变化时，刷新“依赖摘要（只读）”以避免用户误以为“设置没生效”。

        说明：此预览不落库，真正持久化仍以“保存”为准。
        """
        if not self._step_id:
            return
        try:
            with get_session() as session:
                step = session.query(Step).filter(Step.id == self._step_id).first()
                if not step:
                    return
                self._refresh_dependency_summary(step, override_dep_uids=self._get_selected_dep_uids_from_ui())
        except Exception:
            return

    def _ensure_widget_visible(self, widget: QWidget):
        """尽量把某个控件滚动到可见（用于“自定义依赖”后把依赖多选列表带到视口内）。"""
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
        """加载步骤"""
        self._step_id = step_id
        
        with get_session() as session:
            step = session.query(Step).filter(Step.id == step_id).first()
            if not step:
                self.clear()
                return
            
            # 保存当前工作流 ID（用于排除自引用）
            self._current_workflow_id = step.workflow_id
            
            self.edit_name.setText(step.name)
            
            # 设置步骤类型
            index = self.combo_type.findData(step.step_type)
            if index >= 0:
                self._suppress_type_override = True
                try:
                    self.combo_type.setCurrentIndex(index)
                finally:
                    self._suppress_type_override = False
            self._type_manual_override = False
            
            self.edit_script.setText(step.script_path or "")
            self.edit_args.setText(step.args or "")
            self.edit_cwd.setText(step.cwd or "")
            self.edit_theme.setText(step.chart_theme or "")
            self.edit_timeout.setText(str(step.timeout_seconds) if step.timeout_seconds else "")
            self.edit_retry.setText(str(step.retry_count) if step.retry_count else "")
            self.check_gate.setChecked(step.is_gate)
            self.check_skip_on_success.setChecked(getattr(step, 'skip_on_success', False))

            # 执行阶段（用途阶段）
            self.combo_stage.blockSignals(True)
            try:
                self.combo_stage.clear()
                stages = list_stages(step.workflow_id)
                for idx, st in enumerate(stages, start=1):
                    self.combo_stage.addItem(f"S{idx} {st.name}", st.uid)
                suid = getattr(step, "stage_uid", None)
                if suid:
                    i = self.combo_stage.findData(suid)
                    if i >= 0:
                        self.combo_stage.setCurrentIndex(i)
            finally:
                self.combo_stage.blockSignals(False)

            # 依赖步骤列表
            self._load_dependencies(step)
            self.dep_summary.set_collapsed(True)
            self._refresh_dependency_summary(step)
            self._load_workflow_targets(step.script_path)
            self._suppress_type_override = True
            try:
                self._on_type_changed()
            finally:
                self._suppress_type_override = False
            self._refresh_prev_dep_quick_toggle(step)
            self._refresh_dep_quick_text()
            self._apply_enabled_state()

    def _load_dependencies(self, step: Step):
        """加载依赖步骤列表"""
        self.dep_list.clear()
        steps = get_steps_by_workflow(step.workflow_id)
        selected = set(step.get_depends_on())
        for s in steps:
            if s.id == step.id:
                continue
            item = QListWidgetItem(f"{s.order + 1}. {s.name}")
            item.setData(Qt.UserRole, s.uid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if s.uid in selected else Qt.Unchecked)
            self.dep_list.addItem(item)
        self._refresh_dep_quick_text()

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
          - 用于 UI 预览（未保存前也能看到“已选依赖”）
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

        # 用途阶段标签（用于 tooltip）
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

        # “我依赖的步骤”
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

        # “依赖我的步骤”
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

        # 轻量校验提示：依赖未来用途阶段（严格规则）
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
                    "当前依赖包含“未来用途阶段”的步骤（运行/保存阶段顺序时将被阻止）："
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
    
    def clear(self):
        """清空表单"""
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
        self.edit_cwd.clear()
        self.edit_theme.clear()
        self.edit_timeout.clear()
        self.edit_retry.clear()
        self.check_gate.setChecked(False)
        self.btn_dep_quick.setText("(无)")
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
        self.combo_target_workflow.clear()
        self.edit_target_search.clear()
        self.combo_target_scope.setCurrentIndex(0)
        self._apply_enabled_state()
    
    @Slot()
    def save_step(self):
        """保存步骤"""
        if not self._step_id:
            return
        
        # 验证参数格式
        args_text = self.edit_args.text().strip()
        if args_text:
            import json
            try:
                args = json.loads(args_text)
                if not isinstance(args, list):
                    raise ValueError("参数必须是数组")
            except (json.JSONDecodeError, ValueError) as e:
                QMessageBox.warning(self, "参数格式错误", f"参数必须是有效的 JSON 数组\n{e}")
                return
        
        # 验证超时时间
        timeout = None
        timeout_text = self.edit_timeout.text().strip()
        if timeout_text:
            try:
                timeout = int(timeout_text)
                if timeout <= 0:
                    raise ValueError()
            except ValueError:
                QMessageBox.warning(self, "输入错误", "超时时间必须是正整数")
                return
        
        # 验证重试次数
        retry = 0
        retry_text = self.edit_retry.text().strip()
        if retry_text:
            try:
                retry = int(retry_text)
                if retry < 0:
                    raise ValueError()
            except ValueError:
                QMessageBox.warning(self, "输入错误", "重试次数必须是非负整数")
                return
        
        # 更新步骤
        step_type = self.combo_type.currentData()
        script_path = self.edit_script.text().strip()
        if step_type == "sub_workflow":
            uid = self.combo_target_workflow.currentData()
            if not uid:
                QMessageBox.warning(self, "输入错误", "请选择目标工作流")
                return
            if not self._validate_sub_workflow_cycle(uid):
                return
            script_path = uid

        # 验证脚本路径存在性（非阻塞：只提示，不阻断保存）
        import os
        if script_path and step_type != "sub_workflow":
            if not os.path.exists(script_path):
                QMessageBox.warning(
                    self,
                    "路径提示",
                    f"脚本路径不存在（仍会保存配置）：\n{script_path}\n\n建议：确认文件已同步到本机或修正路径。",
                    QMessageBox.Ok,
                )

        deps = []
        for i in range(self.dep_list.count()):
            item = self.dep_list.item(i)
            if item.checkState() == Qt.Checked:
                deps.append(item.data(Qt.UserRole))

        try:
            update_step(
                self._step_id,
                name=self.edit_name.text().strip(),
                step_type=step_type,
                script_path=script_path,
                args=args_text if args_text else None,
                cwd=self.edit_cwd.text().strip() or None,
                chart_theme=self.edit_theme.text().strip() or None,
                timeout_seconds=timeout,
                retry_count=retry,
                is_gate=self.check_gate.isChecked(),
                skip_on_success=self.check_skip_on_success.isChecked(),
                depends_on=json.dumps(deps, ensure_ascii=False) if deps else None,
                stage_uid=self.combo_stage.currentData() if self.combo_stage.count() else None,
            )
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return
        if step_type == "sub_workflow" and script_path:
            update_recent_workflow(script_path)
        
        self._notify_status("已保存步骤配置。")
        self.step_saved.emit()
    
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
        """加载可选的子工作流列表"""
        workflows = list_workflows()
        # 排除当前步骤所属的工作流（避免自引用）
        self._workflow_targets = [
            (wf.name, wf.uid) for wf in workflows 
            if self._current_workflow_id is None or wf.id != self._current_workflow_id
        ]
        self._current_target_uid = current_uid  # 保存当前选中的 UID
        self._refresh_target_options()

    def _refresh_target_options(self, text: str = ""):
        """刷新目标工作流下拉选项"""
        keyword = (text or "").strip().lower()
        scope = self.combo_target_scope.currentData()
        recent_uids = set()
        if scope == "recent":
            from database import list_recent_workflows
            recent_uids = set(list_recent_workflows())
        
        self.combo_target_workflow.blockSignals(True)  # 防止触发信号
        self.combo_target_workflow.clear()
        
        for name, uid in self._workflow_targets:
            if scope == "recent" and uid not in recent_uids:
                continue
            if keyword and keyword not in name.lower():
                continue
            self.combo_target_workflow.addItem(name, uid)
        
        # 恢复选中状态
        if self._current_target_uid:
            idx = self.combo_target_workflow.findData(self._current_target_uid)
            if idx >= 0:
                self.combo_target_workflow.setCurrentIndex(idx)
        
        self.combo_target_workflow.blockSignals(False)

    def _on_type_changed(self):
        """步骤类型变更时更新 UI"""
        if (not self._suppress_type_override) and (self._step_id is not None):
            self._type_manual_override = True

        step_type = self.combo_type.currentData()
        is_sub = step_type == "sub_workflow"
        
        # 切换脚本行和子工作流选择行的可见性
        self.script_label.setVisible(not is_sub)
        self.script_row.setVisible(not is_sub)
        self.sub_workflow_label.setVisible(is_sub)
        self.combo_target_workflow.setVisible(is_sub)
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
            QMessageBox.warning(self, "循环依赖", "检测到跨工作流循环依赖，请选择其他工作流")
            return False
        return True
