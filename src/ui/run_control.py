# -*- coding: utf-8 -*-
"""运行控制面板"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QGroupBox, QComboBox,
    QLabel, QHBoxLayout
)
from PySide6.QtCore import Signal


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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_step_id = None
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 分组框
        group = QGroupBox("运行控制")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(12, 18, 12, 12)
        group_layout.setSpacing(10)
        
        # 全流程运行
        self.btn_run_all = QPushButton("全流程运行")
        self.btn_run_all.setObjectName("primary")
        self.btn_run_all.clicked.connect(self._run_all)
        group_layout.addWidget(self.btn_run_all)
        
        # 分隔线
        group_layout.addSpacing(10)
        
        # 从指定步骤开始
        self.btn_run_from = QPushButton("从选中步骤开始")
        self.btn_run_from.clicked.connect(self._run_from)
        group_layout.addWidget(self.btn_run_from)
        
        # 只运行指定步骤
        self.btn_run_only = QPushButton("只运行选中步骤")
        self.btn_run_only.clicked.connect(self._run_only)
        group_layout.addWidget(self.btn_run_only)
        
        # 重试失败步骤
        self.btn_retry = QPushButton("重试失败步骤")
        self.btn_retry.clicked.connect(self._retry_failed)
        group_layout.addWidget(self.btn_retry)
        
        layout.addWidget(group)
    
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
