# -*- coding: utf-8 -*-
"""实时日志面板"""

import os
import subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QPushButton,
    QHBoxLayout, QGroupBox
)
from PySide6.QtCore import Slot
from PySide6.QtGui import QTextCursor, QFont

from database import get_latest_run_history, get_step_logs_by_run


class LogPanel(QWidget):
    """实时日志面板"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflow_id = None
        self._step_id = None
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 分组框
        group = QGroupBox("实时日志")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(12, 18, 12, 12)
        group_layout.setSpacing(10)
        
        # 工具栏
        toolbar = QHBoxLayout()
        
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setFixedWidth(60)
        self.btn_clear.clicked.connect(self.clear)
        toolbar.addWidget(self.btn_clear)
        
        self.btn_copy = QPushButton("复制")
        self.btn_copy.setFixedWidth(60)
        self.btn_copy.clicked.connect(self._copy_log)
        toolbar.addWidget(self.btn_copy)

        self.btn_open_step_log = QPushButton("打开步骤日志")
        self.btn_open_step_log.setFixedWidth(90)
        self.btn_open_step_log.clicked.connect(self._open_step_log)
        toolbar.addWidget(self.btn_open_step_log)
        
        toolbar.addStretch()
        
        group_layout.addLayout(toolbar)
        
        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                color: #111111;
                border: 1px solid #E6E6E6;
            }
        """)
        group_layout.addWidget(self.log_text)
        
        layout.addWidget(group)
    
    @Slot(str)
    def append_log(self, message: str):
        """追加日志"""
        self.log_text.append(message)
        # 滚动到底部
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)
    
    def clear(self):
        """清空日志"""
        self.log_text.clear()
    
    def _copy_log(self):
        """复制日志到剪贴板"""
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.log_text.toPlainText())

    def set_context(self, workflow_id: int = None, step_id: int = None):
        """设置当前上下文"""
        self._workflow_id = workflow_id
        self._step_id = step_id

    def _open_step_log(self):
        """打开选中步骤日志"""
        if not self._workflow_id or not self._step_id:
            return
        latest = get_latest_run_history(self._workflow_id)
        if not latest:
            return
        step_logs = get_step_logs_by_run(latest.id)
        target = None
        for log in step_logs:
            if log.step_id == self._step_id:
                target = log
                break
        if not target:
            return
        # 优先打开 stdout
        for path in [target.stdout_path, target.stderr_path]:
            if path and os.path.exists(path):
                subprocess.run(["notepad", path])
                return
