# -*- coding: utf-8 -*-
"""实时日志面板"""

import os
import subprocess

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QPushButton,
    QHBoxLayout, QToolButton, QStyle
)
from PySide6.QtCore import Slot, Signal, QSize
from PySide6.QtGui import QTextCursor, QFont

from database import get_latest_run_history, get_step_logs_by_run
from ui.collapsible_section import CollapsibleSection
from ui.theme import COLORS, CORNER_RADIUS


class LogPanel(QWidget):
    """实时日志面板"""

    stop_clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflow_id = None
        self._step_id = None
        self._is_running = False
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题与折叠按钮同一行（与全局卡片一致）
        self.section = CollapsibleSection("实时日志", collapsed=False, header_height=44, title_font_size=15, title_weight=700)
        group_layout = self.section.body_layout

        # Header actions（按 Pencil：蓝色文本操作；停止为兜底图标按钮）
        self.btn_clear = QPushButton("清空")
        self.btn_clear.setObjectName("headerLink")
        self.btn_clear.setFixedHeight(24)
        self.btn_clear.clicked.connect(self.clear)
        self.section.header_actions_layout.addWidget(self.btn_clear)

        self.btn_copy = QPushButton("复制")
        self.btn_copy.setObjectName("headerLink")
        self.btn_copy.setFixedHeight(24)
        self.btn_copy.clicked.connect(self._copy_log)
        self.section.header_actions_layout.addWidget(self.btn_copy)

        self.btn_open_step_log = QPushButton("打开步骤日志")
        self.btn_open_step_log.setObjectName("headerLink")
        self.btn_open_step_log.setFixedHeight(24)
        self.btn_open_step_log.clicked.connect(self._open_step_log)
        self.section.header_actions_layout.addWidget(self.btn_open_step_log)

        # 停止运行（兜底入口，避免左侧折叠后无处停止）
        self.btn_stop = QToolButton()
        self.btn_stop.setAutoRaise(True)
        icon = self.style().standardIcon(getattr(QStyle, "SP_BrowserStop", QStyle.SP_DialogCloseButton))
        self.btn_stop.setIcon(icon)
        self.btn_stop.setIconSize(QSize(16, 16))
        self.btn_stop.setFixedSize(32, 32)
        self.btn_stop.setToolTip("停止运行")
        self.btn_stop.setAccessibleName("停止运行")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.section.header_actions_layout.addWidget(self.btn_stop)
        
        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['background']};
                color: {COLORS['text_primary']};
                border: none;
                border-radius: 12px;
                padding: 12px;
            }}
        """)
        group_layout.addWidget(self.log_text)
        
        layout.addWidget(self.section)

    def set_running(self, running: bool):
        """启用/禁用停止入口"""
        self._is_running = bool(running)
        self.btn_stop.setEnabled(self._is_running)
    
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

    def append_error_details(self, error_list: list):
        """内联展示失败步骤摘要"""
        if not error_list:
            return
        self.log_text.append("")
        self.log_text.append(
            '<span style="color:#D32F2F;font-weight:bold;">'
            f'══ {len(error_list)} 个步骤失败 ══</span>'
        )
        for item in error_list:
            name = item.get("step_name", "")
            err = item.get("error_message", "")
            self.log_text.append(
                f'<span style="color:#D32F2F;">  ✖ {name}: {err}</span>'
            )
        # 滚动到底部
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text.setTextCursor(cursor)
