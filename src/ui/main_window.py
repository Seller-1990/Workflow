# -*- coding: utf-8 -*-
"""主窗口"""

import logging
import threading

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStatusBar, QToolBar, QMessageBox,
    QScrollArea, QFrame, QLabel, QPushButton, QToolButton,
    QSizePolicy, QLayout, QStyle, QApplication, QTabWidget,
    QStackedWidget, QButtonGroup
)
from PySide6.QtCore import Qt, Slot, QSize, QSettings, QPoint, QTimer
from PySide6.QtGui import QAction, QIcon

logger = logging.getLogger(__name__)

from config import APP_NAME, APP_VERSION, ICON_PATH
from database import (
    init_db,
    get_workflow_by_id,
    delete_step,
    get_step_by_id,
    get_steps_by_workflow,
    list_stages,
    create_step,
    create_stage,
)
from engine import WorkflowEngine
from ui.theme import (
    get_colors,
    get_stylesheet,
    get_danger_button_stylesheet,
    msg_information,
    msg_warning,
    msg_critical,
    msg_question,
)
from ui.workflow_list import WorkflowListPanel
from ui.step_table import StepTablePanel
from ui.step_editor import StepEditorPanel
from ui.dag_view import DAGViewPanel
from ui.log_panel import LogPanel
from ui.run_history import RunHistoryPanel
from ui.run_control import RunControlPanel
from ui.workflow_config import WorkflowConfigPanel
from ui.webhook_manager import WebhookManagerDialog
from ui.error_summary import ErrorSummaryDialog
from ui.ios_switch import IosSwitch
from ui.workbench_board import WorkbenchBoardPanel
from ui.json_actions import export_json_action, import_json_action
from ui.main_window_theme import (
    build_shell_theme_tokens,
    center_panel_stylesheet,
    left_panel_stylesheet,
    mode_tabs_stylesheet,
    right_panel_stylesheet,
)
from ui.panel_layout import expanded_splitter_sizes, panel_toggle_text, run_splitter_sizes
from ui.run_actions import run_engine_mode
from ui.run_state import compute_run_lock_state
from ui import dirty_guard, run_dispatch, watch_status_controller


