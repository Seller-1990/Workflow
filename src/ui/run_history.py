# -*- coding: utf-8 -*-
"""运行历史面板"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QMenu, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from database import get_run_histories_by_workflow, clear_run_histories, get_step_logs_by_run
from ui.collapsible_section import CollapsibleSection


class RunHistoryPanel(QWidget):
    """运行历史面板"""

    open_failures_requested = Signal(int)  # run_history_id
    
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
        
        # 标题与折叠按钮同一行
        self.section = CollapsibleSection("运行历史", collapsed=False, header_height=44, title_font_size=15, title_weight=700)
        group_layout = self.section.body_layout
        
        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([col[0] for col in self.COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)

        self.table.horizontalHeader().setFixedHeight(30)
        self.table.horizontalHeader().setStretchLastSection(True)

        # iOS Minimal：白色内嵌面板 + 表头浅底
        self.table.setStyleSheet(
            """
            QTableWidget {
                background: #FFFFFF;
                border: none;
                border-radius: 12px;
            }
            QHeaderView::section {
                background: #FAFBFC;
                border: none;
                padding: 6px 8px;
                color: #6B7280;
                font-size: 11px;
                font-weight: 600;
                text-transform: none;
            }
            QTableWidget::item { padding: 6px 8px; }
            """
        )
        
        # 设置列宽
        for i, (_, width) in enumerate(self.COLUMNS):
            self.table.setColumnWidth(i, width)
        
        group_layout.addWidget(self.table)
        
        layout.addWidget(self.section)
    
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
            run_item.setData(Qt.UserRole + 2, history.status)
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

            # 成功/失败/跳过统计（tooltip 提示，避免新增列挤压）
            try:
                logs = get_step_logs_by_run(history.id)
                counts = {"success": 0, "failure": 0, "skipped": 0, "running": 0, "pending": 0}
                for log in logs:
                    if log.status in counts:
                        counts[log.status] += 1
                summary = f"成功:{counts['success']} 失败:{counts['failure']} 跳过:{counts['skipped']}"
                run_item.setToolTip((run_item.toolTip() or "") + f"\n{summary}")
                status_item.setToolTip(summary)
            except Exception:
                pass
            
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
        
        history_id = run_item.data(Qt.UserRole)
        log_dir = run_item.data(Qt.UserRole + 1)
        raw_status = run_item.data(Qt.UserRole + 2)
        
        menu = QMenu(self)

        # 查看失败步骤（仅失败/有失败日志时可用）
        action_failures = menu.addAction("查看失败步骤")
        has_failures = False
        try:
            if history_id:
                logs = get_step_logs_by_run(int(history_id))
                has_failures = any(l.status == "failure" for l in logs)
        except Exception:
            has_failures = False
        action_failures.setEnabled(bool(history_id) and has_failures)
        if bool(history_id) and not has_failures:
            action_failures.setToolTip("该次运行没有失败步骤。")
        action_failures.triggered.connect(lambda: self.open_failures_requested.emit(int(history_id)))
        
        if log_dir and os.path.exists(log_dir):
            action_open = menu.addAction("打开日志目录")
            action_open.triggered.connect(lambda: self._open_log_dir(log_dir))

        menu.addSeparator()
        action_clear = menu.addAction("清除所有历史")
        action_clear.triggered.connect(self._on_clear_history)
        
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
