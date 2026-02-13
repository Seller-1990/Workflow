# -*- coding: utf-8 -*-
"""运行控制面板"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont


class RunControlPanel(QWidget):
    """运行控制面板
    
    四种运行模式：
    1. 全流程运行
    2. 从指定步骤开始
    3. 只运行指定步骤
    4. 重试失败步骤
    """
    
    # 信号
    run_requested = Signal(str, object)  # mode, param
    dry_run_clicked = Signal()  # 预演模式
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_step_id = None
        self._is_running = False
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)

        header = QLabel("运行控制")
        f = QFont(header.font())
        f.setPointSize(15)
        f.setWeight(QFont.Weight.Bold)
        header.setFont(f)
        layout.addWidget(header)

        # 全流程运行（Primary）
        self.btn_run_all = QPushButton("▶  全流程运行")
        self.btn_run_all.setObjectName("runPrimary")
        self.btn_run_all.setFixedHeight(30)
        self.btn_run_all.clicked.connect(self._run_all)
        layout.addWidget(self.btn_run_all)

        ghost = QWidget()
        ghost_layout = QVBoxLayout(ghost)
        ghost_layout.setContentsMargins(0, 0, 0, 0)
        ghost_layout.setSpacing(2)

        # Ghost buttons（按 Pencil：透明 + 蓝字，圆角 10，高 30，gap 2）
        self.btn_run_from = QPushButton("从选中步骤开始")
        self.btn_run_from.setObjectName("runGhost")
        self.btn_run_from.setFixedHeight(30)
        self.btn_run_from.clicked.connect(self._run_from)
        ghost_layout.addWidget(self.btn_run_from)
        
        self.btn_run_only = QPushButton("只运行选中步骤")
        self.btn_run_only.setObjectName("runGhost")
        self.btn_run_only.setFixedHeight(30)
        self.btn_run_only.clicked.connect(self._run_only)
        ghost_layout.addWidget(self.btn_run_only)
        
        self.btn_retry = QPushButton("重试失败步骤")
        self.btn_retry.setObjectName("runGhost")
        self.btn_retry.setFixedHeight(30)
        self.btn_retry.clicked.connect(self._retry_failed)
        ghost_layout.addWidget(self.btn_retry)
        
        # 预演（默认可用，但视觉为“次要”）
        self.btn_dry_run = QPushButton("工作流预演")
        self.btn_dry_run.setObjectName("runGhostMuted")
        self.btn_dry_run.setFixedHeight(30)
        self.btn_dry_run.setToolTip("预览执行计划，不实际执行")
        self.btn_dry_run.clicked.connect(self.dry_run_clicked.emit)
        ghost_layout.addWidget(self.btn_dry_run)

        # 停止运行（运行中启用）
        self.btn_cancel = QPushButton("停止运行")
        self.btn_cancel.setObjectName("runGhostDisabled")
        self.btn_cancel.setFixedHeight(30)
        self.btn_cancel.setToolTip("停止当前运行")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(lambda: self.run_requested.emit("cancel", None))
        ghost_layout.addWidget(self.btn_cancel)

        layout.addWidget(ghost)

    def set_running(self, running: bool):
        """设置运行状态（用于启用/禁用停止入口与避免重复触发运行）"""
        self._is_running = bool(running)
        self.btn_cancel.setEnabled(self._is_running)
        # 运行中禁止再次触发运行/预演，避免用户误操作产生“已有工作流正在运行”的错误日志
        can_run = not self._is_running
        self.btn_run_all.setEnabled(can_run)
        self.btn_run_from.setEnabled(can_run)
        self.btn_run_only.setEnabled(can_run)
        self.btn_retry.setEnabled(can_run)
        self.btn_dry_run.setEnabled(can_run)
    
    def set_selected_step(self, step_id: int):
        """设置选中的步骤"""
        self._selected_step_id = step_id
    
    def _run_all(self):
        """全流程运行"""
        self.run_requested.emit("full", None)
    
    def _run_from(self):
        """从指定步骤开始"""
        if self._selected_step_id:
            self.run_requested.emit("from_step", self._selected_step_id)
    
    def _run_only(self):
        """只运行指定步骤"""
        if self._selected_step_id:
            self.run_requested.emit("only_step", self._selected_step_id)
    
    def _retry_failed(self):
        """重试失败步骤"""
        self.run_requested.emit("retry_failed", None)
