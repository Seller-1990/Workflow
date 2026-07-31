# -*- coding: utf-8 -*-
"""步骤详情编辑器 UI 构建（自 step_editor 纯移动提取，行为不变）。

每个函数的首个参数 ``panel`` 即 StepEditorPanel 实例；跨方法调用一律走
``panel._xxx`` 委托方法，保持原有动态分发语义。
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QCheckBox,
    QPushButton,
    QToolButton,
    QLabel,
    QMenu,
    QStyle,
    QSizePolicy,
)
from PySide6.QtCore import Qt

from config import StepType
from ui.collapsible_section import CollapsibleSection
from ui.mini_dag import MiniDagWidget
from ui.step_editor_sections import (
    create_advanced_settings_section,
    create_dependency_summary_section,
)
from ui.theme import (
    COLORS,
    get_colors,
    get_menu_stylesheet,
    get_danger_button_stylesheet,
)


def setup_ui(panel):
    """设置 UI"""
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    # 卡片区块（iOS 极简一致性：与 DAG/运行历史相同的 CollapsibleSection）
    panel.section = CollapsibleSection("步骤详情编辑器", collapsed=False)
    group_layout = panel.section.body_layout

    # 右侧「更多」：默认隐藏高级区块，保持定稿 UI 的紧凑外观
    panel.btn_more = QToolButton()
    panel.btn_more.setAutoRaise(True)
    panel.btn_more.setIcon(panel.style().standardIcon(QStyle.SP_TitleBarMenuButton))
    panel.btn_more.setAccessibleName("更多操作")
    panel.btn_more.setToolTip("更多操作：高级设置、依赖摘要")
    panel.section.header_actions_layout.addWidget(panel.btn_more)

    panel._more_menu = QMenu(panel)
    panel._more_menu.setStyleSheet(get_menu_stylesheet(panel._dark))
    panel._act_toggle_details = panel._more_menu.addAction("显示高级设置")
    panel._act_toggle_details.setToolTip("展开或隐藏高级设置")
    panel._act_toggle_details.triggered.connect(panel._toggle_extra_sections)
    panel._act_show_dep = panel._more_menu.addAction("查看依赖摘要")
    panel._act_show_dep.setToolTip("查看当前步骤的上游依赖和下游引用")
    panel._act_show_dep.triggered.connect(panel._show_dep_summary)
    panel.btn_more.setMenu(panel._more_menu)
    panel.btn_more.setPopupMode(QToolButton.InstantPopup)

    panel.context_banner = QLabel()
    panel.context_banner.setWordWrap(False)
    panel.context_banner.setFixedHeight(30)
    panel.context_banner.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    panel.context_banner.setMinimumWidth(0)
    panel.context_banner.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    panel.context_banner.setText("未选中步骤：点击卡片编辑；选阶段后添加步骤会进入该阶段。")
    group_layout.addWidget(panel.context_banner)

    # 任务4：Inspector 空白状态——未选中步骤时展示工作流摘要、快捷键、最近运行
    panel.empty_state_widget = QWidget()
    panel.empty_state_widget.setObjectName("InspectorEmptyState")
    empty_layout = QVBoxLayout(panel.empty_state_widget)
    empty_layout.setContentsMargins(20, 24, 20, 24)
    empty_layout.setSpacing(12)

    # 图标 + 引导标题
    panel.empty_icon = QLabel("📋")
    panel.empty_icon.setObjectName("EmptyIcon")
    panel.empty_icon.setAlignment(Qt.AlignCenter)
    panel.empty_icon.setStyleSheet("font-size: 36px; background: transparent;")
    empty_layout.addWidget(panel.empty_icon)

    panel.empty_title = QLabel("选择一个步骤以编辑")
    panel.empty_title.setObjectName("EmptyTitle")
    panel.empty_title.setAlignment(Qt.AlignCenter)
    panel.empty_title.setStyleSheet("font-size: 15px; font-weight: 600; background: transparent;")
    empty_layout.addWidget(panel.empty_title)

    panel.empty_hint = QLabel("或开启编辑模式后新建步骤")
    panel.empty_hint.setObjectName("EmptyHint")
    panel.empty_hint.setAlignment(Qt.AlignCenter)
    panel.empty_hint.setStyleSheet("font-size: 12px; background: transparent;")
    empty_layout.addWidget(panel.empty_hint)

    # 分隔
    panel.empty_sep = QLabel("")
    panel.empty_sep.setFixedHeight(1)
    panel.empty_sep.setObjectName("EmptySeparator")
    _c = get_colors(panel._dark)
    panel.empty_sep.setStyleSheet(f"background: {_c['border']}; margin: 8px 0;")
    empty_layout.addWidget(panel.empty_sep)

    panel.empty_summary = QLabel("工作流摘要")
    panel.empty_summary.setObjectName("Eyebrow")
    empty_layout.addWidget(panel.empty_summary)

    panel.empty_stats = QLabel("0 阶段 · 0 步 · 未运行")
    panel.empty_stats.setObjectName("WorkflowMeta")
    panel.empty_stats.setWordWrap(True)
    empty_layout.addWidget(panel.empty_stats)

    panel.empty_shortcuts = QLabel(
        "快捷键：\n"
        "  F5 - 运行/停止\n"
        "  Shift+F5 - 停止运行\n"
        "  Ctrl+S - 保存"
    )
    panel.empty_shortcuts.setObjectName("WorkflowMeta")
    panel.empty_shortcuts.setWordWrap(True)
    empty_layout.addWidget(panel.empty_shortcuts)

    panel.empty_last_run = QLabel("最近运行：无")
    panel.empty_last_run.setObjectName("WorkflowMeta")
    panel.empty_last_run.setWordWrap(True)
    empty_layout.addWidget(panel.empty_last_run)

    empty_layout.addStretch(1)

    panel.btn_empty_new_step = QPushButton("+ 新建步骤")
    panel.btn_empty_new_step.setObjectName("PrimaryAction")
    panel.btn_empty_new_step.setEnabled(False)
    panel.btn_empty_new_step.setToolTip("开启编辑模式后可新建步骤")
    panel.btn_empty_new_step.setAccessibleName("新建步骤")
    panel.btn_empty_new_step.setFixedWidth(160)
    empty_layout.addWidget(panel.btn_empty_new_step, alignment=Qt.AlignCenter)

    panel.empty_state_widget.hide()
    group_layout.addWidget(panel.empty_state_widget)

    panel.section.title_label.setText("步骤设置")
    panel.section.btn_toggle.hide()

    # ── 基础信息 ──
    basic_widget = QWidget()
    basic_layout = QVBoxLayout(basic_widget)
    basic_layout.setContentsMargins(0, 0, 0, 0)
    basic_layout.setSpacing(8)

    # Row 0: 步骤名称（独占一行的标签 + 输入；保留紧凑布局）
    name_row = QWidget()
    name_row_layout = QHBoxLayout(name_row)
    name_row_layout.setContentsMargins(0, 0, 0, 0)
    name_row_layout.setSpacing(8)

    label_name = QLabel("名称")
    label_name.setFixedWidth(56)
    name_row_layout.addWidget(label_name)
    panel.edit_name = QLineEdit()
    panel.edit_name.setFixedHeight(30)
    panel.edit_name.setMinimumWidth(0)
    panel.edit_name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    panel.edit_name.setToolTip("步骤在编排视图、运行历史和日志中显示的名称")
    name_row_layout.addWidget(panel.edit_name, stretch=1)

    basic_layout.addWidget(name_row)

    type_stage_row = QWidget()
    type_stage_layout = QHBoxLayout(type_stage_row)
    type_stage_layout.setContentsMargins(0, 0, 0, 0)
    type_stage_layout.setSpacing(8)
    panel.label_type = QLabel("类型")
    panel.label_type.setFixedWidth(56)
    type_stage_layout.addWidget(panel.label_type)
    panel.combo_type = QComboBox()
    for value, display in StepType.choices():
        panel.combo_type.addItem(display, value)
    panel.combo_type.setFixedHeight(30)
    panel.combo_type.setMinimumWidth(0)
    panel.combo_type.setMinimumContentsLength(0)
    panel.combo_type.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    panel.combo_type.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    panel.combo_type.setToolTip("步骤的执行器类型，可由脚本后缀自动识别，也可手动调整")
    panel.combo_type.currentIndexChanged.connect(panel._on_type_changed)
    type_stage_layout.addWidget(panel.combo_type, stretch=1)

    stage_label = QLabel("阶段")
    stage_label.setFixedWidth(48)
    type_stage_layout.addWidget(stage_label)
    panel.combo_stage = QComboBox()
    panel.combo_stage.setFixedHeight(30)
    panel.combo_stage.setMinimumWidth(0)
    panel.combo_stage.setMinimumContentsLength(0)
    panel.combo_stage.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    panel.combo_stage.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    panel.combo_stage.setToolTip("步骤所在阶段。阶段是大顺序屏障，后续阶段会等待前序阶段完成。")
    type_stage_layout.addWidget(panel.combo_stage, stretch=1)
    basic_layout.addWidget(type_stage_row)

    panel.target_workflow_row = QWidget()
    target_workflow_layout = QHBoxLayout(panel.target_workflow_row)
    target_workflow_layout.setContentsMargins(0, 0, 0, 0)
    target_workflow_layout.setSpacing(8)
    panel.sub_workflow_label = QLabel("目标")
    panel.sub_workflow_label.setFixedWidth(56)
    target_workflow_layout.addWidget(panel.sub_workflow_label)
    panel.combo_target_workflow = QComboBox()
    panel.combo_target_workflow.setFixedHeight(30)
    panel.combo_target_workflow.setMinimumWidth(0)
    panel.combo_target_workflow.setMinimumContentsLength(0)
    panel.combo_target_workflow.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    panel.combo_target_workflow.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    panel.combo_target_workflow.setToolTip("子工作流步骤要调用的目标工作流")
    panel.combo_target_workflow.currentIndexChanged.connect(panel._on_target_changed)
    target_workflow_layout.addWidget(panel.combo_target_workflow, stretch=1)
    panel.target_workflow_row.setVisible(False)
    basic_layout.addWidget(panel.target_workflow_row)

    # U-P2-4: 脚本路径独立成行，避免与名称/目标工作流共挤
    panel.script_row = QWidget()
    script_layout = QHBoxLayout(panel.script_row)
    script_layout.setContentsMargins(0, 0, 0, 0)
    script_layout.setSpacing(8)

    panel.script_label = QLabel("路径")
    panel.script_label.setFixedWidth(56)
    script_layout.addWidget(panel.script_label)

    panel.edit_script = QLineEdit()
    panel.edit_script.setFixedHeight(30)
    panel.edit_script.setMinimumWidth(0)
    panel.edit_script.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    panel.edit_script.setPlaceholderText("选择脚本或文件路径…")
    panel.edit_script.setToolTip("当前步骤要执行的脚本、Excel、Power BI 文件，或子工作流 ID")
    panel.edit_script.editingFinished.connect(panel._auto_detect_type_from_script)
    script_layout.addWidget(panel.edit_script, stretch=1)
    panel.btn_browse = QPushButton("浏览")
    panel.btn_browse.setFixedSize(56, 30)
    panel.btn_browse.setAccessibleName("浏览脚本或文件")
    panel.btn_browse.setToolTip("浏览并选择脚本或文件")
    panel.btn_browse.clicked.connect(panel._browse_script)
    script_layout.addWidget(panel.btn_browse)
    basic_layout.addWidget(panel.script_row)

    # Row 2: 上游依赖 + 检查点
    dep_row = QWidget()
    dep_row_layout = QHBoxLayout(dep_row)
    dep_row_layout.setContentsMargins(0, 0, 0, 0)
    dep_row_layout.setSpacing(8)

    dep_line = QWidget()
    dep_line_layout = QHBoxLayout(dep_line)
    dep_line_layout.setContentsMargins(0, 0, 0, 0)
    dep_line_layout.setSpacing(8)
    dep_label = QLabel("依赖")
    dep_label.setFixedWidth(56)
    dep_line_layout.addWidget(dep_label)
    panel.btn_dep_quick = QPushButton("(无) ▾")  # U-P2-4: 加 ▾ 表明这是下拉
    panel.btn_dep_quick.setObjectName("inputLike")
    panel.btn_dep_quick.setFixedHeight(30)
    panel.btn_dep_quick.setMinimumWidth(0)
    panel.btn_dep_quick.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    panel.btn_dep_quick.setAccessibleName("上游依赖快速设置")
    panel.btn_dep_quick.setToolTip("点击快速设置上游依赖：无 / 依赖上一步 / 自定义")
    panel.btn_dep_quick.clicked.connect(panel._show_dep_quick_menu)
    dep_line_layout.addWidget(panel.btn_dep_quick, stretch=1)

    panel.dep_inline_hint = QLabel("")
    panel.dep_inline_hint.setVisible(False)
    panel.dep_inline_hint.setStyleSheet(f"color:{COLORS['warning']}; font-size:11px;")
    dep_line_layout.addWidget(panel.dep_inline_hint)
    dep_row_layout.addWidget(dep_line, stretch=1)

    gate_line = QWidget()
    gate_line_layout = QHBoxLayout(gate_line)
    gate_line_layout.setContentsMargins(0, 0, 0, 0)
    gate_line_layout.setSpacing(6)
    panel.check_gate = QCheckBox("检查点")
    panel.check_gate.setToolTip("检查点是本阶段的闸门步骤：它会单独先执行，同阶段普通步骤会等待它完成。")
    panel.check_gate.stateChanged.connect(panel._on_gate_state_changed)
    gate_line_layout.addWidget(panel.check_gate)
    dep_row_layout.addWidget(gate_line)

    basic_layout.addWidget(dep_row)

    # 高频运行操作：不依赖编辑模式。
    run_row = QWidget()
    run_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    run_row_layout = QVBoxLayout(run_row)
    run_row_layout.setContentsMargins(0, 0, 0, 0)
    run_row_layout.setSpacing(6)
    panel.btn_run_only_step = QPushButton("只运行此步骤")
    panel.btn_run_only_step.setObjectName("stepRunButton")
    panel.btn_run_only_step.setFixedHeight(30)
    panel.btn_run_only_step.setMinimumWidth(0)
    panel.btn_run_only_step.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    panel.btn_run_only_step.setToolTip("只运行当前选中的步骤")
    panel.btn_run_only_step.setAccessibleName("只运行此步骤")
    panel.btn_run_only_step.clicked.connect(lambda: panel._request_step_run("only_step"))
    run_row_layout.addWidget(panel.btn_run_only_step)
    panel.btn_run_from_step = QPushButton("从此步骤开始")
    panel.btn_run_from_step.setObjectName("stepRunButton")
    panel.btn_run_from_step.setFixedHeight(30)
    panel.btn_run_from_step.setMinimumWidth(0)
    panel.btn_run_from_step.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    panel.btn_run_from_step.setToolTip("从当前步骤开始运行后续步骤")
    panel.btn_run_from_step.setAccessibleName("从此步骤开始")
    panel.btn_run_from_step.clicked.connect(lambda: panel._request_step_run("from_step"))
    run_row_layout.addWidget(panel.btn_run_from_step)
    basic_layout.addWidget(run_row)

    # Save row（按 Pencil：右对齐，单按钮）
    save_row = QWidget()
    save_row_layout = QHBoxLayout(save_row)
    save_row_layout.setContentsMargins(0, 0, 0, 0)
    save_row_layout.setSpacing(8)
    save_row_layout.addStretch()
    panel.btn_delete = QPushButton("删除步骤")
    panel.btn_delete.setFixedSize(84, 30)
    panel.btn_delete.setAccessibleName("删除当前步骤")
    panel.btn_delete.setToolTip("删除当前步骤")
    panel.btn_delete.setStyleSheet(get_danger_button_stylesheet(False, radius=10, padding="0px 14px"))
    panel.btn_delete.clicked.connect(panel._request_delete_step)
    save_row_layout.addWidget(panel.btn_delete)
    panel.btn_save = QPushButton("保存")
    panel.btn_save.setObjectName("primaryRect")
    panel.btn_save.setFixedSize(66, 30)
    panel.btn_save.setAccessibleName("保存步骤")
    panel.btn_save.setToolTip("保存当前步骤配置")
    panel.btn_save.clicked.connect(panel.save_step)
    save_row_layout.addWidget(panel.btn_save)
    basic_layout.addWidget(save_row)

    group_layout.addWidget(basic_widget)

    # ── 依赖摘要（可理解 + 可定位，不改变依赖配置本身） ──
    # 任务10：mini DAG 可视化（120px 高，展示上下游）
    panel.mini_dag = MiniDagWidget(panel._dark, parent=panel)
    panel.mini_dag.step_activated.connect(panel.navigate_to_step)
    group_layout.addWidget(panel.mini_dag)

    dep_section = create_dependency_summary_section(COLORS, panel._emit_navigate_from_item)
    panel.dep_summary = dep_section.section
    panel.dep_warning = dep_section.warning
    panel.list_depends_on = dep_section.depends_on_list
    panel.list_dependents = dep_section.dependents_list
    panel._dep_lists = dep_section.lists_container
    panel._dep_summary_hint = dep_section.hint
    group_layout.addWidget(panel.dep_summary)

    # ── 高级设置（默认折叠） ──
    advanced_section = create_advanced_settings_section(
        COLORS,
        panel._browse_cwd,
        panel._refresh_target_options,
        panel._refresh_dep_quick_text,
        panel._refresh_dependency_preview,
    )
    panel.advanced = advanced_section.section
    panel.cwd_row = advanced_section.cwd_row
    panel.label_cwd = advanced_section.cwd_label
    panel.edit_cwd = advanced_section.cwd_edit
    panel.btn_browse_cwd = advanced_section.browse_cwd_button
    panel.sub_workflow_filter_widget = advanced_section.sub_workflow_filter
    panel.edit_target_search = advanced_section.target_search_edit
    panel.combo_target_scope = advanced_section.target_scope_combo
    panel.edit_args = advanced_section.args_edit
    panel.edit_saved_run_args = advanced_section.saved_run_args_edit
    # ROI-2: 步骤显式输出声明（分号分隔），监听冲突检测优先使用声明
    panel.edit_output_paths = advanced_section.output_paths_edit
    panel.edit_theme = advanced_section.theme_edit
    panel.edit_timeout = advanced_section.timeout_spin
    # M9: 编辑器保存时 0 会落库为 NULL，执行器按类型应用默认超时；提示文案与执行器语义保持一致
    panel.edit_timeout.setToolTip("留空使用默认超时：Python 7200s / Excel 300s / Power BI 600s / 子工作流 3600s")
    panel.edit_timeout.setSpecialValueText("默认")
    panel.edit_retry = advanced_section.retry_spin
    panel.check_skip_on_success = advanced_section.skip_on_success_check
    panel.dep_list = advanced_section.dependency_list
    group_layout.addWidget(panel.advanced)

    layout.addWidget(panel.section, alignment=Qt.AlignTop)
    layout.addStretch(1)
