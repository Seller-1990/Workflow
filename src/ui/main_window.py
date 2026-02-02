# -*- coding: utf-8 -*-
"""主窗口"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStatusBar, QToolBar, QMessageBox,
    QScrollArea, QFrame, QCheckBox, QLabel
)
from PySide6.QtCore import Qt, Slot, QThread
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
        
        # 主分割器（左-中-右）
        self.main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.main_splitter)
        
        # ===== 左侧面板 =====
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(12)
        
        # 工作流列表
        self.workflow_list = WorkflowListPanel()
        left_layout.addWidget(self.workflow_list, stretch=1)

        # 编辑开关（防误操作）
        edit_bar = QWidget()
        edit_bar_layout = QHBoxLayout(edit_bar)
        edit_bar_layout.setContentsMargins(0, 0, 0, 0)
        edit_bar_layout.setSpacing(8)
        edit_bar_layout.addWidget(QLabel("编辑"))
        self.check_edit_mode = QCheckBox("开启")
        self.check_edit_mode.setObjectName("toggle")
        self.check_edit_mode.setChecked(False)
        self.check_edit_mode.toggled.connect(self._set_edit_mode)
        edit_bar_layout.addStretch()
        edit_bar_layout.addWidget(self.check_edit_mode)
        left_layout.addWidget(edit_bar)
        
        # 运行控制
        self.run_control = RunControlPanel()
        left_layout.addWidget(self.run_control)
        
        self.main_splitter.addWidget(left_panel)
        
        # ===== 中区面板 =====
        center_container = QWidget()
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(16, 16, 16, 16)
        center_layout.setSpacing(12)
        
        # 基础配置（可折叠）
        self.workflow_config = WorkflowConfigPanel()
        center_layout.addWidget(self.workflow_config)

        # DAG 可视化
        self.dag_view = DAGViewPanel()
        center_layout.addWidget(self.dag_view)
        
        # 步骤列表
        self.step_table = StepTablePanel()
        center_layout.addWidget(self.step_table, stretch=1)
        
        # 步骤详情编辑器
        self.step_editor = StepEditorPanel()
        center_layout.addWidget(self.step_editor)
        
        center_scroll = QScrollArea()
        center_scroll.setWidgetResizable(True)
        center_scroll.setFrameShape(QFrame.NoFrame)
        center_scroll.setWidget(center_container)
        self.center_scroll = center_scroll
        self.main_splitter.addWidget(self.center_scroll)
        
        # ===== 右侧面板 =====
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)
        
        # 实时日志
        self.log_panel = LogPanel()
        right_layout.addWidget(self.log_panel, stretch=1)
        
        # 运行历史
        self.run_history = RunHistoryPanel()
        right_layout.addWidget(self.run_history)
        
        self.main_splitter.addWidget(right_panel)
        
        # 设置分割比例
        self.main_splitter.setSizes([250, 600, 350])

        # 记录折叠前尺寸
        self._left_last_size = 250
        self._right_last_size = 350

    
    def _setup_toolbar(self):
        """设置工具栏"""
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # 新建工作流
        self.action_new = QAction("新建工作流", self)
        self.action_new.setShortcut("Ctrl+N")
        self.action_new.triggered.connect(self._action_new_workflow)
        toolbar.addAction(self.action_new)
        
        # 保存
        self.action_save = QAction("保存", self)
        self.action_save.setShortcut("Ctrl+S")
        self.action_save.triggered.connect(self._action_save)
        toolbar.addAction(self.action_save)
        
        toolbar.addSeparator()
        
        # 运行
        self.action_run = QAction("运行", self)
        self.action_run.setShortcut("F5")
        self.action_run.triggered.connect(self._run_workflow)
        toolbar.addAction(self.action_run)
        
        # 停止
        self.action_stop = QAction("停止", self)
        self.action_stop.setShortcut("Shift+F5")
        self.action_stop.triggered.connect(self._stop_workflow)
        self.action_stop.setEnabled(False)
        toolbar.addAction(self.action_stop)
        
        toolbar.addSeparator()
        
        # 导入
        self.action_import = QAction("导入 JSON", self)
        self.action_import.triggered.connect(self._action_import_json)
        toolbar.addAction(self.action_import)
        
        # 导出
        self.action_export = QAction("导出 JSON", self)
        self.action_export.triggered.connect(self._action_export_json)
        toolbar.addAction(self.action_export)

        toolbar.addSeparator()

        # 左右面板折叠
        self.action_toggle_left = QAction("折叠左侧", self)
        self.action_toggle_left.triggered.connect(self._toggle_left_panel)
        toolbar.addAction(self.action_toggle_left)

        self.action_toggle_right = QAction("折叠右侧", self)
        self.action_toggle_right.triggered.connect(self._toggle_right_panel)
        toolbar.addAction(self.action_toggle_right)

        toolbar.addSeparator()

        # Webhook 管理
        self.action_webhook = QAction("🔔 Webhook 管理", self)
        self.action_webhook.triggered.connect(self._open_webhook_manager)
        toolbar.addAction(self.action_webhook)

    def _set_edit_mode(self, enabled: bool):
        self._edit_mode = bool(enabled)
        self.workflow_list.set_edit_enabled(self._edit_mode)
        self.workflow_config.set_edit_enabled(self._edit_mode)
        self.step_table.set_edit_enabled(self._edit_mode)
        self.step_editor.set_edit_enabled(self._edit_mode)

        self.statusbar.showMessage("编辑模式：开启" if self._edit_mode else "编辑模式：关闭（防误操作）")
        self.check_edit_mode.setText("开启" if self._edit_mode else "关闭")

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
        self.statusbar.showMessage("就绪")
    
    def _connect_signals(self):
        """连接信号"""
        # 工作流列表
        self.workflow_list.workflow_selected.connect(self._on_workflow_selected)
        self.workflow_list.workflow_deleted.connect(self._on_workflow_deleted)
        
        # 步骤表格
        self.step_table.step_selected.connect(self._on_step_selected)
        self.step_table.steps_changed.connect(self._on_steps_changed)

        # 步骤编辑器
        self.step_editor.step_saved.connect(self._on_step_saved)

        # 基础配置
        self.workflow_config.workflow_updated.connect(self._on_workflow_updated)
        
        # 运行控制
        self.run_control.run_requested.connect(self._on_run_requested)
        
        # 引擎
        self.engine.workflow_started.connect(self._on_workflow_started)
        self.engine.workflow_finished.connect(self._on_workflow_finished)
        self.engine.step_started.connect(self._on_step_started)
        self.engine.step_finished.connect(self._on_step_finished)
        self.engine.log_output.connect(self.log_panel.append_log)
        self.engine.progress_updated.connect(self._on_progress_updated)
    
    # ===== 槽函数 =====
    
    @Slot(int)
    def _on_workflow_selected(self, workflow_id: int):
        """工作流被选中"""
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
            self.engine.start_watch(workflow)
    
    @Slot(int)
    def _on_workflow_deleted(self, workflow_id: int):
        """工作流被删除"""
        if self._current_workflow_id == workflow_id:
            self._current_workflow_id = None
            self.engine.stop_watch()
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
            self.workflow_list.load_workflows()
            workflow = get_workflow_by_id(self._current_workflow_id)
            single_enabled = bool(workflow.single_script_enabled) if workflow else False
            self.step_table.set_single_script_mode(single_enabled)
            self.step_editor.set_single_script_mode(single_enabled)
            parallel_enabled = bool(workflow.parallel_enabled) if workflow else False
            self.step_table.set_parallel_available(parallel_enabled)
            self.step_editor.set_parallel_available(parallel_enabled)
            self.step_table.load_steps(self._current_workflow_id)
            if workflow:
                self.engine.start_watch(workflow)
    
    @Slot(str, object)
    def _on_run_requested(self, mode: str, param):
        """运行请求"""
        if not self._current_workflow_id:
            QMessageBox.warning(self, "警告", "请先选择一个工作流")
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
        
        self._run_thread = QThread()
        self._run_thread.run = run_in_thread
        self._run_thread.start()
    
    @Slot(int, str)
    def _on_workflow_started(self, workflow_id: int, run_id: str):
        """工作流开始"""
        self.action_run.setEnabled(False)
        self.action_stop.setEnabled(True)
        self.statusbar.showMessage(f"运行中... ({run_id})")
        # 重置 DAG 所有节点状态
        self.dag_view.reset_all_status()
    
    @Slot(int, str, bool)
    def _on_workflow_finished(self, workflow_id: int, run_id: str, success: bool):
        """工作流结束"""
        self.action_run.setEnabled(True)
        self.action_stop.setEnabled(False)
        
        status = "完成" if success else "失败"
        self.statusbar.showMessage(f"运行{status} ({run_id})")
        
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
        if sizes[0] > 0:
            self._left_last_size = sizes[0]
            sizes[0] = 0
            self.action_toggle_left.setText("展开左侧")
        else:
            sizes[0] = max(self._left_last_size, 200)
            self.action_toggle_left.setText("折叠左侧")
        self.main_splitter.setSizes(sizes)

    def _toggle_right_panel(self):
        """折叠/展开右侧面板"""
        sizes = self.main_splitter.sizes()
        if sizes[2] > 0:
            self._right_last_size = sizes[2]
            sizes[2] = 0
            self.action_toggle_right.setText("展开右侧")
        else:
            sizes[2] = max(self._right_last_size, 250)
            self.action_toggle_right.setText("折叠右侧")
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
        
        event.accept()
