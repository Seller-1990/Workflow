# -*- coding: utf-8 -*-
"""错误汇总弹窗：工作流运行失败后显示所有失败步骤的摘要"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QHBoxLayout, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor


class ErrorSummaryDialog(QDialog):
    """错误汇总弹窗
    
    接收 error_details 信号的数据：
    [{"step_id": int, "step_name": str, "error_message": str}, ...]
    """
    navigate_to_step = Signal(int)     # step_id
    retry_failed = Signal()            # 一键重试失败步骤
    open_step_log = Signal(int)        # step_id（可选：外部处理）
    
    def __init__(self, error_list: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("运行失败汇总")
        self.setMinimumSize(600, 300)
        self._error_list = error_list or []
        self._setup_ui(self._error_list)
    
    def _setup_ui(self, error_list: list):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # 标题
        header = QLabel(f"共 {len(error_list)} 个步骤失败：")
        header.setStyleSheet("font-size: 14px; font-weight: bold; color: #D32F2F;")
        layout.addWidget(header)
        
        # 失败步骤表格
        self.table = QTableWidget(len(error_list), 2)
        self.table.setHorizontalHeaderLabels(["步骤名称", "错误信息"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(lambda r, c: self._navigate_selected())
        
        for row, item in enumerate(error_list):
            step_id = item.get("step_id")
            name_cell = QTableWidgetItem(item.get("step_name", ""))
            if step_id:
                name_cell.setData(Qt.UserRole, int(step_id))
            name_cell.setBackground(QColor("#FFEBEE"))
            self.table.setItem(row, 0, name_cell)
            
            err_cell = QTableWidgetItem(item.get("error_message", ""))
            err_cell.setToolTip(item.get("error_message", ""))
            err_cell.setBackground(QColor("#FFEBEE"))
            self.table.setItem(row, 1, err_cell)
        
        layout.addWidget(self.table)
        
        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_locate = QPushButton("定位到步骤")
        btn_locate.setMinimumWidth(100)
        btn_locate.clicked.connect(self._navigate_selected)
        btn_layout.addWidget(btn_locate)

        btn_open_log = QPushButton("打开步骤日志")
        btn_open_log.setMinimumWidth(110)
        btn_open_log.clicked.connect(self._open_selected_log)
        btn_layout.addWidget(btn_open_log)

        btn_retry = QPushButton("重试失败步骤")
        btn_retry.setMinimumWidth(110)
        btn_retry.clicked.connect(lambda: self.retry_failed.emit())
        btn_layout.addWidget(btn_retry)

        btn_layout.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.setMinimumWidth(80)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

    def _selected_step_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        step_id = item.data(Qt.UserRole)
        return int(step_id) if step_id else None

    def _navigate_selected(self):
        step_id = self._selected_step_id()
        if not step_id:
            QMessageBox.information(self, "提示", "请先选中一个失败步骤。")
            return
        self.navigate_to_step.emit(step_id)

    def _open_selected_log(self):
        step_id = self._selected_step_id()
        if not step_id:
            QMessageBox.information(self, "提示", "请先选中一个失败步骤。")
            return
        # 外部若绑定了 open_step_log，则优先交给外部（便于复用 LogPanel 的上下文）
        if self.receivers(self.open_step_log) > 0:
            self.open_step_log.emit(step_id)
            return
        # 否则做一个最小可用的打开动作（Windows：Notepad）
        try:
            import os
            import subprocess
            from database import get_latest_run_history, get_step_logs_by_run

            # parent 通常是 MainWindow，能提供当前 workflow_id
            workflow_id = getattr(self.parent(), "_current_workflow_id", None)
            if not workflow_id:
                return
            latest = get_latest_run_history(workflow_id)
            if not latest:
                return
            logs = get_step_logs_by_run(latest.id)
            target = next((l for l in logs if l.step_id == step_id), None)
            if not target:
                return
            for path in [getattr(target, "stdout_path", None), getattr(target, "stderr_path", None)]:
                if path and os.path.exists(path):
                    subprocess.run(["notepad", path])
                    return
        except Exception:
            return
