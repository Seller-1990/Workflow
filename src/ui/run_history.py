# -*- coding: utf-8 -*-
"""运行历史面板"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QMenu, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from database import get_run_histories_by_workflow, clear_run_histories


class RunHistoryPanel(QWidget):
    """运行历史面板"""
    
    # 列定义
    COLUMNS = [
        ("运行编号", 120),
        ("状态", 60),
        ("开始时间", 140),
        ("时长", 60),
    ]
    
    # 状态颜色
    STATUS_COLORS = {
        "success": QColor(76, 175, 80),
        "failure": QColor(244, 67, 54),
        "running": QColor(255, 193, 7),
        "cancelled": QColor(158, 158, 158),
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._workflow_id = None
        self._setup_ui()
    
    def _setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 分组框
        group = QGroupBox("运行历史")
        group.setCheckable(True)
        group.setChecked(True)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(12, 18, 12, 12)
        group_layout.setSpacing(10)
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([col[0] for col in self.COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.setMaximumHeight(200)
        
        # 设置列宽
        for i, (_, width) in enumerate(self.COLUMNS):
            self.table.setColumnWidth(i, width)
        
        group_layout.addWidget(self.table)
        
        # 清除按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_clear = QPushButton("清除历史")
        self.btn_clear.setFixedWidth(80)
        self.btn_clear.clicked.connect(self._on_clear_history)
        btn_layout.addWidget(self.btn_clear)
        group_layout.addLayout(btn_layout)
        
        layout.addWidget(group)

        group.toggled.connect(self.table.setVisible)
    
    def load_history(self, workflow_id: int):
        """加载运行历史"""
        self._workflow_id = workflow_id
        self.table.setRowCount(0)
        
        histories = get_run_histories_by_workflow(workflow_id, limit=20)
        self.table.setRowCount(len(histories))
        
        for row, history in enumerate(histories):
            # 运行编号
            run_item = QTableWidgetItem(history.run_id)
            run_item.setData(Qt.UserRole, history.id)
            run_item.setData(Qt.UserRole + 1, history.log_dir)
            self.table.setItem(row, 0, run_item)
            
            # 状态
            status_map = {
                "success": "成功",
                "failure": "失败",
                "running": "运行中",
                "cancelled": "已取消",
                "pending": "等待",
            }
            status_text = status_map.get(history.status, history.status)
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignCenter)
            
            color = self.STATUS_COLORS.get(history.status)
            if color:
                status_item.setForeground(color)
            
            self.table.setItem(row, 1, status_item)
            
            # 开始时间
            start_text = ""
            if history.start_time:
                start_text = history.start_time.strftime("%m-%d %H:%M:%S")
            start_item = QTableWidgetItem(start_text)
            self.table.setItem(row, 2, start_item)
            
            # 时长
            duration_text = ""
            if history.duration_seconds is not None:
                if history.duration_seconds < 60:
                    duration_text = f"{history.duration_seconds:.1f}s"
                else:
                    minutes = int(history.duration_seconds // 60)
                    seconds = int(history.duration_seconds % 60)
                    duration_text = f"{minutes}m{seconds}s"
            duration_item = QTableWidgetItem(duration_text)
            duration_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, duration_item)
    
    def clear(self):
        """清空"""
        self._workflow_id = None
        self.table.setRowCount(0)
    
    def _show_context_menu(self, pos):
        """显示右键菜单"""
        item = self.table.itemAt(pos)
        if not item:
            return
        
        row = self.table.row(item)
        run_item = self.table.item(row, 0)
        if not run_item:
            return
        
        log_dir = run_item.data(Qt.UserRole + 1)
        
        menu = QMenu(self)
        
        if log_dir and os.path.exists(log_dir):
            action_open = menu.addAction("打开日志目录")
            action_open.triggered.connect(lambda: self._open_log_dir(log_dir))
        
        menu.exec_(self.table.mapToGlobal(pos))
    
    def _open_log_dir(self, log_dir: str):
        """打开日志目录"""
        import subprocess
        subprocess.run(["explorer", log_dir])
    
    def _on_clear_history(self):
        """清除运行历史"""
        if not self._workflow_id:
            return
        
        reply = QMessageBox.question(
            self,
            "确认清除",
            "确定要清除所有运行历史记录吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            count = clear_run_histories(self._workflow_id)
            self.table.setRowCount(0)
            QMessageBox.information(
                self,
                "已清除",
                f"已清除 {count} 条运行历史记录"
            )
