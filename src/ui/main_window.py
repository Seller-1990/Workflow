# -*- coding: utf-8 -*-
"""主窗口"""

import logging
import threading

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QStatusBar, QToolBar, QMessageBox,
    QScrollArea, QFrame, QLabel, QPushButton, QToolButton,
    QSizePolicy, QLayout, QStyle, QApplication
)
from PySide6.QtCore import Qt, Slot, QSize, QSettings, QPoint, QTimer
from PySide6.QtGui import QAction, QIcon

logger = logging.getLogger(__name__)

from config import APP_NAME, APP_VERSION, ICON_PATH
from database import init_db, get_workflow_by_id
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
        self._edit_mode = False

        settings = QSettings(APP_NAME, "ui")  # U-P3-2: 统一 QSettings 节点
        self._dark_mode = settings.value("dark_mode", False, type=bool)
        
        self._setup_ui()
        self._setup_toolbar()
        self._setup_statusbar()
        self._connect_signals()

        self._apply_theme()

        self._set_edit_mode(False)
        
        self.workflow_list.load_workflows()
    
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
        
        # ===== 左侧面板 =====
        self.left_panel = QFrame()
        self.left_panel.setObjectName("LeftPanel")
        self.left_panel.setMinimumWidth(200)
        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        
        self.workflow_list = WorkflowListPanel()
        left_layout.addWidget(self.workflow_list, stretch=1)

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
        edit_bar_layout.addWidget(self.check_edit_mode)

        self.btn_left_save = QPushButton("保存")
        self.btn_left_save.setObjectName("primarySmall")
        self.btn_left_save.setFixedSize(78, 26)
        self.btn_left_save.clicked.connect(self._action_save)
        edit_bar_layout.addWidget(self.btn_left_save)
        left_layout.addWidget(edit_bar)
        
        self.run_control = RunControlPanel()
        left_layout.addWidget(self.run_control)
        
        self.main_splitter.addWidget(self.left_panel)

        # ===== 中区面板 =====
        self.center_container = QFrame()
        self.center_container.setObjectName("CenterPanel")
        center_layout = QVBoxLayout(self.center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(16)
        center_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.center_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        
        self.workflow_config = WorkflowConfigPanel()
        self.workflow_config.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center_layout.addWidget(self.workflow_config)

        self.dag_view = DAGViewPanel()
        self.dag_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center_layout.addWidget(self.dag_view)
        
        self.step_table = StepTablePanel()
        self.step_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center_layout.addWidget(self.step_table)
        
        self.step_editor = StepEditorPanel()
        self.step_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        center_layout.addWidget(self.step_editor)

        center_layout.addStretch(1)
        
        center_scroll = QScrollArea()
        center_scroll.setWidgetResizable(True)
        center_scroll.setFrameShape(QFrame.NoFrame)
        center_scroll.setWidget(self.center_container)
        self.center_scroll = center_scroll
        self.main_splitter.addWidget(self.center_scroll)

        # ===== 右侧面板 =====
        self.right_panel = QFrame()
        self.right_panel.setObjectName("RightPanel")
        self.right_panel.setMinimumWidth(250)
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)
        
        self.log_panel = LogPanel()
        self.log_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log_panel.setMinimumHeight(200)
        right_layout.addWidget(self.log_panel)
        
        self.run_history = RunHistoryPanel()
        right_layout.addWidget(self.run_history, stretch=1)
        
        self.main_splitter.addWidget(self.right_panel)
        
        self.main_splitter.setSizes([260, 792, 340])

        self._setup_border_fold_buttons()

        self._left_last_size = 260
        self._right_last_size = 340

        self.step_table.setAccessibleName("步骤列表")
        self.run_control.btn_run_all.setAccessibleName("全流程运行")
        self.run_control.btn_run_from.setAccessibleName("从选中步骤开始")
        self.run_control.btn_run_only.setAccessibleName("只运行选中步骤")
        self.run_control.btn_retry.setAccessibleName("重试失败步骤")
        self.run_control.btn_dry_run.setAccessibleName("工作流预演")
        self.run_control.btn_cancel.setAccessibleName("停止运行")

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
        self.addToolBar(toolbar)

        self.action_import = QAction("导入", self)
        self.action_import.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.action_import.triggered.connect(self._action_import_json)
        toolbar.addAction(self.action_import)
        
        self.action_export = QAction("导出", self)
        self.action_export.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.action_export.triggered.connect(self._action_export_json)
        toolbar.addAction(self.action_export)

        toolbar.addSeparator()

        self.action_webhook = QAction("Webhook 管理", self)
        self.action_webhook.triggered.connect(self._open_webhook_manager)
        toolbar.addAction(self.action_webhook)

        toolbar.addSeparator()

        self.action_dark_mode = QAction("切换主题", self)
        self.action_dark_mode.setCheckable(True)
        self.action_dark_mode.setChecked(self._dark_mode)
        self.action_dark_mode.triggered.connect(self._toggle_dark_mode)
        toolbar.addAction(self.action_dark_mode)

        self.action_save_shortcut = QAction("保存", self)
        self.action_save_shortcut.setShortcut("Ctrl+S")
        self.action_save_shortcut.triggered.connect(self._action_save)
        self.addAction(self.action_save_shortcut)

        self.action_run_shortcut = QAction("运行", self)
        self.action_run_shortcut.setShortcut("F5")
        self.action_run_shortcut.triggered.connect(self.run_control.btn_run_all.click)
        self.addAction(self.action_run_shortcut)

        # R3-#5: Shift+F5 停止运行（仅运行中可用；状态在 _on_workflow_started/finished 切换）
        self.action_stop_shortcut = QAction("停止运行", self)
        self.action_stop_shortcut.setShortcut("Shift+F5")
        self.action_stop_shortcut.setEnabled(False)
        self.action_stop_shortcut.triggered.connect(self._stop_workflow)
        self.addAction(self.action_stop_shortcut)

    def _toggle_dark_mode(self, checked):
        self._dark_mode = checked
        settings = QSettings(APP_NAME, "ui")  # U-P3-2: 统一 QSettings 节点
        settings.setValue("dark_mode", self._dark_mode)
        self._apply_theme()

    def _apply_theme(self):
        C = get_colors(self._dark_mode)

        app = QApplication.instance()
        if app:
            app.setStyleSheet(get_stylesheet(dark=self._dark_mode))

        self.left_panel.setStyleSheet(f"""
            QFrame#LeftPanel {{
                background-color: {C["surface_primary"]};
            }}
            QWidget#foldBar {{
                background: transparent;
            }}
        """)
        self.center_container.setStyleSheet(f"""
            QFrame#CenterPanel {{
                background-color: {C["surface_secondary"]};
            }}
        """)
        self.right_panel.setStyleSheet(f"""
            QFrame#RightPanel {{
                background-color: {C["surface_primary"]};
            }}
            QWidget#foldBar {{
                background: transparent;
            }}
        """)

        self._refresh_border_fold_buttons()

        self.workflow_list.refresh_theme(self._dark_mode)
        self.run_control.refresh_theme(self._dark_mode)
        self.log_panel.refresh_theme(self._dark_mode)
        self.run_history.refresh_theme(self._dark_mode)
        self.dag_view.refresh_theme(self._dark_mode)
        self.step_table.refresh_theme(self._dark_mode)
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
        self.step_table.steps_changed.connect(self._on_steps_changed)

        self.dag_view.step_activated.connect(self._on_dag_step_activated)

        self.step_editor.step_saved.connect(self._on_step_saved)
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

        # P-4: 异步推迟下面两个相对重的 panel；先让 UI 把已加载内容渲染出来
        QTimer.singleShot(0, lambda wid=workflow_id: self._async_load_dag(wid))
        QTimer.singleShot(0, lambda wid=workflow_id: self._async_load_history(wid))

        self.log_panel.set_context(workflow_id=workflow_id, step_id=None)

        self.step_editor.clear()

        if workflow:
            self.statusbar.showMessage(f"当前工作流: {workflow.name}", 5000)

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
        """如果 step_editor 有脏改动，弹"保存 / 不保存 / 取消"三选项。

        Returns:
            True  → 调用方可继续切换
            False → 调用方应中止切换

        R2-#2: save_step 已返回 bool。验证失败时返回 False，本函数据此重新评估。
        R2-#3: 取消路径用 blockSignals 包裹 reselect，避免再次触发 _on_workflow_selected
               造成对话框无限重弹。
        """
        try:
            if not self.step_editor.is_dirty():
                return True
        except Exception:
            return True

        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        # R3-#7 / R4-#8: 文案明确「取消」具体取消什么；标题区分工作流/步骤
        if reason == "switch_workflow":
            box.setWindowTitle("切换工作流前是否保存？")
            box.setText("当前步骤编辑器有未保存的修改。\n切换工作流前要先保存吗？")
            save_btn = box.addButton("保存并切换", QMessageBox.AcceptRole)
            discard_btn = box.addButton("不保存直接切换", QMessageBox.DestructiveRole)
            cancel_btn = box.addButton("留在当前", QMessageBox.RejectRole)
        elif reason == "switch_step":
            box.setWindowTitle("切换步骤前是否保存？")
            box.setText("当前步骤编辑器有未保存的修改。\n切换步骤前要先保存吗？")
            save_btn = box.addButton("保存并切换", QMessageBox.AcceptRole)
            discard_btn = box.addButton("不保存直接切换", QMessageBox.DestructiveRole)
            cancel_btn = box.addButton("留在当前", QMessageBox.RejectRole)
        else:
            box.setWindowTitle("未保存的修改")
            box.setText("步骤编辑器有未保存的修改。是否保存？")
            save_btn = box.addButton("保存", QMessageBox.AcceptRole)
            discard_btn = box.addButton("不保存", QMessageBox.DestructiveRole)
            cancel_btn = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(save_btn)
        # Qt 同步对话框：阻塞直到用户做出选择
        box.exec_()
        clicked = box.clickedButton()
        if clicked is save_btn:
            try:
                ok = bool(self.step_editor.save_step())
            except Exception as e:
                logger.warning("自动保存步骤失败: %s", e)
                ok = False
            # R2-#2: save_step 失败时不允许切换；保留编辑器内容，留住 dirty 状态
            if not ok or self.step_editor.is_dirty():
                self._restore_selection_silently(reason)
                return False
            return True
        if clicked is discard_btn:
            # 用户主动放弃改动：复位脏标记
            try:
                self.step_editor._is_dirty = False
            except Exception:
                pass
            return True
        # 取消：恢复 UI 上的选中状态到旧值
        self._restore_selection_silently(reason)
        return False

    def _restore_selection_silently(self, reason: str) -> None:
        """R2-#3 / R4-#7: 静默回滚 UI 选中状态，避免引发新一轮选中信号。

        支持 reason: switch_workflow / switch_step
        """
        if reason == "switch_workflow":
            self._restore_workflow_selection_silently()
        elif reason == "switch_step":
            self._restore_step_selection_silently()

    def _restore_step_selection_silently(self) -> None:
        """R4-#7: switch_step 取消路径——把 step_table 行选回当前编辑器的 step_id。"""
        try:
            target_step_id = getattr(self.step_editor, "_step_id", None) or getattr(
                self.step_editor, "current_step_id", None
            )
            if not target_step_id:
                return
            tbl = getattr(self.step_table, "table", None)
            if tbl is None:
                return
            blocker_active = tbl.signalsBlocked()
            tbl.blockSignals(True)
            try:
                row_map = getattr(self.step_table, "_row_by_step_id", {}) or {}
                row = row_map.get(int(target_step_id))
                if row is not None and 0 <= row < tbl.rowCount():
                    tbl.setCurrentCell(row, 0)
            finally:
                tbl.blockSignals(blocker_active)
        except Exception as e:
            logger.warning("回滚步骤选中失败: %s", e)

    def _restore_workflow_selection_silently(self) -> None:
        """R2-#3 / R3-#1 / R4-#7: switch_workflow 取消路径的原逻辑提取。"""
        if self._current_workflow_id is None:
            return
        try:
            # 直接定位 QListWidget 并 blockSignals
            lw = getattr(self.workflow_list, "list_widget", None)
            if lw is None:
                return
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
                # 清空选中并把 _current_workflow_id 置 None，避免 UI 与状态错位
                if not matched:
                    lw.setCurrentRow(-1)
                    self._current_workflow_id = None
            finally:
                lw.blockSignals(blocker_active)
        except Exception as e:
            logger.warning("回滚选中失败: %s", e)

    def _sync_engine_watch(self, workflow) -> None:
        """根据 workflow.watch_enabled 启停 engine 监听。

        engine.start_watch 内部已经做：先 stop_watch，再按 watch_enabled / 目录有效性决定启停。
        这里只负责拉一次起、并把结果反馈到状态栏。
        """
        if workflow is None:
            try:
                self.engine.stop_watch()
            except Exception as e:
                logger.warning("停止监听失败: %s", e)
            return
        try:
            started = self.engine.start_watch(workflow)
        except Exception as e:
            logger.warning("启动监听失败: %s", e)
            self.statusbar.showMessage(f"监听启动失败: {e}", 3000)
            return
        if started:
            folders = workflow.get_watch_folders() or []
            self.statusbar.showMessage(f"已开始监听 {len(folders)} 个目录", 3000)
        elif workflow.watch_enabled:
            # watch_enabled=True 但 start_watch 返回 False：目录无效 / 校验失败
            self.statusbar.showMessage("监听未启动（目录无效或为空）", 4000)

    @Slot(int, list)
    def _on_watch_started(self, workflow_id: int, folders: list) -> None:
        """R2-#4: 监听启动 → 更新持久指示器"""
        try:
            count = len(folders or [])
            self._watch_indicator.setText(f"▶ 监听中 ({count})")
            self._refresh_watch_indicator_theme(running=True)
            self._watch_indicator.setToolTip("\n".join(folders or []) or "文件监听状态")
        except Exception as e:
            logger.warning("更新监听指示器失败: %s", e)

    @Slot(int)
    def _on_watch_stopped(self, workflow_id: int) -> None:
        """R2-#4: 监听停止 → 灰色指示器"""
        try:
            self._watch_indicator.setText("⏸ 未监听")
            self._refresh_watch_indicator_theme(running=False)
            self._watch_indicator.setToolTip("文件监听状态")
        except Exception as e:
            logger.warning("更新监听指示器失败: %s", e)

    def _refresh_watch_indicator_theme(self, running: bool) -> None:
        """R3-#6 / R4-#8: 按主题与运行态计算指示器颜色，保证 WCAG AA 对比度"""
        try:
            if running:
                # R4-#8: 浅主题用深一档绿（#248A3D ≈ 4.7:1）、暗主题保持 #34C759
                color = "#248A3D" if not getattr(self, "_dark_mode", False) else "#34C759"
            else:
                # 暗色主题下 #8E8E93 对比 ~3.0:1 不达 AA；改用 #AEAEB2 (~5.4:1)
                color = "#AEAEB2" if getattr(self, "_dark_mode", False) else "#6E6E73"
            self._watch_indicator.setStyleSheet(f"color: {color}; padding: 0 8px;")
        except Exception:
            pass

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
        # R6-#4: 兜底——若 engine.is_running 已为 False 但 _running_workflow_id 还非空
        # （理论上 finished 信号一定会清；这里防御未来 signal_policy 不对称导致永久卡住）
        if running_id is not None and not getattr(self.engine, "is_running", False):
            self._running_workflow_id = None
            self._running_workflow_name = None
            self._stopping_in_progress = False
            running_id = None
        lock_panels = running_id is not None and running_id == current_id
        try:
            self.workflow_config.setEnabled(not lock_panels)
            self.step_table.setEnabled(not lock_panels)
            self.step_editor.setEnabled(not lock_panels)
        except Exception:
            pass
        # R6-#1: 后台运行（运行中但用户切走了）→ 持久指示器；同步可见性
        # R6-#3: stop 请求已发出但 finished 信号未到的窗口，暂不显示"后台运行"标签
        try:
            stopping = getattr(self, "_stopping_in_progress", False)
            if running_id is not None and running_id != current_id and not stopping:
                name = getattr(self, "_running_workflow_name", None) or f"#{running_id}"
                self._bg_running_label.setText(f"↻ 后台运行：{name}")
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
        if self._current_workflow_id == workflow_id:
            self._current_workflow_id = None
            self.workflow_config.clear()
            self.step_table.clear()
            self.dag_view.clear()
            self.step_editor.clear()
            self.run_history.clear()
            self.log_panel.set_context(workflow_id=None, step_id=None)
    
    @Slot(int)
    def _on_step_selected(self, step_id: int):
        """步骤被选中"""
        # #5: 切换步骤前，如编辑器有未保存改动，弹三选项确认
        if not self._confirm_discard_unsaved(reason="switch_step", new_target=step_id):
            return
        self.step_editor.load_step(step_id)
        stage_uid = None
        if step_id:
            # R3-#10: 优先用 step_table 已缓存的 row_meta；缺失再回退 DB（兼容旧入口）
            stage_uid = self.step_table.get_stage_uid_for_step(step_id)
            if stage_uid is None:
                try:
                    from database import get_step_by_id
                    step = get_step_by_id(step_id)
                    if step:
                        stage_uid = step.stage_uid
                except Exception as e:
                    logger.warning("回退查询 step.stage_uid 失败: %s", e)
        self.run_control.set_selected_step(step_id, stage_uid)
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
        if self._current_workflow_id:
            # R3-#9: 把较重的 DAG 重建推到下一轮事件循环，避免与 step_table 同步抢主线程
            wid = self._current_workflow_id
            self.step_table.load_steps(wid)
            QTimer.singleShot(0, lambda w=wid: self._async_load_dag(w))

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
            # R3-#9 / #15: 把较重的 DAG / history 异步刷新，避免一次性触发 4-5 个 DB 查询阻塞主线程
            QTimer.singleShot(0, lambda w=wid: self._async_load_dag(w))
            QTimer.singleShot(0, lambda w=wid: self._async_load_history(w))
            # #1: 配置变更后重启监听以应用新的 watch_enabled / 目录 / 模式
            self._sync_engine_watch(workflow)

    @Slot(bool)
    def _on_run_requested(self, mode: str, param):
        """运行请求"""
        if not self._current_workflow_id:
            msg_warning(self, self._dark_mode, "警告", "请先选择一个工作流")
            return

        if mode == "cancel":
            self.engine.cancel()
            self.statusbar.showMessage("正在停止...")
            return

        # R6-#2 / R7-#1: 主线程预检——已有运行时给三按钮弹窗（停止/切回/取消），
        # 而不是单纯告知（避免用户被迫手工编排）
        if getattr(self.engine, "is_running", False):
            running_id = getattr(self, "_running_workflow_id", None)
            running_name = getattr(self, "_running_workflow_name", None) or (
                f"#{running_id}" if running_id is not None else "(未知)"
            )
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("已有运行中")
            box.setText(
                f"工作流「{running_name}」正在运行中。\n请选择一项操作："
            )
            stop_run_new_btn = box.addButton(
                "停止当前并运行新的", QMessageBox.DestructiveRole
            )
            goto_running_btn = box.addButton("切回当前运行", QMessageBox.AcceptRole)
            cancel_btn = box.addButton("取消", QMessageBox.RejectRole)
            box.setDefaultButton(cancel_btn)
            box.exec_()
            clicked = box.clickedButton()
            if clicked is cancel_btn:
                return
            if clicked is goto_running_btn:
                # 复用切回逻辑
                self._on_bg_running_label_clicked(None)
                return
            # stop_run_new_btn：先取消，等 finished 信号到再触发新运行
            try:
                self.engine.cancel()
                self.statusbar.showMessage("已请求停止当前运行，等待后再启动新运行...", 5000)
            except Exception as e:
                logger.warning("请求停止失败: %s", e)

            target_workflow_id = self._current_workflow_id
            target_mode = mode
            target_param = param

            # R8-#1: 多次点「停止并运行新的」时不再累积回调——
            # 新建前先断开旧的（_pending_retry_cb 持有上次的闭包引用）
            prev_cb = getattr(self, "_pending_retry_cb", None)
            if prev_cb is not None:
                try:
                    self.engine.workflow_finished.disconnect(prev_cb)
                except Exception:
                    pass
                self._pending_retry_cb = None

            def _retry_after_stop(_wid, _run_id, _status):
                try:
                    self.engine.workflow_finished.disconnect(_retry_after_stop)
                except Exception:
                    pass
                self._pending_retry_cb = None
                # 异步重新触发请求，让 Qt 完整跑完 finished 逻辑
                from PySide6.QtCore import QTimer as _QTimer
                if self._current_workflow_id == target_workflow_id:
                    _QTimer.singleShot(
                        50,
                        lambda: self._on_run_requested(target_mode, target_param),
                    )
                else:
                    # R8-#3: 用户在等待期间切了工作流——放弃重试，但显式告知
                    self.statusbar.showMessage(
                        "已取消待执行的新运行（工作流已切换）", 4000
                    )

            try:
                self.engine.workflow_finished.connect(_retry_after_stop)
                self._pending_retry_cb = _retry_after_stop
            except Exception as e:
                logger.warning("连接 finished 信号失败: %s", e)
            return
        
        workflow_id = self._current_workflow_id
        
        def run_in_thread():
            try:
                if mode == "full":
                    result = self.engine.run_all(workflow_id)
                elif mode == "from_step":
                    result = self.engine.run_from(workflow_id, param)
                elif mode == "only_step":
                    result = self.engine.run_only(workflow_id, param)
                elif mode == "only_stage":
                    result = self.engine.run_stage(workflow_id, param)
                elif mode == "from_stage":
                    result = self.engine.run_from_stage(workflow_id, param)
                elif mode == "retry_failed":
                    result = self.engine.retry_failed(workflow_id)
                else:
                    result = False
            except Exception as e:
                from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(
                    self.engine, "_emit_log",
                    Qt.QueuedConnection,
                    Q_ARG(str, f"运行异常: {e}")
                )
        
        self._run_thread = threading.Thread(target=run_in_thread, daemon=True)
        self._run_thread.start()
    
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
            sizes[2] = max(getattr(self, "_right_last_size", 340), 250)
            self.main_splitter.setSizes(sizes)
        self.btn_toggle_right.setEnabled(False)

        self.dag_view.reset_all_status()
        self.step_table.reset_all_status()

    @Slot(int, str, str)
    def _on_workflow_finished(self, workflow_id: int, run_id: str, status: str):
        """工作流结束"""
        # R5-#1 / R6-#1 / R6-#3: 清理 running_workflow_id + 缓存名字 + stopping 标记
        self._running_workflow_id = None
        self._running_workflow_name = None
        self._stopping_in_progress = False
        self.run_control.set_running(False)
        self.log_panel.set_running(False)
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
    
    @Slot(int, str, str, object)
    def _on_step_finished(self, step_id: int, step_name: str, status: str, duration_seconds=None):
        """步骤结束"""
        self.step_table.highlight_step(step_id, status)
        self.dag_view.update_step_status(step_id, status, duration_seconds)
    
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
        """停止工作流"""
        self.engine.cancel()
        self.statusbar.showMessage("正在停止...")

    @Slot()
    def _on_statusbar_stop_clicked(self):
        """R5-#5: 状态栏停止按钮过渡态——点击后立即禁用并改文案，与 run_control 一致"""
        try:
            self._statusbar_stop_btn.setEnabled(False)
            self._statusbar_stop_btn.setText("⏹ 正在停止...")
        except Exception:
            pass
        self._stop_workflow()
    
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
                msg_information(
                    self, self._dark_mode, "导入成功",
                    f"已导入 {count} 个工作流"
                )
                self.workflow_list.load_workflows()
            except Exception as e:
                msg_critical(self, self._dark_mode, "导入失败", str(e))
    
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
                msg_information(
                    self, self._dark_mode, "导出成功",
                    f"已导出到 {file_path}"
                )
            except Exception as e:
                msg_critical(self, self._dark_mode, "导出失败", str(e))

    def _open_webhook_manager(self):
        """打开 Webhook 管理对话框"""
        dialog = WebhookManagerDialog(self)
        dialog.exec_()

    def _toggle_left_panel(self):
        """折叠/展开左侧面板"""
        if self.left_panel.isVisible():
            self._left_last_size = self.left_panel.width()
            self.left_panel.setVisible(False)
            self.btn_toggle_left.setText("▶")
        else:
            self.left_panel.setVisible(True)
            self.left_panel.setMinimumWidth(200)
            sizes = self.main_splitter.sizes()
            if len(sizes) >= 3:
                sizes[0] = max(self._left_last_size, 200)
                self.main_splitter.setSizes(sizes)
            self.btn_toggle_left.setText("◀")
        QTimer.singleShot(50, self._update_border_widget_positions)

    def _toggle_right_panel(self):
        """折叠/展开右侧面板"""
        if self.right_panel.isVisible():
            self._right_last_size = self.right_panel.width()
            self.right_panel.setVisible(False)
            self.btn_toggle_right.setText("◀")
        else:
            self.right_panel.setVisible(True)
            self.right_panel.setMinimumWidth(250)
            sizes = self.main_splitter.sizes()
            if len(sizes) >= 2:
                sizes[-1] = max(self._right_last_size, 250)
                self.main_splitter.setSizes(sizes)
            self.btn_toggle_right.setText("▶")
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
        if not self._confirm_discard_unsaved(reason="close", new_target=None):
            event.ignore()
            return
        if self.engine.is_running:
            reply = msg_question(
                self, self._dark_mode, "确认退出",
                "工作流正在运行，确定要退出吗？",
            )
            if reply == QMessageBox.No:
                event.ignore()
                return
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