class MainWindow(QMainWindow):
    """主窗口
    
    布局结构：
    - 左侧（可折叠）：工作流列表 + 运行控制
    - 中区：
        - 上部：基础配置（折叠）
        - 中部：DAG + 步骤列表
        - 下部：步骤详情编辑器
    - 右侧（可折叠）：实时日志 + 运行历史
    """
    
    def __init__(self):
        super().__init__()
        
        init_db()
        
        self.engine = WorkflowEngine(self)

        self._current_workflow_id = None
        self._running_workflow_id = None  # R5-#1: 正在运行的工作流（与显示分离）
        self._running_workflow_name = None  # R6-#1: 缓存的运行工作流名，避免重复查 DB
        self._pending_retry_cb = None  # R8-#1: F5「停止并运行新的」的待重试回调
        self._watching_workflows: dict[int, list] = {}  # M1: workflow_id -> 监听目录（指示器聚合）
        self._edit_mode = False

        settings = QSettings(APP_NAME, "ui")  # U-P3-2: 统一 QSettings 节点
        # 固定浅色主题：旧版本保存过的深色偏好会在启动时被清掉。
        self._dark_mode = False
        settings.setValue("dark_mode", False)
        
        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()

        self._apply_theme()

        self._set_edit_mode(False)
        
        self.workflow_list.load_workflows()

        # M1: 启动后恢复所有 watch_enabled 工作流的监听（事件循环就绪后执行）
        QTimer.singleShot(0, self._restore_watches_on_startup)
    
    def _setup_ui(self):
        """设置 UI"""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        # U-P3-9：1366x768 笔记本兼容（原 1200x800 在 125% DPI 下溢出屏幕）
        self.setMinimumSize(1024, 680)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setObjectName("MainSplitter")
        self.main_splitter.setHandleWidth(1)
        self.main_splitter.setChildrenCollapsible(False)
        main_layout.addWidget(self.main_splitter)

        self.main_splitter.addWidget(self._create_left_panel())

        # ===== 中间：工作台 =====
        self.center_container = QFrame()
        self.center_container.setObjectName("CenterPanel")
        center_layout = QVBoxLayout(self.center_container)
        center_layout.setContentsMargins(22, 20, 22, 22)
        center_layout.setSpacing(16)
        center_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.center_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        center_layout.addWidget(self._create_command_bar())

        self.mode_tabs = QTabWidget()
        self.mode_tabs.setObjectName("ModeTabs")
        self.mode_tabs.setDocumentMode(True)

        self._add_plan_tab()

        self._add_run_tab()
        self._add_config_tab()
        center_layout.addWidget(self.mode_tabs, stretch=1)

        self.main_splitter.addWidget(self.center_container)

        self.main_splitter.addWidget(self._create_right_panel())

        self.main_splitter.setSizes([280, 840, 340])

        # 旧折叠按钮不再作为工作台 UI 入口，保留隐藏对象以兼容运行状态逻辑。
        self.btn_toggle_left = QToolButton(central_widget)
        self.btn_toggle_left.hide()
        self.btn_toggle_right = QToolButton(central_widget)
        self.btn_toggle_right.hide()

        self._left_last_size = 280
        self._right_last_size = 340
        self._run_splitter_user_adjusted = False
        self._apply_run_splitter_profile("idle", force=True)

        self.step_table.setAccessibleName("步骤列表")
        self.run_control.btn_run_all.setAccessibleName("全流程运行")
        self.run_control.btn_run_from.setAccessibleName("从选中步骤开始")
        self.run_control.btn_run_only.setAccessibleName("只运行选中步骤")
        self.run_control.btn_retry.setAccessibleName("重试失败步骤")
        self.run_control.btn_dry_run.setAccessibleName("工作流预演")
        self.run_control.btn_cancel.setAccessibleName("停止运行")

        self.btn_view_board.clicked.connect(lambda: self._set_plan_view(0))
        self.btn_view_dag.clicked.connect(lambda: self._set_plan_view(1))
        self.btn_view_table.clicked.connect(lambda: self._set_plan_view(2))

    def _create_left_panel(self) -> QFrame:
        self.left_panel = QFrame()
        self.left_panel.setObjectName("LeftPanel")
        self.left_panel.setMinimumWidth(240)
        self.left_panel.setMaximumWidth(320)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(14, 18, 14, 14)
        left_layout.setSpacing(14)
        left_layout.addWidget(self._create_brand_row())

        self.workflow_list = WorkflowListPanel()
        left_layout.addWidget(self.workflow_list, stretch=1)

        asset_label = QLabel("资产")
        asset_label.setObjectName("SidebarLabel")
        left_layout.addWidget(asset_label)
        self.btn_asset_import = self._create_sidebar_button("导入 JSON", "导入工作流 JSON", "导入 JSON")
        self.btn_asset_export = self._create_sidebar_button("导出 JSON", "导出当前工作流为 JSON", "导出 JSON")
        self.btn_asset_webhook = self._create_sidebar_button("Webhook", "配置运行通知 Webhook", "Webhook 管理")
        left_layout.addWidget(self.btn_asset_import)
        left_layout.addWidget(self.btn_asset_export)
        left_layout.addWidget(self.btn_asset_webhook)
        left_layout.addWidget(self._create_edit_bar())

        self.run_control = RunControlPanel()
        self.run_control.setVisible(False)
        left_layout.addWidget(self.run_control)
        return self.left_panel

    def _create_brand_row(self) -> QWidget:
        brand_row = QWidget()
        brand_layout = QHBoxLayout(brand_row)
        brand_layout.setContentsMargins(2, 0, 2, 0)
        brand_layout.setSpacing(10)
        self.lbl_brand_icon = QLabel()
        self.lbl_brand_icon.setObjectName("BrandMark")
        self.lbl_brand_icon.setFixedSize(36, 36)
        if ICON_PATH.exists():
            pix = QIcon(str(ICON_PATH)).pixmap(36, 36)
            self.lbl_brand_icon.setPixmap(pix)
        brand_layout.addWidget(self.lbl_brand_icon)

        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(2)
        self.lbl_brand_name = QLabel("Workflow")
        self.lbl_brand_name.setObjectName("BrandName")
        brand_text.addWidget(self.lbl_brand_name)
        self.lbl_brand_subtitle = QLabel("本地自动化工作台")
        self.lbl_brand_subtitle.setObjectName("BrandSubtitle")
        brand_text.addWidget(self.lbl_brand_subtitle)
        brand_layout.addLayout(brand_text, stretch=1)
        return brand_row

    def _create_sidebar_button(self, text: str, tooltip: str, accessible_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("SidebarNav")
        button.setToolTip(tooltip)
        button.setAccessibleName(accessible_name)
        return button

    def _create_edit_bar(self) -> QWidget:
        edit_bar = QWidget()
        edit_bar.setObjectName("foldBar")
        edit_bar_layout = QHBoxLayout(edit_bar)
        edit_bar_layout.setContentsMargins(4, 0, 4, 0)
        edit_bar_layout.setSpacing(10)
        edit_bar_layout.addWidget(QLabel("编辑模式"))
        edit_bar_layout.addStretch()

        self.check_edit_mode = IosSwitch()
        self.check_edit_mode.setChecked(False)
        self.check_edit_mode.toggled.connect(self._set_edit_mode)
        self.check_edit_mode.setToolTip("开启后可以编辑工作流、阶段和步骤")
        edit_bar_layout.addWidget(self.check_edit_mode)

        self.btn_left_save = QPushButton("保存")
        self.btn_left_save.setObjectName("primarySmall")
        self.btn_left_save.setFixedSize(78, 26)
        self.btn_left_save.clicked.connect(self._action_save)
        self.btn_left_save.setToolTip("保存当前工作流和步骤修改")
        edit_bar_layout.addWidget(self.btn_left_save)
        return edit_bar

    def _create_command_bar(self) -> QWidget:
        command_bar = QWidget()
        command_bar.setObjectName("CommandBar")
        command_layout = QHBoxLayout(command_bar)
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.setSpacing(20)
        command_layout.addLayout(self._create_title_block(), stretch=1)
        command_layout.addWidget(self._create_run_cluster())
        return command_bar

    def _create_title_block(self) -> QVBoxLayout:
        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(4)
        self.lbl_workflow_eyebrow = QLabel("当前工作流")
        self.lbl_workflow_eyebrow.setObjectName("Eyebrow")
        title_block.addWidget(self.lbl_workflow_eyebrow)
        self.lbl_workflow_title = QLabel("请选择工作流")
        self.lbl_workflow_title.setObjectName("WorkflowTitle")
        title_block.addWidget(self.lbl_workflow_title)
        self.lbl_workflow_meta = QLabel("0 阶段 · 0 步 · 未运行")
        self.lbl_workflow_meta.setObjectName("WorkflowMeta")
        title_block.addWidget(self.lbl_workflow_meta)
        return title_block

    def _create_run_cluster(self) -> QWidget:
        run_cluster = QWidget()
        run_cluster.setObjectName("RunCluster")
        run_layout = QHBoxLayout(run_cluster)
        run_layout.setContentsMargins(0, 0, 0, 0)
        run_layout.setSpacing(8)
        self.lbl_run_state = QLabel("● 就绪")
        self.lbl_run_state.setObjectName("RunStateChip")
        self.lbl_run_state.setToolTip("当前运行状态")
        run_layout.addWidget(self.lbl_run_state)
        self.btn_header_run = QPushButton("▶ 运行全流程")
        self.btn_header_run.setObjectName("PrimaryAction")
        self.btn_header_run.setToolTip("运行当前工作流的全流程（F5）")
        self.btn_header_run.setAccessibleName("运行全流程")
        self.btn_header_run.clicked.connect(lambda: self._on_run_requested("full", None))
        run_layout.addWidget(self.btn_header_run)
        self.btn_header_stop = QToolButton()
        self.btn_header_stop.setObjectName("DangerIconButton")
        self.btn_header_stop.setText("■")
        self.btn_header_stop.setToolTip("停止当前运行（Shift+F5）")
        self.btn_header_stop.setAccessibleName("停止运行")
        self.btn_header_stop.clicked.connect(self._stop_workflow)
        self.btn_header_stop.setEnabled(False)
        run_layout.addWidget(self.btn_header_stop)
        return run_cluster

    def _add_plan_tab(self) -> None:
        plan_page = QWidget()
        plan_layout = QVBoxLayout(plan_page)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        plan_layout.setSpacing(12)
        plan_layout.addWidget(self._create_plan_switch())
        plan_layout.addWidget(self._create_plan_stack(), stretch=1)

        self.plan_scroll = QScrollArea()
        self.plan_scroll.setWidgetResizable(True)
        self.plan_scroll.setFrameShape(QFrame.NoFrame)
        self.plan_scroll.setWidget(plan_page)
        self.center_scroll = self.plan_scroll
        self.mode_tabs.addTab(self.plan_scroll, "编排")

    def _create_plan_switch(self) -> QWidget:
        plan_switch = QWidget()
        switch_layout = QHBoxLayout(plan_switch)
        switch_layout.setContentsMargins(0, 0, 0, 0)
        switch_layout.setSpacing(8)
        self.btn_view_board = QPushButton("阶段")
        self.btn_view_board.setObjectName("ViewSwitchActive")
        self.btn_view_board.setToolTip("阶段泳道编排视图")
        self.btn_view_board.setAccessibleName("阶段视图")
        self.btn_view_dag = QPushButton("批次")
        self.btn_view_dag.setObjectName("ViewSwitch")
        self.btn_view_dag.setToolTip("查看自动计算的批次与依赖图")
        self.btn_view_dag.setAccessibleName("批次视图")
        self.btn_view_table = QPushButton("列表")
        self.btn_view_table.setObjectName("ViewSwitch")
        self.btn_view_table.setToolTip("使用表格查看和批量调整步骤")
        self.btn_view_table.setAccessibleName("列表视图")
        self._view_buttons = [
            (self.btn_view_board, 0),
            (self.btn_view_dag, 1),
            (self.btn_view_table, 2),
        ]
        switch_layout.addWidget(self.btn_view_board)
        switch_layout.addWidget(self.btn_view_dag)
        switch_layout.addWidget(self.btn_view_table)
        switch_layout.addStretch(1)
        return plan_switch

    def _create_plan_stack(self) -> QStackedWidget:
        self.plan_stack = QStackedWidget()
        self.plan_stack.setObjectName("PlanStack")
        self.workbench_board = WorkbenchBoardPanel()
        self.plan_stack.addWidget(self.workbench_board)
        self.dag_view = DAGViewPanel()
        self.dag_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.plan_stack.addWidget(self.dag_view)
        self.step_table = StepTablePanel()
        self.step_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.plan_stack.addWidget(self.step_table)
        return self.plan_stack

    def _add_run_tab(self) -> None:
        run_page = QWidget()
        run_page_layout = QVBoxLayout(run_page)
        run_page_layout.setContentsMargins(0, 0, 0, 0)
        run_page_layout.setSpacing(0)
        self.run_splitter = QSplitter(Qt.Vertical)
        self.run_splitter.setObjectName("RunSplitter")
        self.run_splitter.setChildrenCollapsible(False)
        self.run_splitter.setHandleWidth(5)
        self.log_panel = LogPanel()
        self.log_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.run_history = RunHistoryPanel()
        self.run_history.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.run_history.setMinimumHeight(240)
        self.log_panel.setMinimumHeight(300)
        self.run_splitter.addWidget(self.run_history)
        self.run_splitter.addWidget(self.log_panel)
        self.run_splitter.setSizes([360, 560])
        self.run_splitter.splitterMoved.connect(self._on_run_splitter_moved)
        run_page_layout.addWidget(self.run_splitter)
        self.mode_tabs.addTab(run_page, "运行")

    def _add_config_tab(self) -> None:
        self.workflow_config = WorkflowConfigPanel()
        self.workflow_config.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setFrameShape(QFrame.NoFrame)
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        config_scroll.setWidget(self.workflow_config)
        self.mode_tabs.addTab(config_scroll, "配置")

    def _create_right_panel(self) -> QFrame:
        self.right_panel = QFrame()
        self.right_panel.setObjectName("RightPanel")
        self.right_panel.setMinimumWidth(320)
        self.right_panel.setMaximumWidth(390)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(14, 18, 14, 16)
        right_layout.setSpacing(10)
        right_layout.addWidget(self._create_inspector_header())

        self.step_editor = StepEditorPanel()
        self.step_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        inspector_scroll = QScrollArea()
        inspector_scroll.setObjectName("InspectorScroll")
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setFrameShape(QFrame.NoFrame)
        inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inspector_scroll.setWidget(self.step_editor)
        right_layout.addWidget(inspector_scroll, stretch=1)
        return self.right_panel

    def _create_inspector_header(self) -> QWidget:
        inspector_head = QWidget()
        inspector_head_layout = QHBoxLayout(inspector_head)
        inspector_head_layout.setContentsMargins(0, 0, 0, 0)
        inspector_head_layout.setSpacing(10)
        inspector_title_box = QVBoxLayout()
        inspector_title_box.setContentsMargins(0, 0, 0, 0)
        inspector_title_box.setSpacing(4)
        self.lbl_inspector_kind = QLabel("Inspector")
        self.lbl_inspector_kind.setObjectName("Eyebrow")
        inspector_title_box.addWidget(self.lbl_inspector_kind)
        self.lbl_inspector_title = QLabel("选择步骤或阶段")
        self.lbl_inspector_title.setObjectName("InspectorTitle")
        inspector_title_box.addWidget(self.lbl_inspector_title)
        inspector_head_layout.addLayout(inspector_title_box, stretch=1)
        self.btn_inspector_copy = QToolButton()
        self.btn_inspector_copy.setObjectName("IconButton")
        self.btn_inspector_copy.setText("⧉")
        self.btn_inspector_copy.setToolTip("复制当前步骤（在列表视图右键也可操作）")
        self.btn_inspector_copy.setAccessibleName("复制步骤")
        inspector_head_layout.addWidget(self.btn_inspector_copy)
        return inspector_head

    def _setup_border_fold_buttons(self):
        """在面板边框上放置浮动折叠按钮"""
        self.btn_toggle_left = QToolButton(central_widget if (central_widget := self.centralWidget()) else self)
        self.btn_toggle_left.setObjectName("BorderFoldBtn")
        self.btn_toggle_left.setAutoRaise(True)
        self.btn_toggle_left.setFixedSize(20, 40)
        self.btn_toggle_left.setText("◀")
        self.btn_toggle_left.setToolTip("折叠/展开左侧面板")
        self.btn_toggle_left.clicked.connect(self._toggle_left_panel)
        self.btn_toggle_left.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_left.raise_()

        self.btn_toggle_right = QToolButton(central_widget if (central_widget := self.centralWidget()) else self)
        self.btn_toggle_right.setObjectName("BorderFoldBtn")
        self.btn_toggle_right.setAutoRaise(True)
        self.btn_toggle_right.setFixedSize(20, 40)
        self.btn_toggle_right.setText("▶")
        self.btn_toggle_right.setToolTip("折叠/展开右侧面板")
        self.btn_toggle_right.clicked.connect(self._toggle_right_panel)
        self.btn_toggle_right.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_right.raise_()

    def _update_border_widget_positions(self):
        """更新浮动折叠按钮位置（基于 center_scroll 边缘定位）"""
        cw = self.centralWidget()
        if not cw:
            return
        cw_pos = cw.mapTo(self, QPoint(0, 0))
        center_pos = self.center_scroll.mapTo(self, QPoint(0, 0))
        center_h = self.center_scroll.height()

        if hasattr(self, 'btn_toggle_left'):
            x = center_pos.x() - 10
            y = center_pos.y() + (center_h - 40) // 2
            self.btn_toggle_left.move(x, y)

        if hasattr(self, 'btn_toggle_right'):
            x = center_pos.x() + self.center_scroll.width() - 10
            y = center_pos.y() + (center_h - 40) // 2
            self.btn_toggle_right.move(x, y)

    def _refresh_border_fold_buttons(self):
        """刷新边框折叠按钮样式"""
        C = get_colors(self._dark_mode)
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
        if hasattr(self, 'btn_toggle_left'):
            self.btn_toggle_left.setStyleSheet(btn_style)
        if hasattr(self, 'btn_toggle_right'):
            self.btn_toggle_right.setStyleSheet(btn_style)

    def _setup_toolbar(self):
        """设置工具栏"""
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.setObjectName("MainToolbar")
        toolbar.setFixedHeight(44)
        toolbar.setVisible(False)
        self.addToolBar(toolbar)

        self.action_import = QAction("导入", self)
        self.action_import.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.action_import.triggered.connect(self._action_import_json)
        self.action_import.setToolTip("导入工作流 JSON")
        toolbar.addAction(self.action_import)
        
        self.action_export = QAction("导出", self)
        self.action_export.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.action_export.triggered.connect(self._action_export_json)
        self.action_export.setToolTip("导出当前工作流为 JSON")
        toolbar.addAction(self.action_export)

        toolbar.addSeparator()

        self.action_webhook = QAction("Webhook 管理", self)
        self.action_webhook.triggered.connect(self._open_webhook_manager)
        self.action_webhook.setToolTip("配置运行通知 Webhook")
        toolbar.addAction(self.action_webhook)

        toolbar.addSeparator()

        self.action_dark_mode = QAction("切换主题", self)
        self.action_dark_mode.setVisible(False)
        self.action_dark_mode.setEnabled(False)

        self.action_save_shortcut = QAction("保存", self)
        self.action_save_shortcut.setShortcut("Ctrl+S")
        self.action_save_shortcut.triggered.connect(self._action_save)
        self.action_save_shortcut.setToolTip("保存当前工作流和步骤修改")
        self.addAction(self.action_save_shortcut)

        self.action_run_shortcut = QAction("运行", self)
        self.action_run_shortcut.setShortcut("F5")
        self.action_run_shortcut.triggered.connect(self.run_control.btn_run_all.click)
        self.action_run_shortcut.setToolTip("运行当前工作流")
        self.addAction(self.action_run_shortcut)

        # R3-#5: Shift+F5 停止运行（仅运行中可用；状态在 _on_workflow_started/finished 切换）
        self.action_stop_shortcut = QAction("停止运行", self)
        self.action_stop_shortcut.setShortcut("Shift+F5")
        self.action_stop_shortcut.setEnabled(False)
        self.action_stop_shortcut.triggered.connect(self._stop_workflow)
        self.action_stop_shortcut.setToolTip("停止当前运行中的工作流")
        self.addAction(self.action_stop_shortcut)

        if hasattr(self, "btn_asset_import"):
            self.btn_asset_import.clicked.connect(self.action_import.trigger)
        if hasattr(self, "btn_asset_export"):
            self.btn_asset_export.clicked.connect(self.action_export.trigger)
        if hasattr(self, "btn_asset_webhook"):
            self.btn_asset_webhook.clicked.connect(self.action_webhook.trigger)

    def _set_plan_view(self, index: int):
        self.plan_stack.setCurrentIndex(index)
        for btn, stack_index in getattr(self, "_view_buttons", []):
            btn.setObjectName("ViewSwitchActive" if stack_index == index else "ViewSwitch")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_run_splitter_moved(self, *_args):
        self._run_splitter_user_adjusted = True

    def _apply_run_splitter_profile(self, profile: str, *, force: bool = False):
        if not hasattr(self, "run_splitter"):
            return
        if self._run_splitter_user_adjusted and not force:
            return
        sizes = run_splitter_sizes(profile)
        self.run_splitter.blockSignals(True)
        try:
            self.run_splitter.setSizes(sizes)
        finally:
            self.run_splitter.blockSignals(False)
        if force:
            self._run_splitter_user_adjusted = False

    def _toggle_dark_mode(self, checked):
        self._dark_mode = False
        settings = QSettings(APP_NAME, "ui")  # U-P3-2: 统一 QSettings 节点
        settings.setValue("dark_mode", False)
        self._apply_theme()

    def _apply_theme(self):
        C = get_colors(self._dark_mode)

        app = QApplication.instance()
        if app:
            app.setStyleSheet(get_stylesheet(dark=self._dark_mode))

        tokens = build_shell_theme_tokens(C, self._dark_mode)
        self.left_panel.setStyleSheet(left_panel_stylesheet(tokens))
        self.center_container.setStyleSheet(center_panel_stylesheet(tokens))
        self.mode_tabs.setStyleSheet(mode_tabs_stylesheet(tokens))
        self.right_panel.setStyleSheet(right_panel_stylesheet(tokens))

        self._refresh_border_fold_buttons()

        self.workflow_list.refresh_theme(self._dark_mode)
        self.run_control.refresh_theme(self._dark_mode)
        self.log_panel.refresh_theme(self._dark_mode)
        self.run_history.refresh_theme(self._dark_mode)
        self.dag_view.refresh_theme(self._dark_mode)
        self.step_table.refresh_theme(self._dark_mode)
        self.workbench_board.refresh_theme(self._dark_mode)
        self.step_editor.refresh_theme(self._dark_mode)
        self.workflow_config.refresh_theme(self._dark_mode)
        self.step_table.table.refresh_theme(self._dark_mode)
        # R3-#6: 主题切换同步刷新监听指示器对比度
        try:
            running = "监听中" in self._watch_indicator.text()
            self._refresh_watch_indicator_theme(running=running)
        except Exception:
            pass
        try:
            self._shortcut_hint.setStyleSheet(
                f"color: {C['text_tertiary']}; padding-left: 8px;"
            )
        except Exception:
            pass
        try:
            self._statusbar_stop_btn.setStyleSheet(get_danger_button_stylesheet(self._dark_mode))
        except Exception:
            pass
        # R7-#2: 主题切换同步刷新后台运行标签
        try:
            self._refresh_bg_running_label_theme()
        except Exception:
            pass

    def _set_edit_mode(self, enabled: bool):
        enabled = bool(enabled)
        if self._edit_mode == enabled:
            return
        self._edit_mode = enabled
        self.workflow_list.set_edit_enabled(self._edit_mode)
        self.workflow_config.set_edit_enabled(self._edit_mode)
        self.step_table.set_edit_enabled(self._edit_mode)
        self.workbench_board.set_edit_enabled(self._edit_mode)
        self.step_editor.set_edit_enabled(self._edit_mode)

        self.statusbar.showMessage("编辑模式：开启" if self._edit_mode else "编辑模式：关闭（防误操作）", 5000)
        self.btn_left_save.setEnabled(self._edit_mode)

    def _require_edit_mode(self, action_name: str) -> bool:
        if self._edit_mode:
            return True
        self.statusbar.showMessage(f"{action_name}：请先开启左侧「编辑」开关", 5000)
        msg_information(self, self._dark_mode, "需要开启编辑", f"{action_name} 前请先开启左侧「编辑」开关。")
        return False

    def is_edit_mode(self) -> bool:
        """返回当前编辑模式状态"""
        return self._edit_mode

    def _action_new_workflow(self):
        if not self._require_edit_mode("新建工作流"):
            return
        self.workflow_list.create_workflow()

    def _action_save(self):
        if not self._require_edit_mode("保存"):
            return
        self._save_current()

    def _action_import_json(self):
        if not self._require_edit_mode("导入 JSON"):
            return
        self._import_json()

    def _action_export_json(self):
        if not self._require_edit_mode("导出 JSON"):
            return
        self._export_json()
    
    def _setup_statusbar(self):
        """设置状态栏"""
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.statusbar.setFixedHeight(28)
        self.statusbar.showMessage("就绪")
        # R2-#8: 持久化的「停止运行」按钮（默认隐藏，运行中显示）
        from PySide6.QtWidgets import QPushButton, QLabel
        self._statusbar_stop_btn = QPushButton("⏹ 停止运行")
        self._statusbar_stop_btn.setVisible(False)
        self._statusbar_stop_btn.setCursor(Qt.PointingHandCursor)
        self._statusbar_stop_btn.setToolTip("停止当前运行中的工作流")
        self._statusbar_stop_btn.setStyleSheet(get_danger_button_stylesheet(self._dark_mode))
        self._statusbar_stop_btn.clicked.connect(self._on_statusbar_stop_clicked)
        self.statusbar.addPermanentWidget(self._statusbar_stop_btn)
        # R6-#1 / R7-#2: 持久化的"后台运行中"指示器（仅当显示工作流 != 运行工作流时可见）
        # 浅主题用 #B25000（对白底 ~5.0:1 达 AA），暗主题保留 #FF9500（对深底 ~4.9:1）；
        # 加下划线增强"可点击"感知
        self._bg_running_label = QLabel("")
        self._bg_running_label.setVisible(False)
        self._bg_running_label.setToolTip("点击切回正在运行的工作流以查看进度/停止")
        self._bg_running_label.setCursor(Qt.PointingHandCursor)
        self._refresh_bg_running_label_theme()
        self._bg_running_label.mousePressEvent = self._on_bg_running_label_clicked
        self.statusbar.addPermanentWidget(self._bg_running_label)
        # R2-#4 / R3-#6 / R3-#7: 持久化的监听状态指示器
        # - 用 ▶ / ⏸ 不同字符区分（不仅靠颜色）→ 色盲友好
        # - 暗色主题下用 #AEAEB2 提升对比度（>4.5:1 AA）
        self._watch_indicator = QLabel("⏸ 未监听")
        # R4-#8: 显式用 Segoe UI Symbol 字体，避免 ⏸ U+23F8 在精简版 Windows 字体回退异常
        try:
            from PySide6.QtGui import QFont
            self._watch_indicator.setFont(QFont("Segoe UI Symbol"))
        except Exception:
            pass
        self._refresh_watch_indicator_theme(running=False)
        self._watch_indicator.setToolTip("文件监听状态")
        self.statusbar.addPermanentWidget(self._watch_indicator)
        self._shortcut_hint = QLabel("快捷键: Ctrl+S 保存 | F5 运行 | Shift+F5 停止")
        self._shortcut_hint.setToolTip("常用快捷键")
        self.statusbar.addPermanentWidget(self._shortcut_hint)
    
    def _connect_signals(self):
        """连接信号"""
        self.main_splitter.splitterMoved.connect(lambda: self._update_border_widget_positions())

        self.workflow_list.workflow_selected.connect(self._on_workflow_selected)
        self.workflow_list.workflow_deleted.connect(self._on_workflow_deleted)
        
        self.step_table.step_selected.connect(self._on_step_selected)
        self.step_table.step_deleted.connect(self._on_step_deleted)
        self.step_table.steps_changed.connect(self._on_steps_changed)

        self.workbench_board.step_selected.connect(self._on_step_selected)
        self.workbench_board.stage_selected.connect(self._on_stage_selected)
        self.workbench_board.add_step_requested.connect(self._on_add_step_requested)
        self.workbench_board.add_stage_requested.connect(self._on_add_stage_requested)
        self.workbench_board.reorder_requested.connect(self._on_board_reorder_requested)

        self.dag_view.step_activated.connect(self._on_dag_step_activated)

        self.step_editor.step_saved.connect(self._on_step_saved)
        self.step_editor.step_delete_requested.connect(self._on_step_delete_requested)
        self.step_editor.step_run_requested.connect(self._on_step_run_requested)
        self.step_editor.navigate_to_step.connect(self._on_dag_step_activated)

        self.workflow_config.workflow_updated.connect(self._on_workflow_updated)
        
        self.run_control.run_requested.connect(self._on_run_requested)
        
        self.engine.workflow_started.connect(self._on_workflow_started)
        self.engine.workflow_finished.connect(self._on_workflow_finished)
        self.engine.step_started.connect(self._on_step_started)
        self.engine.step_finished.connect(self._on_step_finished)
        self.engine.log_output.connect(self.log_panel.append_log)
        self.engine.progress_updated.connect(self._on_progress_updated)
        self.engine.error_details.connect(self._on_error_details)
        # R2-#4: 监听状态信号 → 持久指示器
        self.engine.watch_started.connect(self._on_watch_started)
        self.engine.watch_stopped.connect(self._on_watch_stopped)

        self.log_panel.stop_clicked.connect(self._stop_workflow)
        
        self.run_control.dry_run_clicked.connect(self._on_dry_run)

        self.run_history.open_failures_requested.connect(self._open_failures_for_history)
        self.run_history.force_stop_requested.connect(self._on_force_stop_run)
    
    # ===== 槽函数 =====
    
    @Slot(int)
    def _on_workflow_selected(self, workflow_id: int):
        """工作流被选中"""
        # R4-#2: 短路——同 id 重复触发（如 _on_workflow_updated 间接重入）时直接返回，
        # 避免清空 step_editor / 重做 4-5 个 DB 查询；首次进入仍走完整路径
        if workflow_id == self._current_workflow_id and workflow_id is not None:
            return
        # R4-#3 / R5-#4: 运行中切换前确认；不立刻执行 engine.cancel()，
        # 等下一个未保存确认弹窗也通过后再 commit，避免用户在第二弹窗
        # 选「留在当前」后旧运行已被不可逆停止。
        pending_stop_running = False
        if self._current_workflow_id is not None and self._current_workflow_id != workflow_id \
                and getattr(self.engine, "is_running", False):
            choice = self._confirm_switch_while_running(target=workflow_id)
            if choice == "cancel":
                self._restore_selection_silently("switch_workflow")
                return
            pending_stop_running = (choice == "stop")
        # #5: 切换工作流前，如步骤编辑器有未保存改动，弹三选项确认
        if not self._confirm_discard_unsaved(reason="switch_workflow", new_target=workflow_id):
            return
        # R5-#4: 两个弹窗都已确认，现在才真正发起停止
        if pending_stop_running:
            try:
                self.engine.cancel()
                # R6-#3: 标记一个"正在停止中"窗口，让 _refresh_run_lock_panels 暂时不显示
                # 「↻ 后台运行」标签——用户感知就是"已请求停止"而不是"还在后台运行"
                self._stopping_in_progress = True
                self.statusbar.showMessage("已请求停止当前运行...", 3000)
            except Exception as e:
                logger.warning("请求停止失败: %s", e)
        self._current_workflow_id = workflow_id
        # R5-#1: 切换显示后立刻按 running 状态刷新面板锁
        self._refresh_run_lock_panels()

        # P-4: 先把"用户立即关注"的内容加载完（workflow_config + step_table 配置开关），
        # 然后把更重的 dag_view / run_history 推到下一轮事件循环异步加载，
        # 让切换工作流的视觉响应从 ~80-400ms 降到 ~50ms。
        self.workflow_config.load_workflow(workflow_id)

        workflow = get_workflow_by_id(workflow_id)
        single_enabled = bool(workflow.single_script_enabled) if workflow else False
        self.step_table.set_single_script_mode(single_enabled)
        self.step_editor.set_single_script_mode(single_enabled)

        parallel_enabled = bool(workflow.parallel_enabled) if workflow else False
        self.step_table.set_parallel_available(parallel_enabled)
        self.step_editor.set_parallel_available(parallel_enabled)

        self.step_table.load_steps(workflow_id)
        self.workbench_board.load_workflow(workflow_id)
        self._refresh_workbench_header(workflow_id)

        # P-4: 异步推迟下面两个相对重的 panel；先让 UI 把已加载内容渲染出来
        QTimer.singleShot(0, lambda wid=workflow_id: self._async_load_dag(wid))
        QTimer.singleShot(0, lambda wid=workflow_id: self._async_load_history(wid))

        self.log_panel.set_context(workflow_id=workflow_id, step_id=None)

        self.step_editor.clear()

        if workflow:
            self.statusbar.showMessage(f"当前工作流: {workflow.name}", 5000)
            self.lbl_inspector_kind.setText("Inspector")
            self.lbl_inspector_title.setText("选择步骤或阶段")

        # #1: 切换工作流时同步监听状态——engine.start_watch 内部会先 stop，再按 watch_enabled 决定是否启动
        self._sync_engine_watch(workflow)

    def _async_load_dag(self, workflow_id: int) -> None:
        # 如果用户在异步加载触发前又切了工作流，跳过陈旧加载
        if workflow_id != self._current_workflow_id:
            return
        try:
            self.dag_view.update_dag(workflow_id)
        except Exception as e:
            logger.warning("异步加载 DAG 失败: %s", e)

    def _async_load_history(self, workflow_id: int) -> None:
        if workflow_id != self._current_workflow_id:
            return
        try:
            self.run_history.load_history(workflow_id)
        except Exception as e:
            logger.warning("异步加载历史失败: %s", e)

    # ==================== #5 未保存改动确认 ====================
    def _confirm_switch_while_running(self, target) -> str:
        """R4-#3 / R5-#4: 运行中切换工作流弹窗。

        Returns:
            "cancel"        → 留在当前，不切换
            "stop"          → 切换且应在后续合适时机停止运行
            "keep_running"  → 切换并保留后台运行
        本函数不再直接调用 engine.cancel()——延迟到所有确认串联通过后再 commit，
        避免用户在第二个弹窗反悔时旧运行已被不可逆停止。
        """
        from PySide6.QtWidgets import QMessageBox
        # R5-#1: 文案改为如实说明——后台继续会失去可视化反馈通道
        running_wf_name = "?"
        try:
            from database import get_workflow_by_id as _gwf
            wf = _gwf(self._current_workflow_id)
            if wf:
                running_wf_name = wf.name
        except Exception:
            pass
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("运行进行中")
        box.setText(
            f"工作流「{running_wf_name}」正在运行中。\n\n"
            "• 停止运行并切换：终止当前运行后再切换\n"
            "• 后台继续运行并切换：切换到新工作流，原运行继续，"
            "但将失去对它的进度可见性与停止入口（需返回原工作流才能查看/停止）\n"
            "• 留在当前：不切换"
        )
        stop_and_switch = box.addButton("停止运行并切换", QMessageBox.DestructiveRole)
        keep_running_switch = box.addButton("后台继续运行并切换", QMessageBox.AcceptRole)
        cancel = box.addButton("留在当前", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is cancel:
            return "cancel"
        if clicked is stop_and_switch:
            return "stop"
        return "keep_running"

    def _confirm_discard_unsaved(self, *, reason: str, new_target) -> bool:
        """#5: 脏改动"保存 / 不保存 / 取消"三选项确认（实现在 ui.dirty_guard）。"""
        return dirty_guard.confirm_discard_unsaved(self, reason=reason, new_target=new_target)

    def _should_check_workflow_config_dirty(self, reason: str) -> bool:
        """是否需要检查工作流配置脏状态（实现在 ui.dirty_guard）。"""
        return dirty_guard.should_check_workflow_config_dirty(self, reason)

    def _is_panel_dirty(self, panel, panel_name: str) -> bool:
        """面板脏状态检查（实现在 ui.dirty_guard）。"""
        return dirty_guard.is_panel_dirty(self, panel, panel_name)

    def _build_dirty_message(self, reason: str, *, config_dirty: bool, step_dirty: bool) -> str:
        """构造未保存提示文案（实现在 ui.dirty_guard）。"""
        return dirty_guard.build_dirty_message(self, reason, config_dirty=config_dirty, step_dirty=step_dirty)

    def _save_dirty_panels(self, *, config_dirty: bool, step_dirty: bool) -> bool:
        """保存脏面板并复查（实现在 ui.dirty_guard）。"""
        return dirty_guard.save_dirty_panels(self, config_dirty=config_dirty, step_dirty=step_dirty)

    def _discard_dirty_panels(self, *, config_dirty: bool, step_dirty: bool) -> bool:
        """丢弃脏面板修改（实现在 ui.dirty_guard）。"""
        return dirty_guard.discard_dirty_panels(self, config_dirty=config_dirty, step_dirty=step_dirty)

    def _discard_panel_changes(self, panel, panel_name: str) -> bool:
        """丢弃单个面板修改（实现在 ui.dirty_guard）。"""
        return dirty_guard.discard_panel_changes(self, panel, panel_name)

    def _reset_panel_dirty_state(self, panel, panel_name: str) -> bool:
        """重置单个面板脏状态（实现在 ui.dirty_guard）。"""
        return dirty_guard.reset_panel_dirty_state(self, panel, panel_name)

    def _restore_selection_silently(self, reason: str) -> bool:
        """R2-#3 / R4-#7: 静默回滚 UI 选中状态，避免引发新一轮选中信号。

        支持 reason: switch_workflow / switch_step
        """
        if reason == "switch_workflow":
            return self._restore_workflow_selection_silently()
        elif reason in {"switch_step", "switch_stage"}:
            return self._restore_step_selection_silently()
        return True

    def _restore_step_selection_silently(self) -> bool:
        """R4-#7: switch_step 取消路径——把 step_table 行选回当前编辑器的 step_id。"""
        try:
            target_step_id = getattr(self.step_editor, "_step_id", None) or getattr(
                self.step_editor, "current_step_id", None
            )
            if not target_step_id:
                return True
            target_step_id = int(target_step_id)
            try:
                self.step_table.select_step(target_step_id, emit_signal=False)
                selection = self.step_table.get_selection_snapshot()
            except Exception as exc:
                logger.warning("回滚步骤表选中失败: step_id=%s, error=%s", target_step_id, exc, exc_info=True)
                return False
            if selection.get("step_id") != target_step_id:
                logger.warning("回滚步骤表选中后状态不一致: expected=%s, actual=%s", target_step_id, selection)
                return False
            try:
                self.workbench_board.select_step(target_step_id, emit_signal=False)
            except Exception as exc:
                logger.warning("回滚看板步骤选中失败: step_id=%s, error=%s", target_step_id, exc, exc_info=True)
                return False
            return True
        except Exception as e:
            logger.warning("回滚步骤选中失败: %s", e)
            return False

    def _restore_workflow_selection_silently(self) -> bool:
        """R2-#3 / R3-#1 / R4-#7: switch_workflow 取消路径的原逻辑提取。"""
        if self._current_workflow_id is None:
            return True
        try:
            # 直接定位 QListWidget 并 blockSignals
            lw = getattr(self.workflow_list, "list_widget", None)
            if lw is None:
                return True
            blocker_active = lw.signalsBlocked()
            lw.blockSignals(True)
            try:
                matched = False
                for i in range(lw.count()):
                    item = lw.item(i)
                    if item and item.data(Qt.UserRole) == self._current_workflow_id:
                        lw.setCurrentItem(item)
                        matched = True
                        break
                # R3-#1: 过滤态下找不到匹配（旧工作流被搜索过滤掉了）：
                # 只清空列表选中，不改当前工作流上下文；中间面板仍显示旧工作流。
                if not matched:
                    lw.setCurrentRow(-1)
            finally:
                lw.blockSignals(blocker_active)
            return True
        except Exception as e:
            logger.warning("回滚选中失败: %s", e)
            return False

    def _sync_engine_watch(self, workflow) -> None:
        """根据 workflow.watch_enabled 启停该工作流的监听（实现在 ui.watch_status_controller）。"""
        watch_status_controller.sync_engine_watch(self, workflow)

    def _restore_watches_on_startup(self) -> None:
        """M1 启动恢复监听 + M7 修复展示（实现在 ui.watch_status_controller）。"""
        watch_status_controller.restore_watches_on_startup(self)

    def _update_watch_indicator(self) -> None:
        """M1: 按当前监听集合刷新指示器（实现在 ui.watch_status_controller）。"""
        watch_status_controller.update_watch_indicator(self)

    @Slot(int, list)
    def _on_watch_started(self, workflow_id: int, folders: list) -> None:
        """R2-#4 / M1: 监听启动 → 聚合到指示器"""
        watch_status_controller.on_watch_started(self, workflow_id, folders)

    @Slot(int)
    def _on_watch_stopped(self, workflow_id: int) -> None:
        """R2-#4 / M1: 监听停止 → 从聚合中移除"""
        watch_status_controller.on_watch_stopped(self, workflow_id)

    def _refresh_watch_indicator_theme(self, running: bool) -> None:
        """R3-#6 / R4-#8: 指示器主题色（实现在 ui.watch_status_controller）。"""
        watch_status_controller.refresh_watch_indicator_theme(self, running)

    def _refresh_bg_running_label_theme(self) -> None:
        """R7-#2 / R8-#2: 后台运行标签——浅主题用 #B25000 (~5.0:1)、暗主题保持 #FF9500；
        用 QFont.setUnderline 而非 QSS text-decoration（QLabel QSS 不支持后者）。
        """
        try:
            dark = getattr(self, "_dark_mode", False)
            color = "#FF9500" if dark else "#B25000"
            self._bg_running_label.setStyleSheet(
                f"color: {color}; padding: 0 8px; font-weight: 600;"
            )
            # R8-#2: QLabel QSS 不识别 text-decoration，必须走 QFont
            from PySide6.QtGui import QFont as _QFont
            f = _QFont(self._bg_running_label.font())
            f.setUnderline(True)
            self._bg_running_label.setFont(f)
        except Exception:
            pass

    def _refresh_run_lock_panels(self) -> None:
        """R5-#1 / R6-#1: 仅当显示的工作流 == 正在运行的工作流时锁定编辑面板。

        否则用户后台运行旧工作流又切到新工作流，新工作流面板会被无理由禁用。
        额外更新"后台运行中"持久指示器（QLabel，常驻状态栏）。
        """
        running_id = getattr(self, "_running_workflow_id", None)
        current_id = self._current_workflow_id
        stopping = getattr(self, "_stopping_in_progress", False)
        state = compute_run_lock_state(
            running_id=running_id,
            current_id=current_id,
            engine_running=bool(getattr(self.engine, "is_running", False)),
            stopping=stopping,
            running_name=getattr(self, "_running_workflow_name", None),
        )
        # R6-#4: 兜底——若 engine.is_running 已为 False 但 _running_workflow_id 还非空
        # （理论上 finished 信号一定会清；这里防御未来 signal_policy 不对称导致永久卡住）
        if state.clear_stale_running:
            self._running_workflow_id = None
            self._running_workflow_name = None
            self._stopping_in_progress = False
            running_id = None
        lock_panels = state.lock_panels
        try:
            self.workflow_config.setEnabled(not lock_panels)
            self.step_table.setEnabled(not lock_panels)
            self.step_editor.setEnabled(not lock_panels)
        except Exception:
            pass
        # R6-#1: 后台运行（运行中但用户切走了）→ 持久指示器；同步可见性
        # R6-#3: stop 请求已发出但 finished 信号未到的窗口，暂不显示"后台运行"标签
        try:
            if state.show_background_label:
                self._bg_running_label.setText(state.background_label_text)
                self._bg_running_label.setVisible(True)
            else:
                self._bg_running_label.setVisible(False)
        except Exception:
            pass

    def _on_bg_running_label_clicked(self, _event) -> None:
        """R6-#1: 点击「后台运行：XX」标签 → 切回正在运行的工作流"""
        running_id = getattr(self, "_running_workflow_id", None)
        if running_id is None:
            return
        try:
            lw = getattr(self.workflow_list, "list_widget", None)
            if lw is None:
                return
            for i in range(lw.count()):
                it = lw.item(i)
                if it and it.data(Qt.UserRole) == running_id:
                    lw.setCurrentItem(it)
                    return
        except Exception as e:
            logger.warning("切回运行工作流失败: %s", e)
    
    @Slot(int)
    def _on_workflow_deleted(self, workflow_id: int):
        """工作流被删除"""
        # M1: 精确停掉被删工作流的监听（不影响其它工作流）
        try:
            self.engine.stop_watch(workflow_id)
        except Exception as e:
            logger.warning("停止被删工作流监听失败: %s", e)
        if self._current_workflow_id == workflow_id:
            self._current_workflow_id = None
            self.workflow_config.clear()
            self.step_table.clear()
            self.workbench_board.clear()
            self.dag_view.clear()
            self.step_editor.clear()
            self.run_history.clear()
            self.log_panel.set_context(workflow_id=None, step_id=None)
            self._refresh_workbench_header(None)

    def _refresh_workbench_header(self, workflow_id: int | None):
        if not workflow_id:
            self.lbl_workflow_title.setText("请选择工作流")
            self.lbl_workflow_meta.setText("0 阶段 · 0 步 · 未运行")
            return
        workflow = get_workflow_by_id(workflow_id)
        stages = list_stages(workflow_id)
        steps = get_steps_by_workflow(workflow_id)
        self.lbl_workflow_title.setText(workflow.name if workflow else f"工作流 #{workflow_id}")
        parallel = "自动并行" if (workflow and workflow.parallel_enabled) else "串行"
        self.lbl_workflow_meta.setText(f"{len(stages)} 阶段 · {len(steps)} 步 · {parallel}")

    @Slot(str)
    def _on_stage_selected(self, stage_uid: str):
        if not stage_uid:
            return
        current_step_id = getattr(self.step_editor, "_step_id", None)
        selected_stage_uid = None
        step_table_selection = {}
        try:
            step_table_selection = self.step_table.get_selection_snapshot()
        except Exception:
            step_table_selection = {}
        try:
            selected_stage_uid = self.workbench_board.selected_stage_uid()
        except Exception:
            selected_stage_uid = step_table_selection.get("stage_uid")
        if not current_step_id and selected_stage_uid == stage_uid:
            return
        if not self._confirm_discard_unsaved(reason="switch_stage", new_target=stage_uid):
            return
        stage_label = stage_uid
        try:
            stages = list_stages(self._current_workflow_id)
            for idx, stage in enumerate(stages, start=1):
                if stage.uid == stage_uid:
                    stage_label = f"S{idx} {stage.name}"
                    break
        except Exception:
            pass
        try:
            self.workbench_board.select_stage(stage_uid, emit_signal=False)
        except Exception as exc:
            logger.warning("同步看板阶段选中失败: stage_uid=%s, error=%s", stage_uid, exc, exc_info=True)
            return
        try:
            self.step_table.set_selected_stage_context(stage_uid, clear_step_selection=True)
        except Exception as exc:
            logger.warning("同步步骤表阶段上下文失败: stage_uid=%s, error=%s", stage_uid, exc, exc_info=True)
            return
        self.lbl_inspector_kind.setText("选中阶段")
        self.lbl_inspector_title.setText(stage_label)
        self.step_editor.clear()
        self.run_control.set_selected_step(None, stage_uid)
        self.log_panel.set_context(workflow_id=self._current_workflow_id, step_id=None)

    @Slot(str)
    def _on_add_step_requested(self, stage_uid: str):
        if not self._current_workflow_id:
            return
        if not self._require_edit_mode("添加步骤"):
            return
        try:
            steps = get_steps_by_workflow(self._current_workflow_id)
            next_order = max([int(s.order or 0) for s in steps], default=-1) + 1
            stage_uid = stage_uid or self.workbench_board.selected_stage_uid()
            step = create_step(
                self._current_workflow_id,
                name="新步骤",
                step_type="python",
                script_path="",
                order=next_order,
                stage_uid=stage_uid,
            )
        except Exception as e:
            msg_critical(self, self._dark_mode, "添加失败", str(e))
            return
        self._reload_workflow_surfaces(select_step_id=step.id if step else None)
        self.statusbar.showMessage("已添加步骤", 5000)

    @Slot(str)
    def _on_add_stage_requested(self, stage_uid: str):
        if not self._current_workflow_id:
            return
        if not self._require_edit_mode("新增阶段"):
            return
        try:
            stages = list_stages(self._current_workflow_id)
            order_by_uid = {stage.uid: int(stage.order or 0) for stage in stages}
            base_order = order_by_uid.get(stage_uid, max(order_by_uid.values(), default=0))
            stage = create_stage(self._current_workflow_id, name="新阶段", order=base_order + 1)
        except Exception as e:
            msg_critical(self, self._dark_mode, "新增阶段失败", str(e))
            return
        self._reload_workflow_surfaces(select_stage_uid=stage.uid if stage else None)
        self.statusbar.showMessage("已新增阶段", 5000)

    @Slot(int, str, list)
    def _on_board_reorder_requested(self, step_id: int, target_stage_uid: str, ordered_step_ids: list):
        if not self._current_workflow_id:
            return
        if not self._require_edit_mode("拖拽调整步骤"):
            return
        ok = self.step_table.apply_orders_and_stage_updates(
            {int(step_id): target_stage_uid},
            [int(sid) for sid in ordered_step_ids],
        )
        if not ok:
            self.workbench_board.load_workflow(self._current_workflow_id)
            return
        self._reload_workflow_surfaces(select_step_id=int(step_id))
        self.statusbar.showMessage("已更新步骤阶段和顺序", 5000)

    def _reload_workflow_surfaces(self, *, select_step_id: int | None = None, select_stage_uid: str | None = None):
        if not self._current_workflow_id:
            return
        wid = self._current_workflow_id
        self.step_table.load_steps(wid)
        self.workbench_board.load_workflow(wid)
        self._refresh_workbench_header(wid)
        QTimer.singleShot(0, lambda w=wid: self._async_load_dag(w))
        if select_step_id:
            self.step_table.select_step(select_step_id)
            self.workbench_board.select_step(select_step_id, emit_signal=False)
            self._on_step_selected(select_step_id)
        elif select_stage_uid:
            self.workbench_board.select_stage(select_stage_uid, emit_signal=False)
            self._on_stage_selected(select_stage_uid)
    
    @Slot(int)
    def _on_step_selected(self, step_id: int):
        """步骤被选中"""
        try:
            if int(getattr(self.step_editor, "_step_id", 0) or 0) == int(step_id):
                return
        except (TypeError, ValueError):
            pass
        # #5: 切换步骤前，如编辑器有未保存改动，弹三选项确认
        if not self._confirm_discard_unsaved(reason="switch_step", new_target=step_id):
            return
        try:
            self.step_table.select_step(step_id, emit_signal=False)
        except Exception:
            pass
        self.step_editor.load_step(step_id)
        try:
            self.workbench_board.select_step(step_id, emit_signal=False)
        except Exception:
            pass
        try:
            step = get_step_by_id(step_id)
            if step:
                self.lbl_inspector_kind.setText("选中步骤")
                self.lbl_inspector_title.setText(step.name)
        except Exception:
            pass
        stage_uid = None
        if step_id:
            # R3-#10: 优先用 step_table 已缓存的 row_meta；缺失再回退 DB（兼容旧入口）
            stage_uid = self.step_table.get_stage_uid_for_step(step_id)
            if stage_uid is None:
                try:
                    step = get_step_by_id(step_id)
                    if step:
                        stage_uid = step.stage_uid
                except Exception as e:
                    logger.warning("回退查询 step.stage_uid 失败: %s", e)
        self.run_control.set_selected_step(step_id, stage_uid)
        self.log_panel.set_context(workflow_id=self._current_workflow_id, step_id=step_id)

    @Slot(int)
    def _on_step_delete_requested(self, step_id: int):
        """从步骤编辑器发起删除。"""
        if not step_id:
            return
        if not self._require_edit_mode("删除步骤"):
            return

        step = get_step_by_id(step_id)
        if not step:
            msg_warning(self, self._dark_mode, "删除失败", "步骤不存在，可能已被删除。")
            if self._current_workflow_id:
                self.step_table.load_steps(self._current_workflow_id)
            self._on_step_deleted(step_id)
            return

        reply = msg_question(
            self,
            self._dark_mode,
            "确认删除步骤",
            f"确定要删除步骤「{step.name}」吗？\n此操作不可撤销，未保存修改也会丢失。",
        )
        if reply != QMessageBox.Yes:
            return

        try:
            ok = delete_step(step_id)
        except Exception as e:
            msg_critical(self, self._dark_mode, "删除失败", str(e))
            return
        if not ok:
            msg_warning(self, self._dark_mode, "删除失败", "步骤不存在或删除失败。")
            return

        if self._current_workflow_id:
            wid = self._current_workflow_id
            self.step_table.load_steps(wid)
            QTimer.singleShot(0, lambda w=wid: self._async_load_dag(w))
        self._on_step_deleted(step_id)
        self.statusbar.showMessage("已删除步骤", 5000)

    @Slot(str, int)
    def _on_step_run_requested(self, mode: str, step_id: int):
        """从 Inspector 发起单步运行。"""
        if mode not in ("only_step", "from_step"):
            return
        self._on_run_requested(mode, step_id)

    @Slot(int)
    def _on_step_deleted(self, step_id: int):
        """步骤被删除后，清理仍指向该步骤的上下文。"""
        current_step_id = getattr(self.step_editor, "_step_id", None)
        if current_step_id != step_id:
            if self._current_workflow_id:
                self.workbench_board.load_workflow(self._current_workflow_id)
            return
        self.step_editor.clear()
        if self._current_workflow_id:
            self.workbench_board.load_workflow(self._current_workflow_id)
            self._refresh_workbench_header(self._current_workflow_id)
        self.run_control.set_selected_step(None, None)
        self.log_panel.set_context(workflow_id=self._current_workflow_id, step_id=None)
        self.lbl_inspector_kind.setText("Inspector")
        self.lbl_inspector_title.setText("选择步骤或阶段")

    @Slot(int)
    def _on_dag_step_activated(self, step_id: int):
        """DAG 双击节点：定位到步骤列表并打开编辑器"""
        if not step_id:
            return
        self.step_table.select_step(step_id)
        self._on_step_selected(step_id)
    
    @Slot()
    def _on_steps_changed(self):
        """步骤发生变化"""
        if self._current_workflow_id:
            wid = self._current_workflow_id
            selection = {}
            try:
                selection = self.step_table.get_selection_snapshot()
            except Exception:
                selection = {}
            current_step_id = getattr(self.step_editor, "_step_id", None) or selection.get("step_id")
            current_stage_uid = None
            if current_step_id:
                try:
                    current_stage_uid = self.step_table.get_stage_uid_for_step(current_step_id)
                except Exception:
                    current_stage_uid = None
            if not current_stage_uid:
                current_stage_uid = selection.get("stage_uid") or self.workbench_board.selected_stage_uid()
            self._reload_steps_views(wid, restore_step_id=current_step_id, restore_stage_uid=current_stage_uid, reload_editor=True)
    
    @Slot()
    def _on_step_saved(self):
        """步骤保存"""
        if self._current_workflow_id:
            wid = self._current_workflow_id
            current_step_id = getattr(self.step_editor, "_step_id", None)
            current_stage_uid = None
            if current_step_id:
                try:
                    current_stage_uid = self.step_table.get_stage_uid_for_step(current_step_id)
                except Exception:
                    current_stage_uid = None
            self._reload_steps_views(wid, restore_step_id=current_step_id, restore_stage_uid=current_stage_uid)

    def _reload_steps_views(
        self,
        workflow_id: int,
        *,
        restore_step_id: int | None = None,
        restore_stage_uid: str | None = None,
        reload_editor: bool = False,
    ) -> None:
        self.step_table.load_steps(workflow_id)
        self.workbench_board.load_workflow(workflow_id)
        self._refresh_workbench_header(workflow_id)
        QTimer.singleShot(0, lambda w=workflow_id: self._async_load_dag(w))

        def _clear_step_context() -> None:
            try:
                self.step_table.set_selected_stage_context(None, clear_step_selection=True)
            except Exception as exc:
                logger.warning("清空步骤表阶段上下文失败: workflow_id=%s, error=%s", workflow_id, exc, exc_info=True)
            self.step_editor.clear()
            self.lbl_inspector_kind.setText("Inspector")
            self.lbl_inspector_title.setText("选择步骤或阶段")
            self.run_control.set_selected_step(None, None)
            self.log_panel.set_context(workflow_id=workflow_id, step_id=None)

        def _restore_stage_context(stage_uid: str | None) -> None:
            if not stage_uid:
                _clear_step_context()
                return
            stage_label = stage_uid
            try:
                stages = list_stages(workflow_id)
                for idx, stage in enumerate(stages, start=1):
                    if stage.uid == stage_uid:
                        stage_label = f"S{idx} {stage.name}"
                        break
            except Exception as exc:
                logger.warning("恢复阶段标题失败: workflow_id=%s, stage_uid=%s, error=%s", workflow_id, stage_uid, exc)
            try:
                self.workbench_board.select_stage(stage_uid, emit_signal=False)
            except Exception as exc:
                logger.warning("恢复看板阶段选中失败: stage_uid=%s, error=%s", stage_uid, exc, exc_info=True)
                return
            try:
                self.step_table.set_selected_stage_context(stage_uid, clear_step_selection=True)
            except Exception as exc:
                logger.warning("恢复步骤表阶段上下文失败: stage_uid=%s, error=%s", stage_uid, exc, exc_info=True)
                return
            self.lbl_inspector_kind.setText("选中阶段")
            self.lbl_inspector_title.setText(stage_label)
            self.step_editor.clear()
            self.run_control.set_selected_step(None, stage_uid)
            self.log_panel.set_context(workflow_id=workflow_id, step_id=None)

        def _restore_step_context(step_id: int | None, fallback_stage_uid: str | None) -> None:
            if not step_id:
                _restore_stage_context(fallback_stage_uid)
                return
            if not self.step_table.has_step(int(step_id)):
                _restore_stage_context(fallback_stage_uid)
                return
            try:
                self.step_table.select_step(int(step_id), emit_signal=False)
            except Exception as exc:
                logger.warning("恢复步骤表步骤选中失败: step_id=%s, error=%s", step_id, exc, exc_info=True)
                _restore_stage_context(fallback_stage_uid)
                return
            try:
                self.workbench_board.select_step(int(step_id), emit_signal=False)
            except Exception as exc:
                logger.warning("恢复看板步骤选中失败: step_id=%s, error=%s", step_id, exc, exc_info=True)
                _restore_stage_context(fallback_stage_uid)
                return
            if reload_editor:
                try:
                    self.step_editor.load_step(int(step_id))
                except Exception as exc:
                    logger.warning("恢复步骤编辑器失败: step_id=%s, error=%s", step_id, exc, exc_info=True)
                    _restore_stage_context(fallback_stage_uid)
                    return
            try:
                step = get_step_by_id(int(step_id))
                if step:
                    self.lbl_inspector_kind.setText("选中步骤")
                    self.lbl_inspector_title.setText(step.name)
            except Exception as exc:
                logger.warning("恢复步骤 Inspector 标题失败: step_id=%s, error=%s", step_id, exc)
            stage_uid = fallback_stage_uid
            if stage_uid is None:
                try:
                    stage_uid = self.step_table.get_stage_uid_for_step(int(step_id))
                except Exception as exc:
                    logger.warning("恢复步骤阶段上下文失败: step_id=%s, error=%s", step_id, exc)
                    stage_uid = None
            self.run_control.set_selected_step(int(step_id), stage_uid)
            self.log_panel.set_context(workflow_id=workflow_id, step_id=int(step_id))

        QTimer.singleShot(0, lambda sid=restore_step_id, stage_uid=restore_stage_uid: _restore_step_context(sid, stage_uid))

    @Slot()
    def _on_workflow_updated(self):
        """工作流配置更新"""
        if self._current_workflow_id:
            wid = self._current_workflow_id
            self.workflow_list.load_workflows(selected_workflow_id=wid)
            workflow = get_workflow_by_id(wid)
            single_enabled = bool(workflow.single_script_enabled) if workflow else False
            self.step_table.set_single_script_mode(single_enabled)
            self.step_editor.set_single_script_mode(single_enabled)
            parallel_enabled = bool(workflow.parallel_enabled) if workflow else False
            self.step_table.set_parallel_available(parallel_enabled)
            self.step_editor.set_parallel_available(parallel_enabled)
            self.step_table.load_steps(wid)
            self.workbench_board.load_workflow(wid)
            self._refresh_workbench_header(wid)
            # R3-#9 / #15: 把较重的 DAG / history 异步刷新，避免一次性触发 4-5 个 DB 查询阻塞主线程
            QTimer.singleShot(0, lambda w=wid: self._async_load_dag(w))
            QTimer.singleShot(0, lambda w=wid: self._async_load_history(w))
            # #1: 配置变更后重启监听以应用新的 watch_enabled / 目录 / 模式
            self._sync_engine_watch(workflow)

    @Slot(bool)
    def _on_run_requested(self, mode: str, param):
        """运行请求（实现在 ui.run_dispatch：含运行中三选弹窗与停止重试链）"""
        run_dispatch.on_run_requested(self, mode, param)

    @Slot(int, str)
    def _on_workflow_started(self, workflow_id: int, run_id: str):
        """工作流开始"""
        # R5-#1: 记录正在运行的 workflow_id，供面板锁定守卫与切换显示判断使用
        self._running_workflow_id = workflow_id
        # R6-#1: 缓存名字，避免每次切换都查 DB
        try:
            from database import get_workflow_by_id as _gwf
            wf = _gwf(workflow_id)
            self._running_workflow_name = wf.name if wf else None
        except Exception:
            self._running_workflow_name = None
        self.statusbar.showMessage(f"运行中... ({run_id})", 5000)
        self.lbl_run_state.setText("● 运行中")
        self.lbl_run_state.setToolTip(f"当前运行中：{run_id}")
        self.btn_header_run.setEnabled(False)
        self.btn_header_stop.setEnabled(True)
        self._apply_run_splitter_profile("running")

        self.run_control.set_running(True)
        self.log_panel.set_running(True)
        # R2-#8: 状态栏显眼停止按钮
        try:
            self._statusbar_stop_btn.setVisible(True)
        except Exception:
            pass
        # R3-#5: 启用 Shift+F5 停止快捷键
        try:
            self.action_stop_shortcut.setEnabled(True)
        except Exception:
            pass

        # U-P1-7 / R5-#1: 仅当当前显示的工作流 == 正在运行的工作流，才禁用编辑面板。
        # 用户后台运行旧工作流又切到新工作流时，新工作流面板不应被锁。
        self._refresh_run_lock_panels()

        sizes = self.main_splitter.sizes()
        if len(sizes) >= 3 and sizes[2] <= 0:
            sizes[2] = max(getattr(self, "_right_last_size", 340), 320)
            self.main_splitter.setSizes(sizes)
        self.btn_toggle_right.setEnabled(False)

        self.dag_view.reset_all_status()
        self.step_table.reset_all_status()
        self.workbench_board.reset_all_status()

    @Slot(int, str, str)
    def _on_workflow_finished(self, workflow_id: int, run_id: str, status: str):
        """工作流结束"""
        # R5-#1 / R6-#1 / R6-#3: 清理 running_workflow_id + 缓存名字 + stopping 标记
        self._running_workflow_id = None
        self._running_workflow_name = None
        self._stopping_in_progress = False
        self.run_control.set_running(False)
        self.log_panel.set_running(False)
        self.lbl_run_state.setText("● 就绪")
        self.lbl_run_state.setToolTip("当前运行状态：就绪")
        self.btn_header_run.setEnabled(True)
        self.btn_header_stop.setEnabled(False)
        self._apply_run_splitter_profile("idle")
        self.btn_toggle_right.setEnabled(True)
        # R2-#8: 隐藏状态栏停止按钮
        try:
            self._statusbar_stop_btn.setVisible(False)
            # R5-#5: 复位按钮文案/可用性，供下次运行使用
            self._statusbar_stop_btn.setEnabled(True)
            self._statusbar_stop_btn.setText("⏹ 停止运行")
        except Exception:
            pass
        # R3-#5: 禁用 Shift+F5 停止快捷键
        try:
            self.action_stop_shortcut.setEnabled(False)
        except Exception:
            pass

        # U-P1-7 / R5-#1: 用统一守卫恢复面板可编辑性
        self._refresh_run_lock_panels()

        status_map = {
            "success": "完成",
            "failure": "失败",
            "cancelled": "已取消",
        }
        text = status_map.get(status, status)
        self.statusbar.showMessage(f"运行{text} ({run_id})", 5000)

        if self._current_workflow_id == workflow_id:
            # R4-#10: 推迟到下一轮事件循环，避免 finished 信号到达瞬间主线程
            # 立刻执行 get_run_histories + summary 查询（~30-80ms 卡顿）
            QTimer.singleShot(0, lambda wid=workflow_id: self._async_load_history(wid))
    
    @Slot(int, str)
    def _on_step_started(self, step_id: int, step_name: str):
        """步骤开始"""
        self.step_table.highlight_step(step_id, "running")
        self.dag_view.update_step_status(step_id, "running")
        if hasattr(self, "workbench_board"):
            self.workbench_board.highlight_step(step_id, "running")
    
    @Slot(int, str, str, object)
    def _on_step_finished(self, step_id: int, step_name: str, status: str, duration_seconds=None):
        """步骤结束"""
        self.step_table.highlight_step(step_id, status)
        self.dag_view.update_step_status(step_id, status, duration_seconds)
        if hasattr(self, "workbench_board"):
            self.workbench_board.highlight_step(step_id, status, duration_seconds)
    
    @Slot(int, int)
    def _on_progress_updated(self, current: int, total: int):
        """进度更新"""
        self.statusbar.showMessage(f"进度: {current}/{total}")
    
    @Slot(list)
    def _on_error_details(self, error_list: list):
        """失败汇总：日志内联 + 弹窗"""
        self.log_panel.append_error_details(error_list)
        dialog = ErrorSummaryDialog(error_list, self, workflow_id=self._current_workflow_id)
        dialog.navigate_to_step.connect(self._focus_step)
        dialog.retry_failed.connect(lambda: self._on_run_requested("retry_failed", None))
        dialog.open_step_log.connect(lambda sid: self._open_step_log_for_step(sid))
        dialog.exec_()

    @Slot(int)
    def _focus_step(self, step_id: int):
        """定位到步骤（列表选中 + 打开编辑器 + 滚动到可见）"""
        if not step_id:
            return
        try:
            self.step_table.select_step(step_id)
            self._on_step_selected(step_id)
            self.center_scroll.ensureWidgetVisible(self.step_table)
        except Exception:
            return

    def _open_step_log_for_step(self, step_id: int):
        """打开指定步骤在最新一次运行中的日志（复用 LogPanel 的上下文）"""
        if not self._current_workflow_id or not step_id:
            return
        try:
            self.log_panel.set_context(workflow_id=self._current_workflow_id, step_id=step_id)
            self.log_panel.open_step_log()
        except Exception:
            return

    @Slot(int)
    def _open_failures_for_history(self, history_id: int):
        """从运行历史打开失败步骤汇总"""
        if not self._current_workflow_id or not history_id:
            return
        try:
            from database import get_step_logs_by_run, get_steps_by_workflow

            steps = get_steps_by_workflow(self._current_workflow_id)
            step_name_by_id = {s.id: s.name for s in steps}
            logs = get_step_logs_by_run(history_id)
            failures = [
                {
                    "step_id": l.step_id,
                    "step_name": step_name_by_id.get(l.step_id, f"步骤#{l.step_id}"),
                    "error_message": getattr(l, "error_message", "") or "",
                }
                for l in logs
                if l.status == "failure"
            ]
            if not failures:
                msg_information(self, self._dark_mode, "提示", "该次运行没有失败步骤。")
                return
            dialog = ErrorSummaryDialog(failures, self, workflow_id=self._current_workflow_id)
            dialog.navigate_to_step.connect(self._focus_step)
            dialog.retry_failed.connect(lambda: self._on_run_requested("retry_failed", None))
            dialog.open_step_log.connect(lambda sid: self._open_step_log_for_step(sid))
            dialog.exec_()
        except Exception as e:
            msg_warning(self, self._dark_mode, "打开失败汇总失败", str(e))
    
    def _on_dry_run(self):
        """预演模式"""
        if not self._current_workflow_id:
            msg_warning(self, self._dark_mode, "警告", "请先选择一个工作流")
            return
        self.engine.dry_run(self._current_workflow_id)
    
    # ===== 工具栏操作 =====
    
    def _save_current(self):
        """保存当前"""
        config_ok = bool(self.workflow_config.save_config())
        step_ok = True
        has_step = bool(getattr(self.step_editor, "_step_id", None))
        try:
            step_dirty = bool(self.step_editor.is_dirty())
        except Exception:
            step_dirty = False
        if has_step or step_dirty:
            step_ok = bool(self.step_editor.save_step())
        if config_ok and step_ok:
            self.statusbar.showMessage("已保存", 5000)
            return True
        self.statusbar.showMessage("保存未完成，请检查输入后重试", 5000)
        return False
    
    def _run_workflow(self):
        """运行工作流"""
        self._on_run_requested("full", None)
    
    def _stop_workflow(self):
        """停止工作流（实现在 ui.run_dispatch）"""
        run_dispatch.stop_workflow(self)

    @Slot()
    def _on_statusbar_stop_clicked(self):
        """R5-#5: 状态栏停止按钮过渡态（实现在 ui.run_dispatch）"""
        run_dispatch.on_statusbar_stop_clicked(self)
    
    @Slot(int)
    def _on_force_stop_run(self, run_history_id: int):
        """强制停止运行历史中的任务"""
        reply = msg_question(
            self, self._dark_mode, "确认强制停止",
            "确定要强制停止该运行吗？\n未完成的步骤将被标记为已取消。",
        )
        if reply == QMessageBox.Yes:
            self.engine.force_stop_run(run_history_id)
            if self._current_workflow_id:
                self.run_history.load_history(self._current_workflow_id)
    
    def _import_json(self):
        """导入 JSON"""
        import_json_action(
            parent=self,
            dark_mode=self._dark_mode,
            reload_workflows=self.workflow_list.load_workflows,
        )
    
    def _export_json(self):
        """导出 JSON"""
        export_json_action(
            parent=self,
            dark_mode=self._dark_mode,
        )

    def _open_webhook_manager(self):
        """打开 Webhook 管理对话框"""
        dialog = WebhookManagerDialog(self)
        dialog.exec_()
        if hasattr(self, "workflow_config") and hasattr(self.workflow_config, "refresh_webhooks"):
            self.workflow_config.refresh_webhooks()

    def _toggle_left_panel(self):
        """折叠/展开左侧面板"""
        if self.left_panel.isVisible():
            self._left_last_size = self.left_panel.width()
            self.left_panel.setVisible(False)
            self.btn_toggle_left.setText(panel_toggle_text("left", visible=False))
        else:
            self.left_panel.setVisible(True)
            self.left_panel.setMinimumWidth(200)
            sizes = expanded_splitter_sizes(
                self.main_splitter.sizes(),
                panel_index=0,
                last_size=self._left_last_size,
                minimum_size=200,
            )
            if sizes:
                self.main_splitter.setSizes(sizes)
            self.btn_toggle_left.setText(panel_toggle_text("left", visible=True))
        QTimer.singleShot(50, self._update_border_widget_positions)

    def _toggle_right_panel(self):
        """折叠/展开右侧面板"""
        if self.right_panel.isVisible():
            self._right_last_size = self.right_panel.width()
            self.right_panel.setVisible(False)
            self.btn_toggle_right.setText(panel_toggle_text("right", visible=False))
        else:
            self.right_panel.setVisible(True)
            self.right_panel.setMinimumWidth(320)
            sizes = expanded_splitter_sizes(
                self.main_splitter.sizes(),
                panel_index=-1,
                last_size=self._right_last_size,
                minimum_size=320,
            )
            if sizes:
                self.main_splitter.setSizes(sizes)
            self.btn_toggle_right.setText(panel_toggle_text("right", visible=True))
        QTimer.singleShot(50, self._update_border_widget_positions)

    def resizeEvent(self, event):
        """窗口大小变化时更新边框折叠按钮位置"""
        super().resizeEvent(event)
        self._update_border_widget_positions()

    def showEvent(self, event):
        """窗口首次显示时初始化边框折叠按钮位置"""
        super().showEvent(event)
        self._update_border_widget_positions()

    def closeEvent(self, event):
        """关闭事件"""
        if self.engine.is_running:
            reply = msg_question(
                self, self._dark_mode, "确认退出",
                "工作流正在运行，确定要退出吗？",
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
        if not self._confirm_discard_unsaved(reason="close", new_target=None):
            event.ignore()
            return
        if self.engine.is_running:
            self.engine.cancel()
            shutdown_wait = self.engine.wait_for_completion(timeout=10.0)
            if hasattr(self, '_run_thread') and self._run_thread.is_alive():
                self._run_thread.join(timeout=5)
                shutdown_wait = shutdown_wait and (not self._run_thread.is_alive())
        else:
            shutdown_wait = True
        
        try:
            self.engine.workflow_started.disconnect(self._on_workflow_started)
            self.engine.workflow_finished.disconnect(self._on_workflow_finished)
            self.engine.step_started.disconnect(self._on_step_started)
            self.engine.step_finished.disconnect(self._on_step_finished)
            self.engine.log_output.disconnect(self.log_panel.append_log)
            self.engine.progress_updated.disconnect(self._on_progress_updated)
            self.engine.error_details.disconnect(self._on_error_details)
        except (RuntimeError, TypeError):
            pass
        
        try:
            self.engine.shutdown(wait=shutdown_wait)
        except Exception:
            pass
        
        event.accept()
