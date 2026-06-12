# -*- coding: utf-8 -*-
"""主窗口 UI 构建与主题应用（自 main_window 纯移动提取，行为不变）。

每个函数的首个参数 ``window`` 即 MainWindow 实例。仅在初始化期使用、
类上不再保留委托的构建函数之间直接互调本模块函数；其余运行期跨方法
调用一律走 ``window._xxx`` 委托方法，保持原有动态分发语义。
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStatusBar, QToolBar,
    QScrollArea, QFrame, QLabel, QPushButton, QToolButton,
    QSizePolicy, QStyle, QApplication, QTabWidget,
    QStackedWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon

from config import APP_NAME, APP_VERSION, ICON_PATH
from ui.theme import (
    get_colors,
    get_stylesheet,
)
from ui.workflow_list import WorkflowListPanel
from ui.step_table import StepTablePanel
from ui.step_editor import StepEditorPanel
from ui.log_panel import LogPanel
from ui.run_history import RunHistoryPanel
from ui.run_control import RunControlPanel
from ui.workflow_config import WorkflowConfigPanel
from ui.ios_switch import IosSwitch
from ui.workbench_board import WorkbenchBoardPanel
from ui.main_window_theme import (
    build_shell_theme_tokens,
    center_panel_stylesheet,
    left_panel_stylesheet,
    mode_tabs_stylesheet,
    right_panel_stylesheet,
)

logger = logging.getLogger(__name__)


def setup_ui(window):
    """设置 UI"""
    window.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
    if ICON_PATH.exists():
        window.setWindowIcon(QIcon(str(ICON_PATH)))
    # U-P3-9：1366x768 笔记本兼容（原 1200x800 在 125% DPI 下溢出屏幕）
    window.setMinimumSize(1024, 680)

    central_widget = QWidget()
    window.setCentralWidget(central_widget)

    main_layout = QHBoxLayout(central_widget)
    main_layout.setContentsMargins(0, 0, 0, 0)
    main_layout.setSpacing(0)

    window.main_splitter = QSplitter(Qt.Horizontal)
    window.main_splitter.setObjectName("MainSplitter")
    window.main_splitter.setHandleWidth(1)
    window.main_splitter.setChildrenCollapsible(False)
    main_layout.addWidget(window.main_splitter)

    window.main_splitter.addWidget(create_left_panel(window))

    # ===== 中间：工作台 =====
    window.center_container = QFrame()
    window.center_container.setObjectName("CenterPanel")
    center_layout = QVBoxLayout(window.center_container)
    center_layout.setContentsMargins(22, 20, 22, 22)
    center_layout.setSpacing(16)
    window.center_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    center_layout.addWidget(create_command_bar(window))

    window.mode_tabs = QTabWidget()
    window.mode_tabs.setObjectName("ModeTabs")
    window.mode_tabs.setDocumentMode(True)

    add_plan_tab(window)

    add_run_tab(window)
    add_config_tab(window)
    center_layout.addWidget(window.mode_tabs, stretch=1)

    window.main_splitter.addWidget(window.center_container)

    window.main_splitter.addWidget(create_right_panel(window))

    window.main_splitter.setSizes([280, 840, 340])

    window._left_last_size = 280
    window._right_last_size = 340
    setup_border_fold_buttons(window)
    window._run_splitter_user_adjusted = False
    window._apply_run_splitter_profile("idle", force=True)

    window.step_table.setAccessibleName("步骤列表")
    window.run_control.btn_run_all.setAccessibleName("全流程运行")
    window.run_control.btn_run_from.setAccessibleName("从选中步骤开始")
    window.run_control.btn_run_only.setAccessibleName("只运行选中步骤")
    window.run_control.btn_retry.setAccessibleName("重试失败步骤")
    window.run_control.btn_dry_run.setAccessibleName("工作流预演")

    window.btn_view_board.clicked.connect(lambda: window._set_plan_view(0))
    window.btn_view_table.clicked.connect(lambda: window._set_plan_view(1))
    window.mode_tabs.currentChanged.connect(
        lambda index: window._ensure_run_log_visible() if index == getattr(window, "_run_tab_index", -1) else None
    )


def create_left_panel(window) -> QFrame:
    window.left_panel = QFrame()
    window.left_panel.setObjectName("LeftPanel")
    window.left_panel.setMinimumWidth(240)
    window.left_panel.setMaximumWidth(320)
    left_layout = QVBoxLayout(window.left_panel)
    left_layout.setContentsMargins(14, 18, 14, 14)
    left_layout.setSpacing(14)
    left_layout.addWidget(create_brand_row(window))

    window.workflow_list = WorkflowListPanel()
    left_layout.addWidget(window.workflow_list, stretch=1)

    asset_label = QLabel("资产")
    asset_label.setObjectName("SidebarLabel")
    left_layout.addWidget(asset_label)
    window.btn_asset_import = create_sidebar_button(window, "导入 JSON", "导入工作流 JSON", "导入 JSON")
    window.btn_asset_export = create_sidebar_button(window, "导出 JSON", "导出当前工作流为 JSON", "导出 JSON")
    window.btn_asset_webhook = create_sidebar_button(window, "Webhook", "配置运行通知 Webhook", "Webhook 管理")
    left_layout.addWidget(window.btn_asset_import)
    left_layout.addWidget(window.btn_asset_export)
    left_layout.addWidget(window.btn_asset_webhook)
    left_layout.addWidget(create_edit_bar(window))

    window.run_control = RunControlPanel()
    window.run_control.setVisible(False)
    left_layout.addWidget(window.run_control)
    return window.left_panel


def create_brand_row(window) -> QWidget:
    brand_row = QWidget()
    brand_layout = QHBoxLayout(brand_row)
    brand_layout.setContentsMargins(2, 0, 2, 0)
    brand_layout.setSpacing(10)
    window.lbl_brand_icon = QLabel()
    window.lbl_brand_icon.setObjectName("BrandMark")
    window.lbl_brand_icon.setFixedSize(36, 36)
    if ICON_PATH.exists():
        pix = QIcon(str(ICON_PATH)).pixmap(36, 36)
        window.lbl_brand_icon.setPixmap(pix)
    brand_layout.addWidget(window.lbl_brand_icon)

    brand_text = QVBoxLayout()
    brand_text.setContentsMargins(0, 0, 0, 0)
    brand_text.setSpacing(2)
    window.lbl_brand_name = QLabel("Workflow")
    window.lbl_brand_name.setObjectName("BrandName")
    brand_text.addWidget(window.lbl_brand_name)
    window.lbl_brand_subtitle = QLabel("本地自动化工作台")
    window.lbl_brand_subtitle.setObjectName("BrandSubtitle")
    brand_text.addWidget(window.lbl_brand_subtitle)
    brand_layout.addLayout(brand_text, stretch=1)
    return brand_row


def create_sidebar_button(window, text: str, tooltip: str, accessible_name: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("SidebarNav")
    button.setToolTip(tooltip)
    button.setAccessibleName(accessible_name)
    return button


def create_edit_bar(window) -> QWidget:
    edit_bar = QWidget()
    edit_bar.setObjectName("foldBar")
    edit_bar_layout = QHBoxLayout(edit_bar)
    edit_bar_layout.setContentsMargins(4, 0, 4, 0)
    edit_bar_layout.setSpacing(10)
    edit_bar_layout.addWidget(QLabel("编辑模式"))
    edit_bar_layout.addStretch()

    window.check_edit_mode = IosSwitch()
    window.check_edit_mode.setChecked(False)
    window.check_edit_mode.toggled.connect(window._set_edit_mode)
    window.check_edit_mode.setToolTip("开启后可以编辑工作流、阶段和步骤")
    edit_bar_layout.addWidget(window.check_edit_mode)

    window.btn_left_save = QPushButton("保存")
    window.btn_left_save.setObjectName("primarySmall")
    window.btn_left_save.setFixedSize(78, 26)
    window.btn_left_save.clicked.connect(window._action_save)
    window.btn_left_save.setToolTip("保存当前工作流和步骤修改")
    edit_bar_layout.addWidget(window.btn_left_save)
    return edit_bar


def create_command_bar(window) -> QWidget:
    command_bar = QWidget()
    command_bar.setObjectName("CommandBar")
    command_layout = QHBoxLayout(command_bar)
    command_layout.setContentsMargins(0, 0, 0, 0)
    command_layout.setSpacing(20)
    command_layout.addLayout(create_title_block(window), stretch=1)
    command_layout.addWidget(create_run_cluster(window))
    return command_bar


def create_title_block(window) -> QVBoxLayout:
    title_block = QVBoxLayout()
    title_block.setContentsMargins(0, 0, 0, 0)
    title_block.setSpacing(4)
    window.lbl_workflow_eyebrow = QLabel("当前工作流")
    window.lbl_workflow_eyebrow.setObjectName("Eyebrow")
    title_block.addWidget(window.lbl_workflow_eyebrow)
    window.lbl_workflow_title = QLabel("请选择工作流")
    window.lbl_workflow_title.setObjectName("WorkflowTitle")
    title_block.addWidget(window.lbl_workflow_title)
    window.lbl_workflow_meta = QLabel("0 阶段 · 0 步 · 未运行")
    window.lbl_workflow_meta.setObjectName("WorkflowMeta")
    title_block.addWidget(window.lbl_workflow_meta)
    return title_block


def create_run_cluster(window) -> QWidget:
    run_cluster = QWidget()
    run_cluster.setObjectName("RunCluster")
    run_layout = QHBoxLayout(run_cluster)
    run_layout.setContentsMargins(0, 0, 0, 0)
    run_layout.setSpacing(8)
    window.lbl_run_state = QLabel("● 就绪")
    window.lbl_run_state.setObjectName("RunStateChip")
    window.lbl_run_state.setToolTip("当前运行状态")
    run_layout.addWidget(window.lbl_run_state)
    window.btn_header_run = QPushButton("▶ 运行全流程")
    window.btn_header_run.setObjectName("PrimaryAction")
    window.btn_header_run.setToolTip("运行当前工作流的全流程（F5）")
    window.btn_header_run.setAccessibleName("运行全流程")
    window.btn_header_run.clicked.connect(window._on_header_run_clicked)
    run_layout.addWidget(window.btn_header_run)
    return run_cluster


def set_header_run_button_state(window, state: str) -> None:
    button = getattr(window, "btn_header_run", None)
    if button is None:
        return
    if state == "running":
        button.setText("■ 停止运行")
        button.setObjectName("DangerAction")
        button.setToolTip("停止当前运行（F5 或 Shift+F5）")
        button.setAccessibleName("停止运行")
        button.setEnabled(True)
    elif state == "stopping":
        button.setText("■ 正在停止...")
        button.setObjectName("DangerAction")
        button.setToolTip("正在停止当前运行")
        button.setAccessibleName("正在停止")
        button.setEnabled(False)
    else:
        button.setText("▶ 运行全流程")
        button.setObjectName("PrimaryAction")
        button.setToolTip("运行当前工作流的全流程（F5）")
        button.setAccessibleName("运行全流程")
        button.setEnabled(True)
    button.style().unpolish(button)
    button.style().polish(button)


def add_plan_tab(window) -> None:
    plan_page = QWidget()
    plan_layout = QVBoxLayout(plan_page)
    plan_layout.setContentsMargins(0, 0, 0, 0)
    plan_layout.setSpacing(12)
    plan_layout.addWidget(window._create_plan_switch())
    plan_layout.addWidget(create_plan_stack(window), stretch=1)
    window.center_scroll = window.workbench_board.scroll
    window.mode_tabs.addTab(plan_page, "编排")


def create_plan_switch(window) -> QWidget:
    plan_switch = QWidget()
    switch_layout = QHBoxLayout(plan_switch)
    switch_layout.setContentsMargins(0, 0, 0, 0)
    switch_layout.setSpacing(8)
    window.btn_view_board = QPushButton("阶段")
    window.btn_view_board.setObjectName("ViewSwitchActive")
    window.btn_view_board.setToolTip("阶段泳道编排视图")
    window.btn_view_board.setAccessibleName("阶段视图")
    window.btn_view_table = QPushButton("列表")
    window.btn_view_table.setObjectName("ViewSwitch")
    window.btn_view_table.setToolTip("使用表格查看和批量调整步骤")
    window.btn_view_table.setAccessibleName("列表视图")
    window._view_buttons = [
        (window.btn_view_board, 0),
        (window.btn_view_table, 1),
    ]
    switch_layout.addWidget(window.btn_view_board)
    switch_layout.addWidget(window.btn_view_table)
    switch_layout.addStretch(1)
    return plan_switch


def create_plan_stack(window) -> QStackedWidget:
    window.plan_stack = QStackedWidget()
    window.plan_stack.setObjectName("PlanStack")
    window.workbench_board = WorkbenchBoardPanel()
    window.plan_stack.addWidget(window.workbench_board)
    window.step_table = StepTablePanel()
    window.step_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    window.plan_stack.addWidget(window.step_table)
    return window.plan_stack


def add_run_tab(window) -> None:
    run_page = QWidget()
    run_page_layout = QVBoxLayout(run_page)
    run_page_layout.setContentsMargins(0, 0, 0, 0)
    run_page_layout.setSpacing(0)
    window.run_splitter = QSplitter(Qt.Vertical)
    window.run_splitter.setObjectName("RunSplitter")
    window.run_splitter.setChildrenCollapsible(False)
    window.run_splitter.setHandleWidth(5)
    window.log_panel = LogPanel()
    window.log_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    window.run_history = RunHistoryPanel()
    window.run_history.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    window.run_history.setMinimumHeight(180)
    window.log_panel.setMinimumHeight(220)
    window.run_splitter.addWidget(window.run_history)
    window.run_splitter.addWidget(window.log_panel)
    window.run_splitter.setSizes([360, 560])
    window.run_splitter.splitterMoved.connect(window._on_run_splitter_moved)
    run_page_layout.addWidget(window.run_splitter)
    window._run_tab_index = window.mode_tabs.addTab(run_page, "运行")


def add_config_tab(window) -> None:
    window.workflow_config = WorkflowConfigPanel()
    window.workflow_config.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    config_scroll = QScrollArea()
    config_scroll.setWidgetResizable(True)
    config_scroll.setFrameShape(QFrame.NoFrame)
    config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    config_scroll.setWidget(window.workflow_config)
    window.mode_tabs.addTab(config_scroll, "配置")


def create_right_panel(window) -> QFrame:
    window.right_panel = QFrame()
    window.right_panel.setObjectName("RightPanel")
    window.right_panel.setMinimumWidth(320)
    window.right_panel.setMaximumWidth(390)
    right_layout = QVBoxLayout(window.right_panel)
    right_layout.setContentsMargins(14, 18, 14, 16)
    right_layout.setSpacing(10)
    right_layout.addWidget(create_inspector_header(window))

    window.step_editor = StepEditorPanel()
    window.step_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    inspector_scroll = QScrollArea()
    inspector_scroll.setObjectName("InspectorScroll")
    inspector_scroll.setWidgetResizable(True)
    inspector_scroll.setFrameShape(QFrame.NoFrame)
    inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    inspector_scroll.setWidget(window.step_editor)
    right_layout.addWidget(inspector_scroll, stretch=1)
    return window.right_panel


def create_inspector_header(window) -> QWidget:
    inspector_head = QWidget()
    inspector_head_layout = QHBoxLayout(inspector_head)
    inspector_head_layout.setContentsMargins(0, 0, 0, 0)
    inspector_head_layout.setSpacing(10)
    inspector_title_box = QVBoxLayout()
    inspector_title_box.setContentsMargins(0, 0, 0, 0)
    inspector_title_box.setSpacing(4)
    window.lbl_inspector_kind = QLabel("Inspector")
    window.lbl_inspector_kind.setObjectName("Eyebrow")
    inspector_title_box.addWidget(window.lbl_inspector_kind)
    window.lbl_inspector_title = QLabel("选择步骤或阶段")
    window.lbl_inspector_title.setObjectName("InspectorTitle")
    inspector_title_box.addWidget(window.lbl_inspector_title)
    inspector_head_layout.addLayout(inspector_title_box, stretch=1)
    window.btn_inspector_copy = QToolButton()
    window.btn_inspector_copy.setObjectName("IconButton")
    window.btn_inspector_copy.setText("⧉")
    window.btn_inspector_copy.setToolTip("复制当前步骤（在列表视图右键也可操作）")
    window.btn_inspector_copy.setAccessibleName("复制步骤")
    inspector_head_layout.addWidget(window.btn_inspector_copy)
    return inspector_head


def setup_border_fold_buttons(window):
    """在面板边框上放置浮动折叠按钮"""
    window.btn_toggle_left = QToolButton(central_widget if (central_widget := window.centralWidget()) else window)
    window.btn_toggle_left.setObjectName("BorderFoldBtn")
    window.btn_toggle_left.setAutoRaise(True)
    window.btn_toggle_left.setFixedSize(20, 40)
    window.btn_toggle_left.setText("◀")
    window.btn_toggle_left.setToolTip("折叠/展开左侧面板")
    window.btn_toggle_left.clicked.connect(window._toggle_left_panel)
    window.btn_toggle_left.setCursor(Qt.PointingHandCursor)
    window.btn_toggle_left.raise_()

    window.btn_toggle_right = QToolButton(central_widget if (central_widget := window.centralWidget()) else window)
    window.btn_toggle_right.setObjectName("BorderFoldBtn")
    window.btn_toggle_right.setAutoRaise(True)
    window.btn_toggle_right.setFixedSize(20, 40)
    window.btn_toggle_right.setText("▶")
    window.btn_toggle_right.setToolTip("折叠/展开右侧面板")
    window.btn_toggle_right.clicked.connect(window._toggle_right_panel)
    window.btn_toggle_right.setCursor(Qt.PointingHandCursor)
    window.btn_toggle_right.raise_()


def refresh_border_fold_buttons(window):
    """刷新边框折叠按钮样式"""
    C = get_colors(window._dark_mode)
    btn_style = f"""
        QToolButton#BorderFoldBtn {{
            background: {C["surface_primary"]};
            color: {C["text_secondary"]};
            border: 1px solid {C["border"]};
            border-radius: 4px;
            padding: 0;
            font-size: 12px;
            font-weight: bold;
        }}
        QToolButton#BorderFoldBtn:hover {{
            color: {C["primary"]};
            background: {C["hover"]};
            border: 1px solid {C["primary"]};
        }}
    """
    if hasattr(window, 'btn_toggle_left'):
        window.btn_toggle_left.setStyleSheet(btn_style)
    if hasattr(window, 'btn_toggle_right'):
        window.btn_toggle_right.setStyleSheet(btn_style)


def setup_toolbar(window):
    """设置工具栏"""
    toolbar = QToolBar("主工具栏")
    toolbar.setMovable(False)
    toolbar.setObjectName("MainToolbar")
    toolbar.setFixedHeight(44)
    toolbar.setVisible(False)
    window.addToolBar(toolbar)

    window.action_import = QAction("导入", window)
    window.action_import.setIcon(window.style().standardIcon(QStyle.SP_DialogOpenButton))
    window.action_import.triggered.connect(window._action_import_json)
    window.action_import.setToolTip("导入工作流 JSON")
    toolbar.addAction(window.action_import)

    window.action_export = QAction("导出", window)
    window.action_export.setIcon(window.style().standardIcon(QStyle.SP_DialogSaveButton))
    window.action_export.triggered.connect(window._action_export_json)
    window.action_export.setToolTip("导出当前工作流为 JSON")
    toolbar.addAction(window.action_export)

    toolbar.addSeparator()

    window.action_webhook = QAction("Webhook 管理", window)
    window.action_webhook.triggered.connect(window._open_webhook_manager)
    window.action_webhook.setToolTip("配置运行通知 Webhook")
    toolbar.addAction(window.action_webhook)

    toolbar.addSeparator()

    window.action_dark_mode = QAction("切换主题", window)
    window.action_dark_mode.setVisible(False)
    window.action_dark_mode.setEnabled(False)

    window.action_save_shortcut = QAction("保存", window)
    window.action_save_shortcut.setShortcut("Ctrl+S")
    window.action_save_shortcut.triggered.connect(window._action_save)
    window.action_save_shortcut.setToolTip("保存当前工作流和步骤修改")
    window.addAction(window.action_save_shortcut)

    window.action_run_shortcut = QAction("运行", window)
    window.action_run_shortcut.setShortcut("F5")
    window.action_run_shortcut.triggered.connect(window.btn_header_run.click)
    window.action_run_shortcut.setToolTip("运行或停止当前工作流")
    window.addAction(window.action_run_shortcut)

    # R3-#5: Shift+F5 停止运行（仅运行中可用；状态在 _on_workflow_started/finished 切换）
    window.action_stop_shortcut = QAction("停止运行", window)
    window.action_stop_shortcut.setShortcut("Shift+F5")
    window.action_stop_shortcut.setEnabled(False)
    window.action_stop_shortcut.triggered.connect(window._stop_workflow)
    window.action_stop_shortcut.setToolTip("停止当前运行中的工作流")
    window.addAction(window.action_stop_shortcut)

    if hasattr(window, "btn_asset_import"):
        window.btn_asset_import.clicked.connect(window.action_import.trigger)
    if hasattr(window, "btn_asset_export"):
        window.btn_asset_export.clicked.connect(window.action_export.trigger)
    if hasattr(window, "btn_asset_webhook"):
        window.btn_asset_webhook.clicked.connect(window.action_webhook.trigger)


def apply_theme(window):
    C = get_colors(window._dark_mode)

    app = QApplication.instance()
    if app:
        app.setStyleSheet(get_stylesheet(dark=window._dark_mode))

    tokens = build_shell_theme_tokens(C, window._dark_mode)
    window.left_panel.setStyleSheet(left_panel_stylesheet(tokens))
    window.center_container.setStyleSheet(center_panel_stylesheet(tokens))
    window.mode_tabs.setStyleSheet(mode_tabs_stylesheet(tokens))
    window.right_panel.setStyleSheet(right_panel_stylesheet(tokens))

    window._refresh_border_fold_buttons()

    window.workflow_list.refresh_theme(window._dark_mode)
    window.run_control.refresh_theme(window._dark_mode)
    window.log_panel.refresh_theme(window._dark_mode)
    window.run_history.refresh_theme(window._dark_mode)
    window.step_table.refresh_theme(window._dark_mode)
    window.workbench_board.refresh_theme(window._dark_mode)
    window.step_editor.refresh_theme(window._dark_mode)
    window.workflow_config.refresh_theme(window._dark_mode)
    window.step_table.table.refresh_theme(window._dark_mode)
    # R3-#6: 主题切换同步刷新监听指示器对比度
    try:
        running = "监听中" in window._watch_indicator.text()
        window._refresh_watch_indicator_theme(running=running)
    except Exception:
        pass
    try:
        window._shortcut_hint.setStyleSheet(
            f"color: {C['text_tertiary']}; padding-left: 8px;"
        )
    except Exception:
        pass
    try:
        stopping = bool(getattr(window, "_stopping_in_progress", False))
        running = bool(getattr(window.engine, "is_running", False))
        set_header_run_button_state(
            window,
            "stopping" if stopping else ("running" if running else "idle"),
        )
    except Exception:
        pass
    # R7-#2: 主题切换同步刷新后台运行标签
    try:
        window._refresh_bg_running_label_theme()
    except Exception:
        pass


def setup_statusbar(window):
    """设置状态栏"""
    window.statusbar = QStatusBar()
    window.setStatusBar(window.statusbar)
    window.statusbar.setFixedHeight(28)
    window.statusbar.showMessage("就绪")
    from PySide6.QtWidgets import QLabel
    # R6-#1 / R7-#2: 持久化的"后台运行中"指示器（仅当显示工作流 != 运行工作流时可见）
    # 浅主题用 #B25000（对白底 ~5.0:1 达 AA），暗主题保留 #FF9500（对深底 ~4.9:1）；
    # 加下划线增强"可点击"感知
    window._bg_running_label = QLabel("")
    window._bg_running_label.setVisible(False)
    window._bg_running_label.setToolTip("点击切回正在运行的工作流以查看进度/停止")
    window._bg_running_label.setCursor(Qt.PointingHandCursor)
    window._refresh_bg_running_label_theme()
    window._bg_running_label.mousePressEvent = window._on_bg_running_label_clicked
    window.statusbar.addPermanentWidget(window._bg_running_label)
    # R2-#4 / R3-#6 / R3-#7: 持久化的监听状态指示器
    # - 用 ▶ / ⏸ 不同字符区分（不仅靠颜色）→ 色盲友好
    # - 暗色主题下用 #AEAEB2 提升对比度（>4.5:1 AA）
    window._watch_indicator = QLabel("⏸ 未监听")
    # R4-#8: 显式用 Segoe UI Symbol 字体，避免 ⏸ U+23F8 在精简版 Windows 字体回退异常
    try:
        from PySide6.QtGui import QFont
        window._watch_indicator.setFont(QFont("Segoe UI Symbol"))
    except Exception:
        pass
    window._refresh_watch_indicator_theme(running=False)
    window._watch_indicator.setToolTip("文件监听状态")
    window.statusbar.addPermanentWidget(window._watch_indicator)
    window._shortcut_hint = QLabel("快捷键: Ctrl+S 保存 | F5 运行/停止 | Shift+F5 停止")
    window._shortcut_hint.setToolTip("常用快捷键")
    window.statusbar.addPermanentWidget(window._shortcut_hint)


def connect_signals(window):
    """连接信号"""
    window.main_splitter.splitterMoved.connect(lambda: window._update_border_widget_positions())

    window.workflow_list.workflow_selected.connect(window._on_workflow_selected)
    window.workflow_list.workflow_deleted.connect(window._on_workflow_deleted)

    window.step_table.step_selected.connect(window._on_step_selected)
    window.step_table.step_deleted.connect(window._on_step_deleted)
    window.step_table.steps_changed.connect(window._on_steps_changed)

    window.workbench_board.step_selected.connect(window._on_step_selected)
    window.workbench_board.stage_selected.connect(window._on_stage_selected)
    window.workbench_board.add_step_requested.connect(window._on_add_step_requested)
    window.workbench_board.add_stage_requested.connect(window._on_add_stage_requested)
    window.workbench_board.reorder_requested.connect(window._on_board_reorder_requested)

    window.step_editor.step_saved.connect(window._on_step_saved)
    window.step_editor.step_delete_requested.connect(window._on_step_delete_requested)
    window.step_editor.step_run_requested.connect(window._on_step_run_requested)
    window.step_editor.navigate_to_step.connect(window._on_dag_step_activated)

    window.workflow_config.workflow_updated.connect(window._on_workflow_updated)

    window.run_control.run_requested.connect(window._on_run_requested)

    window.engine.workflow_started.connect(window._on_workflow_started)
    window.engine.workflow_finished.connect(window._on_workflow_finished)
    window.engine.step_started.connect(window._on_step_started)
    window.engine.step_finished.connect(window._on_step_finished)
    window.engine.log_output.connect(window.log_panel.append_log)
    window.engine.progress_updated.connect(window._on_progress_updated)
    window.engine.error_details.connect(window._on_error_details)
    # R2-#4: 监听状态信号 → 持久指示器
    window.engine.watch_started.connect(window._on_watch_started)
    window.engine.watch_stopped.connect(window._on_watch_stopped)

    window.log_panel.stop_clicked.connect(window._stop_workflow)

    window.run_control.dry_run_clicked.connect(window._on_dry_run)

    window.run_history.open_failures_requested.connect(window._open_failures_for_history)
    window.run_history.force_stop_requested.connect(window._on_force_stop_run)
