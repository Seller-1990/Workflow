# -*- coding: utf-8 -*-
"""主窗口"""

import threading

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStatusBar, QToolBar, QMessageBox,
    QScrollArea, QFrame, QLabel, QPushButton, QToolButton,
    QSizePolicy, QLayout
)
from PySide6.QtCore import Qt, Slot, QSize
from PySide6.QtGui import QAction, QIcon

from config import APP_NAME, APP_VERSION, ICON_PATH
from database import init_db, get_workflow_by_id
from engine import WorkflowEngine
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
        
        # 初始化数据库
        init_db()
        
        # 初始化引擎
        self.engine = WorkflowEngine(self)
        
        # 当前选中的工作流 ID
        self._current_workflow_id = None
        self._edit_mode = False
        
        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()

        # 默认关闭编辑（防误操作）
        self._set_edit_mode(False)
        
        # 加载数据
        self.workflow_list.load_workflows()
    
    def _setup_ui(self):
        """设置 UI"""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setMinimumSize(1200, 800)
        
        # 主布局使用 QSplitter
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 主分割器（按 Pencil 定稿：左栏 / 左折叠条 / 中区 / 右折叠条 / 右栏）
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setObjectName("MainSplitter")
        self.main_splitter.setHandleWidth(0)
        main_layout.addWidget(self.main_splitter)
        
        # ===== 左侧面板 =====
        left_panel = QFrame()
        left_panel.setObjectName("LeftPanel")
        left_panel.setMaximumWidth(260)
        left_layout = QVBoxLayout(left_panel)
        # Pencil：Left Panel 宽 260，内部以组件自身 padding 为准
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        
        # 工作流列表
        self.workflow_list = WorkflowListPanel()
        left_layout.addWidget(self.workflow_list, stretch=1)

        # 编辑开关 + 保存（按 Pencil：编辑模式 + iOS Switch + 保存按钮）
        edit_bar = QWidget()
        edit_bar_layout = QHBoxLayout(edit_bar)
        edit_bar_layout.setContentsMargins(4, 0, 4, 0)
        edit_bar_layout.setSpacing(10)
        edit_bar_layout.addWidget(QLabel("编辑模式"))
        edit_bar_layout.addStretch()

        self.check_edit_mode = IosSwitch()
        self.check_edit_mode.setChecked(False)
        # 使用 stateChanged（int->bool）避免个别平台/自绘控件下 toggled 未触发的边缘问题
        self.check_edit_mode.stateChanged.connect(lambda st: self._set_edit_mode(st == Qt.Checked))
        # 冗余兜底：部分情况下 stateChanged/toggled 可能只触发其一（自绘控件/样式差异）
        self.check_edit_mode.toggled.connect(lambda v: self._set_edit_mode(bool(v)))
        edit_bar_layout.addWidget(self.check_edit_mode)

        self.btn_left_save = QPushButton("保存")
        self.btn_left_save.setObjectName("primarySmall")
        self.btn_left_save.setFixedSize(78, 26)
        self.btn_left_save.clicked.connect(self._action_save)
        edit_bar_layout.addWidget(self.btn_left_save)
        left_layout.addWidget(edit_bar)
        
        # 运行控制
        self.run_control = RunControlPanel()
        left_layout.addWidget(self.run_control)
        
        self.main_splitter.addWidget(left_panel)

        # ===== 左侧折叠条（24px）=====
        self.left_fold_strip = QFrame()
        self.left_fold_strip.setObjectName("FoldStrip")
        self.left_fold_strip.setFixedWidth(24)
        strip_l = QVBoxLayout(self.left_fold_strip)
        strip_l.setContentsMargins(0, 0, 0, 0)
        strip_l.setSpacing(0)
        strip_l.addSpacing(230)
        btn_l_wrap = QFrame()
        btn_l_wrap.setObjectName("FoldBtnWrap")
        btn_l_wrap.setFixedSize(20, 28)
        btn_l_layout = QHBoxLayout(btn_l_wrap)
        btn_l_layout.setContentsMargins(0, 0, 0, 0)
        btn_l_layout.setSpacing(0)
        self.btn_toggle_left_strip = QToolButton()
        self.btn_toggle_left_strip.setObjectName("FoldBtn")
        self.btn_toggle_left_strip.setAutoRaise(True)
        self.btn_toggle_left_strip.setFixedSize(20, 28)
        self.btn_toggle_left_strip.setIconSize(QSize(12, 12))
        self.btn_toggle_left_strip.setArrowType(Qt.LeftArrow)
        self.btn_toggle_left_strip.clicked.connect(self._toggle_left_panel)
        btn_l_layout.addWidget(self.btn_toggle_left_strip, alignment=Qt.AlignCenter)
        strip_l.addWidget(btn_l_wrap, alignment=Qt.AlignCenter)
        strip_l.addStretch()
        self.main_splitter.addWidget(self.left_fold_strip)
        
        # ===== 中区面板 =====
        center_container = QFrame()
        center_container.setObjectName("CenterPanel")
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(16)
        # 关键：让 ScrollArea 依据内容计算最小高度，避免“展开后看不见/被挤压为 0 高度”
        # 同时让中区可自然滚动，解决固定高度导致的占地与不可见问题。
        center_layout.setSizeConstraint(QLayout.SetMinimumSize)
        center_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        
        # 基础配置（可折叠）
        self.workflow_config = WorkflowConfigPanel()
        self.workflow_config.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center_layout.addWidget(self.workflow_config)

        # DAG 可视化
        self.dag_view = DAGViewPanel()
        self.dag_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center_layout.addWidget(self.dag_view)
        
        # 步骤列表
        self.step_table = StepTablePanel()
        self.step_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center_layout.addWidget(self.step_table)
        
        # 步骤详情编辑器
        self.step_editor = StepEditorPanel()
        self.step_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center_layout.addWidget(self.step_editor)

        # 吸收多余高度：避免当多个模块折叠时仍“强行填满界面”导致大片空白卡片
        center_layout.addStretch(1)
        
        center_scroll = QScrollArea()
        center_scroll.setWidgetResizable(True)
        center_scroll.setFrameShape(QFrame.NoFrame)
        center_scroll.setWidget(center_container)
        self.center_scroll = center_scroll
        self.main_splitter.addWidget(self.center_scroll)

        # ===== 右侧折叠条（24px）=====
        self.right_fold_strip = QFrame()
        self.right_fold_strip.setObjectName("FoldStrip")
        self.right_fold_strip.setFixedWidth(24)
        strip_r = QVBoxLayout(self.right_fold_strip)
        strip_r.setContentsMargins(0, 0, 0, 0)
        strip_r.setSpacing(0)
        strip_r.addSpacing(230)
        btn_r_wrap = QFrame()
        btn_r_wrap.setObjectName("FoldBtnWrap")
        btn_r_wrap.setFixedSize(20, 28)
        btn_r_layout = QHBoxLayout(btn_r_wrap)
        btn_r_layout.setContentsMargins(0, 0, 0, 0)
        btn_r_layout.setSpacing(0)
        self.btn_toggle_right_strip = QToolButton()
        self.btn_toggle_right_strip.setObjectName("FoldBtn")
        self.btn_toggle_right_strip.setAutoRaise(True)
        self.btn_toggle_right_strip.setFixedSize(20, 28)
        self.btn_toggle_right_strip.setIconSize(QSize(12, 12))
        self.btn_toggle_right_strip.setArrowType(Qt.RightArrow)
        self.btn_toggle_right_strip.clicked.connect(self._toggle_right_panel)
        btn_r_layout.addWidget(self.btn_toggle_right_strip, alignment=Qt.AlignCenter)
        strip_r.addWidget(btn_r_wrap, alignment=Qt.AlignCenter)
        strip_r.addStretch()
        self.main_splitter.addWidget(self.right_fold_strip)
        
        # ===== 右侧面板 =====
        right_panel = QFrame()
        right_panel.setObjectName("RightPanel")
        right_panel.setMaximumWidth(340)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)
        
        # 实时日志
        self.log_panel = LogPanel()
        self.log_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.log_panel.setFixedHeight(500)
        right_layout.addWidget(self.log_panel)
        
        # 运行历史
        self.run_history = RunHistoryPanel()
        right_layout.addWidget(self.run_history, stretch=1)
        
        self.main_splitter.addWidget(right_panel)
        
        # 设置分割比例
        self.main_splitter.setSizes([260, 24, 792, 24, 340])

        # 记录折叠前尺寸
        self._left_last_size = 260
        self._right_last_size = 340

    
    def _setup_toolbar(self):
        """设置工具栏"""
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.setObjectName("MainToolbar")
        toolbar.setFixedHeight(44)
        self.addToolBar(toolbar)

        # 导入/导出（按 Pencil：导入 / 导出）
        self.action_import = QAction("导入", self)
        self.action_import.triggered.connect(self._action_import_json)
        toolbar.addAction(self.action_import)
        
        self.action_export = QAction("导出", self)
        self.action_export.triggered.connect(self._action_export_json)
        toolbar.addAction(self.action_export)

        toolbar.addSeparator()

        # Webhook 管理
        self.action_webhook = QAction("Webhook 管理", self)
        self.action_webhook.triggered.connect(self._open_webhook_manager)
        toolbar.addAction(self.action_webhook)

    def _set_edit_mode(self, enabled: bool):
        enabled = bool(enabled)
        if self._edit_mode == enabled:
            return
        self._edit_mode = enabled
        self.workflow_list.set_edit_enabled(self._edit_mode)
        self.workflow_config.set_edit_enabled(self._edit_mode)
        self.step_table.set_edit_enabled(self._edit_mode)
        self.step_editor.set_edit_enabled(self._edit_mode)

        self.statusbar.showMessage("编辑模式：开启" if self._edit_mode else "编辑模式：关闭（防误操作）")
        self.btn_left_save.setEnabled(self._edit_mode)

    def _require_edit_mode(self, action_name: str) -> bool:
        if self._edit_mode:
            return True
        self.statusbar.showMessage(f"{action_name}：请先开启左侧“编辑”开关")
        QMessageBox.information(self, "需要开启编辑", f"{action_name} 前请先开启左侧“编辑”开关。")
        return False

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
    
    def _connect_signals(self):
        """连接信号"""
        # 工作流列表
        self.workflow_list.workflow_selected.connect(self._on_workflow_selected)
        self.workflow_list.workflow_deleted.connect(self._on_workflow_deleted)
        
        # 步骤表格
        self.step_table.step_selected.connect(self._on_step_selected)
        self.step_table.steps_changed.connect(self._on_steps_changed)

        # DAG 双击定位步骤
        self.dag_view.step_activated.connect(self._on_dag_step_activated)

        # 步骤编辑器
        self.step_editor.step_saved.connect(self._on_step_saved)
        self.step_editor.navigate_to_step.connect(self._on_dag_step_activated)

        # 基础配置
        self.workflow_config.workflow_updated.connect(self._on_workflow_updated)
        
        # 运行控制
        self.run_control.run_requested.connect(self._on_run_requested)
        self.run_control.watch_requested.connect(self._on_watch_requested)
        
        # 引擎
        self.engine.workflow_started.connect(self._on_workflow_started)
        self.engine.workflow_finished.connect(self._on_workflow_finished)
        self.engine.step_started.connect(self._on_step_started)
        self.engine.step_finished.connect(self._on_step_finished)
        self.engine.log_output.connect(self.log_panel.append_log)
        self.engine.progress_updated.connect(self._on_progress_updated)
        self.engine.error_details.connect(self._on_error_details)

        # 右侧日志：停止运行兜底入口
        self.log_panel.stop_clicked.connect(self._stop_workflow)
        
        # 预演按钮
        self.run_control.dry_run_clicked.connect(self._on_dry_run)

        # 运行历史：查看失败步骤
        self.run_history.open_failures_requested.connect(self._open_failures_for_history)
    
    # ===== 槽函数 =====
    
    @Slot(int)
    def _on_workflow_selected(self, workflow_id: int):
        """工作流被选中"""
        self.engine.stop_watch()
        self.run_control.set_watching(False)
        self._current_workflow_id = workflow_id
        
        # 加载基础配置
        self.workflow_config.load_workflow(workflow_id)

        # 单脚本模式
        workflow = get_workflow_by_id(workflow_id)
        single_enabled = bool(workflow.single_script_enabled) if workflow else False
        self.step_table.set_single_script_mode(single_enabled)
        self.step_editor.set_single_script_mode(single_enabled)

        parallel_enabled = bool(workflow.parallel_enabled) if workflow else False
        self.step_table.set_parallel_available(parallel_enabled)
        self.step_editor.set_parallel_available(parallel_enabled)

        # 加载步骤
        self.step_table.load_steps(workflow_id)
        
        # 更新 DAG
        self.dag_view.update_dag(workflow_id)
        
        # 加载运行历史
        self.run_history.load_history(workflow_id)

        # 更新日志上下文
        self.log_panel.set_context(workflow_id=workflow_id, step_id=None)
        
        # 清空编辑器
        self.step_editor.clear()
        
        # 更新状态栏
        if workflow:
            self.statusbar.showMessage(f"当前工作流: {workflow.name}")
        self._sync_watch_controls(workflow)
    
    @Slot(int)
    def _on_workflow_deleted(self, workflow_id: int):
        """工作流被删除"""
        if self._current_workflow_id == workflow_id:
            self._current_workflow_id = None
            self.engine.stop_watch()
            self.run_control.set_watching(False)
            self.run_control.set_watch_available(False)
            self.workflow_config.clear()
            self.step_table.clear()
            self.dag_view.clear()
            self.step_editor.clear()
            self.run_history.clear()
            self.log_panel.set_context(workflow_id=None, step_id=None)
    
    @Slot(int)
    def _on_step_selected(self, step_id: int):
        """步骤被选中"""
        self.step_editor.load_step(step_id)
        self.run_control.set_selected_step(step_id)
        self.log_panel.set_context(workflow_id=self._current_workflow_id, step_id=step_id)

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
            self.dag_view.update_dag(self._current_workflow_id)
            self.step_table.load_steps(self._current_workflow_id)
    
    @Slot()
    def _on_step_saved(self):
        """步骤保存"""
        # 刷新步骤列表和 DAG
        if self._current_workflow_id:
            self.step_table.load_steps(self._current_workflow_id)
            self.dag_view.update_dag(self._current_workflow_id)

    @Slot()
    def _on_workflow_updated(self):
        """工作流配置更新"""
        if self._current_workflow_id:
            self.workflow_list.load_workflows(selected_workflow_id=self._current_workflow_id)
            workflow = get_workflow_by_id(self._current_workflow_id)
            single_enabled = bool(workflow.single_script_enabled) if workflow else False
            self.step_table.set_single_script_mode(single_enabled)
            self.step_editor.set_single_script_mode(single_enabled)
            parallel_enabled = bool(workflow.parallel_enabled) if workflow else False
            self.step_table.set_parallel_available(parallel_enabled)
            self.step_editor.set_parallel_available(parallel_enabled)
            self.step_table.load_steps(self._current_workflow_id)
            self.engine.stop_watch()
            self.run_control.set_watching(False)
            self._sync_watch_controls(workflow)

    def _sync_watch_controls(self, workflow):
        """同步监听按钮的可用性。"""
        watch_available = False
        if workflow and workflow.watch_enabled and workflow.get_watch_folders():
            try:
                self.engine.validate_watch_folders(workflow.get_watch_folders())
                watch_available = True
            except ValueError:
                watch_available = False
        self.run_control.set_watch_available(watch_available)

    @Slot(bool)
    def _on_watch_requested(self, should_start: bool):
        """显式开始/停止监听。"""
        if not self._current_workflow_id:
            return

        workflow = get_workflow_by_id(self._current_workflow_id)
        if not workflow:
            self.run_control.set_watch_available(False)
            self.run_control.set_watching(False)
            return

        if should_start:
            started = self.engine.start_watch(workflow)
            self.run_control.set_watching(started)
            self.statusbar.showMessage(
                f"已开始监听: {workflow.name}" if started else "监听未启动，请检查监听配置"
            )
            return

        self.engine.stop_watch()
        self.run_control.set_watching(False)
        self.statusbar.showMessage(f"已停止监听: {workflow.name}")
    
    @Slot(str, object)
    def _on_run_requested(self, mode: str, param):
        """运行请求"""
        if not self._current_workflow_id:
            QMessageBox.warning(self, "警告", "请先选择一个工作流")
            return

        # 取消/停止：直接执行，不创建后台线程
        if mode == "cancel":
            self.engine.cancel()
            self.statusbar.showMessage("正在停止...")
            return
        
        # 在后台线程中运行工作流，避免 UI 阻塞
        workflow_id = self._current_workflow_id
        
        def run_in_thread():
            if mode == "full":
                self.engine.run_all(workflow_id)
            elif mode == "from_step":
                self.engine.run_from(workflow_id, param)
            elif mode == "only_step":
                self.engine.run_only(workflow_id, param)
            elif mode == "retry_failed":
                self.engine.retry_failed(workflow_id)
        
        self._run_thread = threading.Thread(target=run_in_thread, daemon=True)
        self._run_thread.start()
    
    @Slot(int, str)
    def _on_workflow_started(self, workflow_id: int, run_id: str):
        """工作流开始"""
        self.statusbar.showMessage(f"运行中... ({run_id})")

        # 运行中：启用停止入口并避免重复触发
        self.run_control.set_running(True)
        self.log_panel.set_running(True)

        # 若右侧折叠，则自动展开（确保可随时停止）
        sizes = self.main_splitter.sizes()
        if len(sizes) >= 5 and sizes[4] <= 0:
            sizes[4] = max(getattr(self, "_right_last_size", 340), 250)
            self.main_splitter.setSizes(sizes)
        # 运行中锁定右侧折叠按钮，避免误折叠导致无处停止
        self.btn_toggle_right_strip.setEnabled(False)

        # 重置 DAG 和步骤表格状态
        self.dag_view.reset_all_status()
        self.step_table.reset_all_status()
    
    @Slot(int, str, str)
    def _on_workflow_finished(self, workflow_id: int, run_id: str, status: str):
        """工作流结束"""
        # 运行结束：禁用停止入口
        self.run_control.set_running(False)
        self.log_panel.set_running(False)
        self.btn_toggle_right_strip.setEnabled(True)

        status_map = {
            "success": "完成",
            "failure": "失败",
            "cancelled": "已取消",
        }
        text = status_map.get(status, status)
        self.statusbar.showMessage(f"运行{text} ({run_id})")
        
        # 刷新运行历史
        if self._current_workflow_id == workflow_id:
            self.run_history.load_history(workflow_id)
    
    @Slot(int, str)
    def _on_step_started(self, step_id: int, step_name: str):
        """步骤开始"""
        self.step_table.highlight_step(step_id, "running")
        self.dag_view.update_step_status(step_id, "running")
    
    @Slot(int, str, bool)
    def _on_step_finished(self, step_id: int, step_name: str, success: bool):
        """步骤结束"""
        status = "success" if success else "failure"
        self.step_table.highlight_step(step_id, status)
        self.dag_view.update_step_status(step_id, status)
    
    @Slot(int, int)
    def _on_progress_updated(self, current: int, total: int):
        """进度更新"""
        self.statusbar.showMessage(f"进度: {current}/{total}")
    
    @Slot(list)
    def _on_error_details(self, error_list: list):
        """失败汇总：日志内联 + 弹窗"""
        self.log_panel.append_error_details(error_list)
        dialog = ErrorSummaryDialog(error_list, self)
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
            # 确保步骤列表在中区可见
            self.center_scroll.ensureWidgetVisible(self.step_table)
        except Exception:
            return

    def _open_step_log_for_step(self, step_id: int):
        """打开指定步骤在最新一次运行中的日志（复用 LogPanel 的上下文）"""
        if not self._current_workflow_id or not step_id:
            return
        try:
            self.log_panel.set_context(workflow_id=self._current_workflow_id, step_id=step_id)
            self.log_panel._open_step_log()
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
                QMessageBox.information(self, "提示", "该次运行没有失败步骤。")
                return
            dialog = ErrorSummaryDialog(failures, self)
            dialog.navigate_to_step.connect(self._focus_step)
            dialog.retry_failed.connect(lambda: self._on_run_requested("retry_failed", None))
            dialog.open_step_log.connect(lambda sid: self._open_step_log_for_step(sid))
            dialog.exec_()
        except Exception as e:
            QMessageBox.warning(self, "打开失败汇总失败", str(e))
    
    def _on_dry_run(self):
        """预演模式"""
        if not self._current_workflow_id:
            QMessageBox.warning(self, "警告", "请先选择一个工作流")
            return
        self.engine.dry_run(self._current_workflow_id)
    
    # ===== 工具栏操作 =====
    
    def _save_current(self):
        """保存当前"""
        self.step_editor.save_step()
        self.statusbar.showMessage("已保存")
    
    def _run_workflow(self):
        """运行工作流"""
        self._on_run_requested("full", None)
    
    def _stop_workflow(self):
        """停止工作流"""
        self.engine.cancel()
        self.statusbar.showMessage("正在停止...")
    
    def _import_json(self):
        """导入 JSON"""
        from PySide6.QtWidgets import QFileDialog
        
        file_path, _ = QFileDialog.getOpenFileName(
            self, "导入工作流 JSON",
            "", "JSON Files (*.json)"
        )
        
        if file_path:
            from pathlib import Path
            from database import import_from_json
            
            try:
                count = import_from_json(Path(file_path))
                QMessageBox.information(
                    self, "导入成功",
                    f"已导入 {count} 个工作流"
                )
                self.workflow_list.load_workflows()
            except Exception as e:
                QMessageBox.critical(self, "导入失败", str(e))
    
    def _export_json(self):
        """导出 JSON"""
        from PySide6.QtWidgets import QFileDialog
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出工作流 JSON",
            "workflows_export.json", "JSON Files (*.json)"
        )
        
        if file_path:
            from pathlib import Path
            from database import export_to_json
            
            try:
                export_to_json(Path(file_path))
                QMessageBox.information(
                    self, "导出成功",
                    f"已导出到 {file_path}"
                )
            except Exception as e:
                QMessageBox.critical(self, "导出失败", str(e))

    def _open_webhook_manager(self):
        """打开 Webhook 管理对话框"""
        dialog = WebhookManagerDialog(self)
        dialog.exec_()

    def _toggle_left_panel(self):
        """折叠/展开左侧面板"""
        sizes = self.main_splitter.sizes()
        if len(sizes) < 5:
            return
        if sizes[0] > 0:
            self._left_last_size = sizes[0]
            sizes[0] = 0
            self.btn_toggle_left_strip.setArrowType(Qt.RightArrow)
        else:
            sizes[0] = max(self._left_last_size, 200)
            self.btn_toggle_left_strip.setArrowType(Qt.LeftArrow)
        self.main_splitter.setSizes(sizes)

    def _toggle_right_panel(self):
        """折叠/展开右侧面板"""
        sizes = self.main_splitter.sizes()
        if len(sizes) < 5:
            return
        if sizes[4] > 0:
            self._right_last_size = sizes[4]
            sizes[4] = 0
            self.btn_toggle_right_strip.setArrowType(Qt.LeftArrow)
        else:
            sizes[4] = max(self._right_last_size, 250)
            self.btn_toggle_right_strip.setArrowType(Qt.RightArrow)
        self.main_splitter.setSizes(sizes)
    
    def closeEvent(self, event):
        """关闭事件"""
        if self.engine.is_running:
            reply = QMessageBox.question(
                self, "确认退出",
                "工作流正在运行，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
            
            self.engine.cancel()
        self.engine.stop_watch()
        self.run_control.set_watching(False)
        
        event.accept()
